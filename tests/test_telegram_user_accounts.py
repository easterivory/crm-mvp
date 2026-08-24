from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.bot import BotCreate, TelegramAccountConnectIn
from app.schemas.telegram import TelegramChat, TelegramMessage, TelegramUser
from app.services.bot_service import BotService
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.telegram_account_credential_service import (
    TelegramAccountCredentialService,
)
from app.services.telegram_account_gateway import (
    TelegramAccountGateway,
    TelegramAccountGatewayError,
)
from app.services.telegram_sender import TelegramSenderService
from app.services.telegram_service import TelegramService
from app.services.telegram_user_account_service import TelegramUserAccountService
from app.services.tracking_service import TrackingService
from app.workers.telegram_account_worker import TelegramAccountWorker


def test_named_account_creation_is_opt_in_and_never_uses_bot_token() -> None:
    project_id = uuid4()
    bot_id = uuid4()
    service = BotService.__new__(BotService)
    service.bot_repo = SimpleNamespace(
        create=AsyncMock(return_value=SimpleNamespace(id=bot_id))
    )
    service._resolve_project_for_create = AsyncMock(
        return_value=SimpleNamespace(id=project_id)
    )
    service._fetch_telegram_bot_info = AsyncMock()
    service._set_webhook_for_token = AsyncMock()
    service.get_bot = AsyncMock(return_value="account-result")

    result = asyncio.run(
        service.create_bot(
            project_id=project_id,
            data=BotCreate(
                name="Sales account",
                transport_type="user_mtproto",
            ),
        )
    )

    assert result == "account-result"
    service._fetch_telegram_bot_info.assert_not_awaited()
    service._set_webhook_for_token.assert_not_awaited()
    service.bot_repo.create.assert_awaited_once_with(
        project_id=project_id,
        name="Sales account",
        transport_type="user_mtproto",
        telegram_token=None,
        crm_description=None,
        telegram_description=None,
        telegram_about=None,
    )


def test_named_account_rejects_bot_token() -> None:
    service = BotService.__new__(BotService)
    service._resolve_project_for_create = AsyncMock(
        return_value=SimpleNamespace(id=uuid4())
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            service.create_bot(
                project_id=uuid4(),
                data=BotCreate(
                    name="Sales account",
                    telegram_token="123456:token",
                    transport_type="user_mtproto",
                ),
            )
        )

    assert exc_info.value.status_code == 422


def test_api_hash_validation_is_strict() -> None:
    valid = TelegramAccountConnectIn(
        api_id=12345,
        api_hash="a" * 32,
        phone_number="+79990001122",
    )
    assert valid.api_hash == "a" * 32

    with pytest.raises(ValidationError):
        TelegramAccountConnectIn(
            api_id=12345,
            api_hash="not-an-api-hash",
            phone_number="+79990001122",
        )


def test_account_credentials_are_encrypted_at_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "TELEGRAM_ACCOUNT_ENCRYPTION_KEY", "test-key")
    credentials = TelegramAccountCredentialService()
    encrypted = credentials.encrypt("0123456789abcdef0123456789abcdef")

    assert "0123456789abcdef" not in encrypted
    assert credentials.decrypt(encrypted, label="API hash") == (
        "0123456789abcdef0123456789abcdef"
    )


