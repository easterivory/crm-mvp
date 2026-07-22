from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.core.constants import RoleName, SenderType
from app.core.telegram_commands import (
    collect_funnel_telegram_commands,
    extract_telegram_command,
    normalize_telegram_command,
)
from app.models.bot import Bot
from app.schemas.funnel import FunnelEdgeIn, FunnelGraphIn, FunnelStepIn
from app.services.funnel_block_registry import FunnelBlockRegistry
from app.services.funnel_command_service import FunnelCommandService
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.funnel_service import FunnelService
from app.services import funnel_start_queue
from app.services.funnel_start_queue import enqueue_funnel_start
from app.services.funnel_validator import FunnelGraphValidator
from app.services.telegram_service import TelegramService


def command_step(command: str = "help", description: str = "Помощь") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        key=f"command_{command}",
        title=f"/{command}",
        step_type="trigger",
        block_type="generic_trigger",
        config_json={
            "trigger_type": "custom_command",
            "command": command,
            "command_description": description,
        },
    )


def test_command_normalization_accepts_telegram_mentions_and_arguments() -> None:
    assert normalize_telegram_command("/HELP@ExampleBot") == "help"
    assert extract_telegram_command(" /help@ExampleBot account ") == "help"
    assert extract_telegram_command("text /help") is None
    assert extract_telegram_command("/нельзя") is None


def test_custom_trigger_validation_is_strict_only_for_publishable_config() -> None:
    registry = FunnelBlockRegistry()

    assert registry.validate_block(
        "trigger",
        "generic_trigger",
        {
            "trigger_type": "custom_command",
            "command": "/help",
            "command_description": "Помощь",
        },
    ) == []
    errors = registry.validate_block(
        "trigger",
        "generic_trigger",
        {
            "trigger_type": "custom_command",
            "command": "/start",
            "command_description": "Повторный старт",
        },
    )
    assert any("зарезервирована" in error for error in errors)


def test_command_collection_keeps_first_unique_command() -> None:
    first = command_step("help", "Помощь")
    duplicate = command_step("/HELP", "Дубликат")
    commands = collect_funnel_telegram_commands([first, duplicate])

    assert [(item.command, item.description) for item in commands] == [
        ("help", "Помощь")
    ]


def test_command_menu_sync_uses_active_funnel_and_skips_tokenless_draft() -> None:
    project_id = uuid4()
    bot_id = uuid4()
    version = SimpleNamespace(id=uuid4())
    service = FunnelCommandService.__new__(FunnelCommandService)
    service.db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    service.bot_repo = SimpleNamespace(
        get_by_id_in_project=AsyncMock(
            side_effect=[
                SimpleNamespace(telegram_token=None, telegram_managed_commands=[]),
                SimpleNamespace(telegram_token="token", telegram_managed_commands=[]),
            ]
        ),
        update_in_project=AsyncMock(),
    )
    service.funnel_repo = SimpleNamespace(
        get_active_published_funnel_for_bot=AsyncMock(
            return_value=(SimpleNamespace(id=uuid4()), version)
        ),
        list_steps=AsyncMock(return_value=[command_step()]),
    )
    service.sender = SimpleNamespace(
        get_bot_commands=AsyncMock(
            return_value=[{"command": "status", "description": "Статус заявки"}]
        ),
        set_bot_commands=AsyncMock(return_value={"ok": True}),
    )

    assert not asyncio.run(service.sync_for_bot(bot_id=bot_id, project_id=project_id))
    assert asyncio.run(service.sync_for_bot(bot_id=bot_id, project_id=project_id))
    service.sender.set_bot_commands.assert_awaited_once_with(
        "token",
        [
            {"command": "start", "description": "Запустить бота"},
            {"command": "help", "description": "Помощь"},
            {"command": "status", "description": "Статус заявки"},
        ],
    )
    service.bot_repo.update_in_project.assert_awaited_once_with(
        bot_id,
        project_id,
        telegram_managed_commands=["help", "start"],
    )
    service.db.commit.assert_awaited_once()