def test_account_login_assigns_uuid_before_the_first_database_flush(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "TELEGRAM_ACCOUNT_ENCRYPTION_KEY", "test-key")
    bot_id = uuid4()
    project_id = uuid4()
    connection = SimpleNamespace(auth_status="disconnected")
    authorized = SimpleNamespace(auth_status="awaiting_code")
    client = SimpleNamespace(
        connect=AsyncMock(),
        disconnect=AsyncMock(),
        send_code_request=AsyncMock(
            return_value=SimpleNamespace(phone_code_hash="phone-code-hash")
        ),
    )

    service = TelegramUserAccountService.__new__(TelegramUserAccountService)
    service.db = SimpleNamespace(commit=AsyncMock())
    service.bot_repo = SimpleNamespace()
    service.connection_repo = SimpleNamespace(
        get_by_bot_id=AsyncMock(return_value=None),
        create=AsyncMock(return_value=connection),
        update_by_bot_id=AsyncMock(return_value=authorized),
    )
    service.credentials = TelegramAccountCredentialService()
    service._get_account_bot = AsyncMock(return_value=SimpleNamespace(id=bot_id))
    service._client = lambda **_kwargs: client
    service._save_session = lambda _client: "session"
    service._audit = AsyncMock()
    service._status_out = lambda _bot_id, _connection: "awaiting-code"

    result = asyncio.run(
        service.request_login_code(
            bot_id=bot_id,
            project_id=project_id,
            data=TelegramAccountConnectIn(
                api_id=12345,
                api_hash="a" * 32,
                phone_number="+79990001122",
            ),
            actor=SimpleNamespace(),
        )
    )

    assert result == "awaiting-code"
    create_kwargs = service.connection_repo.create.await_args.kwargs
    assert isinstance(create_kwargs["id"], type(bot_id))
    assert create_kwargs["bot_id"] == bot_id


def test_account_sender_uses_mtproto_gateway_and_text_button_analogues() -> None:
    bot_id = uuid4()
    project_id = uuid4()
    sender = TelegramSenderService.__new__(TelegramSenderService)
    sender._get_transport_type = AsyncMock(return_value="user_mtproto")
    sender._invoke_account_gateway = AsyncMock(
        return_value={"message_id": 77, "_transport": "user_mtproto"}
    )

    result = asyncio.run(
        sender.send_message(
            project_id=project_id,
            bot_id=bot_id,
            external_chat_id="12345",
            text="Выберите действие",
            reply_markup={
                "inline_keyboard": [
                    [{"text": "Продолжить", "callback_data": "next"}],
                    [{"text": "Документы", "url": "https://example.com/docs"}],
                ]
            },
        )
    )

    assert result == {"message_id": 77, "_transport": "user_mtproto"}
    payload = sender._invoke_account_gateway.await_args.kwargs["payload"]
    assert "• Продолжить" in payload["text"]
    assert "Документы: https://example.com/docs" in payload["text"]


def test_account_branch_fallback_does_not_treat_url_or_contact_as_answer() -> None:
    buttons = [
        {"id": "next", "label": "Далее", "value": "next", "type": "branch"},
        {"id": "site", "label": "Сайт", "value": "site", "type": "url"},
        {"id": "phone", "label": "Телефон", "value": "contact", "type": "contact"},
    ]

    assert FunnelRuntimeService._choice_for_account_buttons(buttons, "Далее") == buttons[0]
    assert FunnelRuntimeService._choice_for_account_buttons(buttons, "Сайт") is None
    assert FunnelRuntimeService._choice_for_account_buttons(buttons, "Телефон") is None
    assert FunnelRuntimeService._account_contact_choice(buttons, "+7 999 000-11-22") == buttons[2]


def test_mtproto_incoming_payload_is_marked_without_start_attribution() -> None:
    message = TelegramMessage(
        message_id=11,
        text="/start old-reference",
        chat=TelegramChat(id=12345, type="private", access_hash=777),
        from_user=TelegramUser(id=12345, first_name="Lead"),
    )

    created = TelegramService._telegram_message_to_create(
        message,
        source_transport="user_mtproto",
    )

    assert created.raw_payload_json is not None
    assert created.raw_payload_json["_transport"] == "user_mtproto"


def test_mtproto_history_import_is_claimed_without_replaying_funnel() -> None:
    project_id = uuid4()
    bot_id = uuid4()
    chat_id = uuid4()
    lead_id = uuid4()
    persisted_message_id = uuid4()
    sent_at = datetime(2026, 8, 20, 12, 30, tzinfo=timezone.utc)
    update = SimpleNamespace(
        message=TelegramMessage(
            message_id=91,
            text="Старое сообщение",
            chat=TelegramChat(id=12345, type="private", access_hash=777),
            from_user=TelegramUser(id=12345, first_name="Lead"),
        )
    )

    service = TelegramService.__new__(TelegramService)
    service._find_or_create_chat = AsyncMock(
        return_value=(SimpleNamespace(id=chat_id), True, False)
    )
    service._find_or_create_lead = AsyncMock(
        return_value=SimpleNamespace(id=lead_id)
    )
    service.message_repo = SimpleNamespace(
        get_by_external_id=AsyncMock(return_value=None),
        claim_funnel_processing=AsyncMock(return_value=True),
    )
    service.message_service = SimpleNamespace(
        create_message=AsyncMock(
            return_value=SimpleNamespace(id=persisted_message_id)
        )
    )
    service.chat_repo = SimpleNamespace(update_by_id=AsyncMock())
    service.lead_repo = SimpleNamespace(update_by_id=AsyncMock())

    result = asyncio.run(
        service.handle_mtproto_history_message(
            update=update,
            project_id=project_id,
            bot_id=bot_id,
            sent_at=sent_at,
            outgoing=False,
        )
    )

    assert result is not None
    assert result.chat_id == chat_id
    create_call = service.message_service.create_message.await_args
    assert create_call.kwargs["send_to_telegram"] is False
    assert create_call.kwargs["translate_incoming"] is False
    data = create_call.kwargs["data"]
    assert data.created_at == sent_at
    assert data.raw_payload_json["mtproto_history_import"] is True
    service.message_repo.claim_funnel_processing.assert_awaited_once_with(
        [persisted_message_id]
    )


def test_live_input_starts_funnel_for_existing_mtproto_dialog() -> None:
    chat_id = uuid4()
    project_id = uuid4()
    bot_id = uuid4()
    version_id = uuid4()
    history_message = SimpleNamespace(
        id=uuid4(),
        sender_type="bot",
        is_external_account_message=True,
        raw_payload_json={
            "mtproto_manual_outgoing": True,
            "mtproto_history_import": True,
        },
    )
    service = TelegramService.__new__(TelegramService)
    service.message_repo = SimpleNamespace(
        get_latest_outgoing_message=AsyncMock(return_value=history_message),
    )
    service.funnel_runtime = SimpleNamespace(
        get_active_published_funnel_for_bot=AsyncMock(
            return_value=(SimpleNamespace(id=uuid4()), SimpleNamespace(id=version_id)),
        ),
        get_state_status=AsyncMock(return_value=("not_started", None)),
    )

    should_start = asyncio.run(
        service._should_start_mtproto_runtime(
            chat_id=chat_id,
            project_id=project_id,
            bot_id=bot_id,
            lead_import_id=None,
        )
    )

    assert should_start is True
    service.funnel_runtime.get_state_status.assert_awaited_once_with(
        chat_id=chat_id,
        active_funnel_version_id=version_id,
    )