def test_command_menu_removes_only_stale_funnel_managed_commands() -> None:
    project_id = uuid4()
    bot_id = uuid4()
    service = FunnelCommandService.__new__(FunnelCommandService)
    service.db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    service.bot_repo = SimpleNamespace(
        get_by_id_in_project=AsyncMock(
            return_value=SimpleNamespace(
                telegram_token="token",
                telegram_managed_commands=["start", "old_funnel_command"],
            )
        ),
        update_in_project=AsyncMock(),
    )
    service.funnel_repo = SimpleNamespace(
        get_active_published_funnel_for_bot=AsyncMock(
            return_value=(SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4()))
        ),
        list_steps=AsyncMock(return_value=[command_step("help", "Помощь")]),
    )
    service.sender = SimpleNamespace(
        get_bot_commands=AsyncMock(
            return_value=[
                {"command": "start", "description": "Запустить бота"},
                {"command": "old_funnel_command", "description": "Старая ветка"},
                {"command": "manual", "description": "Команда BotFather"},
            ]
        ),
        set_bot_commands=AsyncMock(return_value={"ok": True}),
    )

    assert asyncio.run(service.sync_for_bot(bot_id=bot_id, project_id=project_id))

    service.sender.set_bot_commands.assert_awaited_once_with(
        "token",
        [
            {"command": "start", "description": "Запустить бота"},
            {"command": "help", "description": "Помощь"},
            {"command": "manual", "description": "Команда BotFather"},
        ],
    )


def test_runtime_executes_custom_trigger_without_selecting_it_for_start() -> None:
    custom = command_step()
    default = SimpleNamespace(
        id=uuid4(),
        step_type="trigger",
        block_type="generic_trigger",
        config_json={"trigger_type": "new_chat"},
    )
    assert FunnelRuntimeService._default_start_trigger([custom, default]) is default

    service = FunnelRuntimeService.__new__(FunnelRuntimeService)
    service.repo = SimpleNamespace(
        lock_chat_for_runtime=AsyncMock(return_value=True),
        list_steps=AsyncMock(return_value=[custom, default]),
        cancel_scheduled_jobs_for_chat=AsyncMock(),
        upsert_chat_funnel_state=AsyncMock(),
    )
    service._log_runtime_step = AsyncMock()
    service._execute_from_step = AsyncMock(return_value=None)
    chat_id = uuid4()
    funnel_id = uuid4()
    version_id = uuid4()

    result = asyncio.run(
        service.execute_custom_command_for_chat(
            chat_id=chat_id,
            funnel_id=funnel_id,
            funnel_version_id=version_id,
            command="/HELP@ExampleBot",
        )
    )

    assert result is custom
    service.repo.cancel_scheduled_jobs_for_chat.assert_awaited_once_with(chat_id=chat_id)
    upsert = service.repo.upsert_chat_funnel_state.await_args.kwargs
    assert upsert["completed_at"] is None
    assert upsert["runtime_json"]["custom_command"]["command"] == "help"
    service._execute_from_step.assert_awaited_once_with(chat_id=chat_id, step=custom)


def test_legacy_trigger_without_trigger_type_remains_the_default_start() -> None:
    legacy_trigger = SimpleNamespace(
        id=uuid4(),
        step_type="trigger",
        block_type="generic_trigger",
        config_json={},
    )
    custom = command_step("help", "Помощь")

    assert FunnelRuntimeService._default_start_trigger([legacy_trigger, custom]) is legacy_trigger


def test_funnel_start_queue_keeps_the_legacy_worker_signature(monkeypatch) -> None:
    redis = SimpleNamespace(
        enqueue_job=AsyncMock(return_value=SimpleNamespace(id="job")),
        close=AsyncMock(),
    )
    monkeypatch.setattr(
        funnel_start_queue,
        "create_pool",
        AsyncMock(return_value=redis),
    )
    chat_id = uuid4()
    message_id = uuid4()

    assert asyncio.run(
        enqueue_funnel_start(
            chat_id,
            message_id,
            fresh_lifecycle=False,
        )
    )
    call = redis.enqueue_job.await_args
    assert call.args == (
        "process_funnel_start_task",
        str(chat_id),
        str(message_id),
        False,
    )


def test_queued_custom_command_runs_active_funnel_branch() -> None:
    chat_id = uuid4()
    message_id = uuid4()
    bot_id = uuid4()
    project_id = uuid4()
    funnel_id = uuid4()
    version_id = uuid4()
    chat = SimpleNamespace(
        id=chat_id,
        bot_id=bot_id,
        project_id=project_id,
        is_deleted=False,
        reset_at=None,
    )
    message = SimpleNamespace(id=message_id, body="/help")
    trigger = command_step()
    service = TelegramService.__new__(TelegramService)
    service.chat_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=chat))
    service.message_repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=message),
        claim_funnel_processing=AsyncMock(return_value=True),
    )
    service.bot_repo = SimpleNamespace(reset_chat_state=AsyncMock())
    service.funnel_runtime = SimpleNamespace(
        get_active_published_funnel_for_bot=AsyncMock(
            return_value=(SimpleNamespace(id=funnel_id), SimpleNamespace(id=version_id))
        ),
        get_custom_command_trigger=AsyncMock(return_value=trigger),
        execute_custom_command_for_chat=AsyncMock(return_value=trigger),
    )

    result = asyncio.run(
        service.process_queued_funnel_start(
            chat_id=chat_id,
            trigger_message_id=message_id,
            fresh_lifecycle=False,
        )
    )

    assert result == "processed"
    service.funnel_runtime.execute_custom_command_for_chat.assert_awaited_once_with(
        chat_id=chat_id,
        funnel_id=funnel_id,
        funnel_version_id=version_id,
        command="help",
    )