def test_existing_named_account_chat_queues_funnel_on_live_input() -> None:
    chat_id = uuid4()
    message_id = uuid4()
    project_id = uuid4()
    bot_id = uuid4()
    chat = SimpleNamespace(
        id=chat_id,
        external_chat_id="8053174284",
        is_blocked=False,
        lead_import_id=None,
        tracking_link_id=None,
    )
    message = TelegramMessage(
        message_id=101,
        chat=TelegramChat(id=8053174284, access_hash=123456),
        from_user=TelegramUser(
            id=8053174284,
            first_name="Виктор",
            username="smmirnovvictor",
        ),
        text="Здравствуйте",
    )
    service = TelegramService.__new__(TelegramService)
    service.db = SimpleNamespace(commit=AsyncMock())
    service._resolve_tracking_link_id = AsyncMock(return_value=None)
    service._find_or_create_chat = AsyncMock(return_value=(chat, False, False))
    service._create_message = AsyncMock(
        return_value=SimpleNamespace(id=message_id, external_message_id="101")
    )
    service.message_repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=SimpleNamespace(funnel_processed_at=None)),
    )
    service._find_or_create_lead = AsyncMock(
        return_value=SimpleNamespace(id=uuid4())
    )
    service._save_shared_contact = AsyncMock(return_value=False)
    service._attach_utm_bridge_data = AsyncMock()
    service._should_start_mtproto_runtime = AsyncMock(return_value=True)

    update = SimpleNamespace(
        update_id=101,
        message=message,
        callback_query=None,
        my_chat_member=None,
    )
    with patch(
        "app.services.telegram_service.enqueue_funnel_start",
        new=AsyncMock(return_value=True),
    ) as enqueue_start:
        asyncio.run(
            service.handle_update(
                update=update,
                project_id=project_id,
                bot_id=bot_id,
                source_transport="user_mtproto",
            )
        )

    service._should_start_mtproto_runtime.assert_awaited_once_with(
        chat_id=chat_id,
        project_id=project_id,
        bot_id=bot_id,
        lead_import_id=None,
    )
    enqueue_start.assert_awaited_once_with(
        chat_id,
        message_id,
        fresh_lifecycle=True,
    )
    service.db.commit.assert_awaited_once()


def test_mtproto_import_does_not_restart_active_or_manually_handled_dialog() -> None:
    chat_id = uuid4()
    project_id = uuid4()
    bot_id = uuid4()
    version_id = uuid4()
    service = TelegramService.__new__(TelegramService)
    service.message_repo = SimpleNamespace(
        get_latest_outgoing_message=AsyncMock(return_value=None),
    )
    service.funnel_runtime = SimpleNamespace(
        get_active_published_funnel_for_bot=AsyncMock(
            return_value=(SimpleNamespace(id=uuid4()), SimpleNamespace(id=version_id)),
        ),
        get_state_status=AsyncMock(return_value=("waiting_for_answer", SimpleNamespace())),
    )

    active_should_start = asyncio.run(
        service._should_start_mtproto_runtime(
            chat_id=chat_id,
            project_id=project_id,
            bot_id=bot_id,
            lead_import_id=None,
        )
    )

    service.message_repo.get_latest_outgoing_message = AsyncMock(
        return_value=SimpleNamespace(
            id=uuid4(),
            sender_type="manager",
            is_external_account_message=False,
            raw_payload_json={},
        )
    )
    service.funnel_runtime.get_state_status.reset_mock()
    manual_should_start = asyncio.run(
        service._should_start_mtproto_runtime(
            chat_id=chat_id,
            project_id=project_id,
            bot_id=bot_id,
            lead_import_id=None,
        )
    )

    assert active_should_start is False
    assert manual_should_start is False
    service.funnel_runtime.get_state_status.assert_not_awaited()


def test_spreadsheet_import_never_auto_starts_mtproto_funnel() -> None:
    service = TelegramService.__new__(TelegramService)
    service.message_repo = SimpleNamespace(
        get_latest_outgoing_message=AsyncMock(return_value=None),
    )
    service.funnel_runtime = SimpleNamespace(
        get_active_published_funnel_for_bot=AsyncMock(),
        get_state_status=AsyncMock(),
    )

    should_start = asyncio.run(
        service._should_start_mtproto_runtime(
            chat_id=uuid4(),
            project_id=uuid4(),
            bot_id=uuid4(),
            lead_import_id=uuid4(),
        )
    )

    assert should_start is False
    service.message_repo.get_latest_outgoing_message.assert_not_awaited()
    service.funnel_runtime.get_active_published_funnel_for_bot.assert_not_awaited()