def test_unknown_command_keeps_existing_new_chat_start_behavior() -> None:
    chat_id = uuid4()
    message_id = uuid4()
    chat = SimpleNamespace(
        id=chat_id,
        bot_id=uuid4(),
        project_id=uuid4(),
        is_deleted=False,
        reset_at=None,
    )
    message = SimpleNamespace(
        id=message_id,
        chat_id=chat_id,
        external_message_id=None,
        body="/unknown",
        caption=None,
        message_type="text",
        sender_type=SenderType.USER,
        sender_id=None,
        created_at=datetime.now(timezone.utc),
    )
    service = TelegramService.__new__(TelegramService)
    service.chat_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=chat))
    service.message_repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=message),
        claim_funnel_processing=AsyncMock(return_value=True),
    )
    service.funnel_runtime = SimpleNamespace(
        get_active_published_funnel_for_bot=AsyncMock(
            return_value=(SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4()))
        ),
        get_custom_command_trigger=AsyncMock(return_value=None),
    )
    service._process_runtime_or_legacy = AsyncMock()

    result = asyncio.run(
        service.process_queued_funnel_start(
            chat_id=chat_id,
            trigger_message_id=message_id,
            fresh_lifecycle=True,
        )
    )

    assert result == "processed"
    service._process_runtime_or_legacy.assert_awaited_once()


def test_publish_validation_requires_a_default_start_trigger() -> None:
    command_id = uuid4()
    finish_id = uuid4()
    graph = FunnelGraphIn(
        steps=[
            FunnelStepIn(
                id=command_id,
                key="help",
                title="Помощь",
                step_type="trigger",
                block_type="generic_trigger",
                config_json={
                    "trigger_type": "custom_command",
                    "command": "help",
                    "command_description": "Помощь",
                },
            ),
            FunnelStepIn(
                id=finish_id,
                key="finish",
                title="Завершение",
                step_type="finish",
                block_type="generic_finish",
                config_json={"result": "stop"},
            ),
        ],
        edges=[FunnelEdgeIn(from_step_id=command_id, to_step_id=finish_id)],
    )
    service = FunnelService.__new__(FunnelService)
    service.registry = FunnelBlockRegistry()
    service.graph_validator = FunnelGraphValidator()

    validation = service._validate_graph_payload(graph, strict_config=True)

    assert any(issue.code == "missing_default_trigger" for issue in validation.errors)


def test_tokenless_bot_draft_graph_saves_without_telegram_dependency() -> None:
    trigger_id = uuid4()
    message_id = uuid4()
    finish_id = uuid4()
    graph = FunnelGraphIn(
        steps=[
            FunnelStepIn(
                id=trigger_id,
                key="start",
                title="Старт",
                step_type="trigger",
                block_type="generic_trigger",
                config_json={"trigger_type": "new_chat"},
            ),
            FunnelStepIn(
                id=message_id,
                key="message",
                title="Сообщение",
                step_type="message",
                block_type="generic_message",
                config_json={"text": "Здравствуйте"},
            ),
            FunnelStepIn(
                id=finish_id,
                key="finish",
                title="Завершение",
                step_type="finish",
                block_type="generic_finish",
                config_json={"result": "stop"},
            ),
        ],
        edges=[
            FunnelEdgeIn(from_step_id=trigger_id, to_step_id=message_id),
            FunnelEdgeIn(from_step_id=message_id, to_step_id=finish_id),
        ],
    )
    service = FunnelService.__new__(FunnelService)
    service.repo = SimpleNamespace(
        get_version_in_project=AsyncMock(
            return_value=SimpleNamespace(id=uuid4(), status="draft")
        ),
        replace_graph=AsyncMock(),
    )
    service.registry = FunnelBlockRegistry()
    service.graph_validator = FunnelGraphValidator()
    service._graph_out = AsyncMock(return_value="saved")
    service.bot_repo = SimpleNamespace(
        get_bot_token_by_id=AsyncMock(side_effect=AssertionError("token lookup is forbidden"))
    )

    result = asyncio.run(
        service.save_graph(
            funnel_id=uuid4(),
            version_id=uuid4(),
            project_id=uuid4(),
            graph=graph,
            current_user=SimpleNamespace(role_name=RoleName.ADMIN),
        )
    )

    assert result == "saved"
    service.repo.replace_graph.assert_awaited_once()
    service.bot_repo.get_bot_token_by_id.assert_not_awaited()
    assert Bot.__table__.c.telegram_token.nullable is True