def test_tracking_link_is_rejected_only_for_named_account() -> None:
    bot_id = uuid4()
    project_id = uuid4()
    service = TrackingService.__new__(TrackingService)
    service.bot_repo = SimpleNamespace(
        get_transport_type=AsyncMock(return_value="user_mtproto")
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service._ensure_bot_supports_tracking(bot_id, project_id))

    assert exc_info.value.status_code == 422

    service.bot_repo.get_transport_type = AsyncMock(return_value="bot_api")
    asyncio.run(service._ensure_bot_supports_tracking(bot_id, project_id))


def test_worker_sync_cursor_normalizes_naive_datetime() -> None:
    value = datetime(2026, 8, 22, 12, 0, 0)
    normalized = TelegramAccountWorker._as_utc(value)

    assert normalized is not None
    assert normalized.tzinfo == timezone.utc


def test_account_gateway_wraps_queue_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import telegram_account_gateway as gateway_module

    redis = SimpleNamespace(
        rpush=AsyncMock(side_effect=RuntimeError("redis unavailable")),
        delete=AsyncMock(),
    )
    monkeypatch.setattr(gateway_module, "get_redis", AsyncMock(return_value=redis))

    with pytest.raises(TelegramAccountGatewayError) as exc_info:
        asyncio.run(
            TelegramAccountGateway().invoke(
                bot_id=uuid4(),
                operation="send_message",
                payload={"external_chat_id": "123", "text": "Hello"},
                timeout_seconds=1,
            )
        )

    assert exc_info.value.transient is True
    redis.delete.assert_awaited_once()


def test_account_worker_ignores_bots_and_saved_messages() -> None:
    assert TelegramAccountWorker._is_supported_private_peer(
        SimpleNamespace(id=100, bot=False, is_self=False)
    )
    assert not TelegramAccountWorker._is_supported_private_peer(
        SimpleNamespace(id=200, bot=True, is_self=False)
    )
    assert not TelegramAccountWorker._is_supported_private_peer(
        SimpleNamespace(id=300, bot=False, is_self=True)
    )


def test_account_worker_snapshots_connection_ids_before_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers import telegram_account_worker as worker_module

    bot_id = uuid4()

    class ExpiringConnection:
        def __init__(self) -> None:
            self.expired = False

        @property
        def bot_id(self) -> UUID:
            if self.expired:
                raise RuntimeError("detached ORM attribute access")
            return bot_id

    connection = ExpiringConnection()

    class FakeSession:
        async def rollback(self) -> None:
            connection.expired = True

    class FakeSessionContext:
        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, *_args):
            return False

    class FakeRepository:
        def __init__(self, _db) -> None:
            pass

        async def list_authorized(self):
            return [connection]

    monkeypatch.setattr(worker_module, "get_db_session", FakeSessionContext)
    monkeypatch.setattr(
        worker_module,
        "TelegramUserConnectionRepository",
        FakeRepository,
    )

    async def scenario() -> None:
        worker = TelegramAccountWorker()
        release = asyncio.Event()

        async def hold_connection(_bot_id) -> None:
            await release.wait()

        worker._run_connection = hold_connection
        await worker._refresh_connections()
        assert bot_id in worker.connection_tasks
        release.set()
        await asyncio.gather(*worker.connection_tasks.values())

    asyncio.run(scenario())


def test_account_worker_runs_safe_initial_sync_before_regular_catchup() -> None:
    async def scenario() -> None:
        worker = TelegramAccountWorker()
        bot_id = uuid4()
        project_id = uuid4()
        client = SimpleNamespace()
        worker._load_sync_cursor = AsyncMock(
            return_value=(datetime.now(timezone.utc), 12345, True)
        )
        worker._sync_initial_dialogs = AsyncMock()
        worker._touch_last_sync = AsyncMock()

        await worker._sync_missed_messages(
            client=client,
            bot_id=bot_id,
            project_id=project_id,
        )

        worker._sync_initial_dialogs.assert_awaited_once_with(
            client=client,
            bot_id=bot_id,
            project_id=project_id,
            own_user_id=12345,
        )
        worker._touch_last_sync.assert_awaited_once_with(bot_id)

    asyncio.run(scenario())
