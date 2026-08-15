from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.constants import RoleName
from app.core.constants import SenderType
from app.services.message_service import MessageService


def _operator(*, primary_project_id, extra_project_ids=()):
    return SimpleNamespace(
        is_deleted=False,
        role_name=RoleName.MANAGER,
        project_id=primary_project_id,
        project_accesses=[
            SimpleNamespace(project_id=project_id)
            for project_id in extra_project_ids
        ],
    )


def test_manager_can_send_in_additional_project() -> None:
    primary_project_id = uuid4()
    additional_project_id = uuid4()
    service = MessageService.__new__(MessageService)
    service.user_repo = SimpleNamespace(
        get_by_id=AsyncMock(
            return_value=_operator(
                primary_project_id=primary_project_id,
                extra_project_ids=(additional_project_id,),
            )
        )
    )

    asyncio.run(
        service._ensure_operator_can_send(uuid4(), additional_project_id)
    )


def test_manager_cannot_send_without_project_access() -> None:
    service = MessageService.__new__(MessageService)
    service.user_repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=_operator(primary_project_id=uuid4()))
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service._ensure_operator_can_send(uuid4(), uuid4()))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Operator is not a member of this project"


def test_super_admin_can_send_in_any_project() -> None:
    service = MessageService.__new__(MessageService)
    service.user_repo = SimpleNamespace(
        get_by_id=AsyncMock(
            return_value=SimpleNamespace(
                is_deleted=False,
                role_name=RoleName.SUPER_ADMIN,
                project_id=None,
                project_accesses=[],
            )
        )
    )

    asyncio.run(service._ensure_operator_can_send(uuid4(), uuid4()))


def test_outgoing_message_translation_targets_operator_language() -> None:
    project_id = uuid4()
    chat_id = uuid4()
    message_id = uuid4()
    expected = SimpleNamespace(id=message_id)
    message = SimpleNamespace(
        id=message_id,
        chat_id=chat_id,
        sender_type=SenderType.BOT,
        operator_id=None,
        body="Hola, como estas?",
        caption=None,
        original_text=None,
        translated_text=None,
    )
    service = MessageService.__new__(MessageService)
    service.db = SimpleNamespace(flush=AsyncMock(), refresh=AsyncMock())
    service.chat_repo = SimpleNamespace(
        get_active=AsyncMock(return_value=SimpleNamespace(id=chat_id))
    )
    service.project_repo = SimpleNamespace(
        get_active=AsyncMock(
            return_value=SimpleNamespace(operator_lang="ru", default_client_lang="es")
        )
    )
    service.message_repo = SimpleNamespace(
        get_by_id_in_project=AsyncMock(return_value=message)
    )
    service.translation_service = SimpleNamespace(
        translate_text=AsyncMock(return_value="Привет, как дела?")
    )
    service._message_out = AsyncMock(return_value=expected)

    result = asyncio.run(
        service.translate_message_on_demand(
            chat_id=chat_id,
            project_id=project_id,
            message_id=message_id,
        )
    )

    assert result is expected
    service.translation_service.translate_text.assert_awaited_once_with(
        "Hola, como estas?",
        source_lang=None,
        target_lang="ru",
        raise_on_failure=True,
    )


def test_reply_parameters_reference_message_in_same_chat() -> None:
    project_id = uuid4()
    chat_id = uuid4()
    reply_id = uuid4()
    service = MessageService.__new__(MessageService)
    service.message_repo = SimpleNamespace(
        get_by_id_in_project=AsyncMock(
            return_value=SimpleNamespace(
                id=reply_id,
                chat_id=chat_id,
                external_message_id="731",
                deleted_at=None,
            )
        )
    )

    result = asyncio.run(
        service._telegram_reply_parameters(
            chat_id=chat_id,
            project_id=project_id,
            reply_to_message_id=reply_id,
        )
    )

    assert result == {
        "message_id": 731,
        "allow_sending_without_reply": False,
    }


def test_old_telegram_message_is_not_deleted_locally() -> None:
    project_id = uuid4()
    chat_id = uuid4()
    message_id = uuid4()
    service = MessageService.__new__(MessageService)
    service._ensure_operator_can_send = AsyncMock()
    service.chat_repo = SimpleNamespace(
        get_active=AsyncMock(
            return_value=SimpleNamespace(
                id=chat_id,
                bot_id=uuid4(),
                external_chat_id="100500",
            )
        )
    )
    service.message_repo = SimpleNamespace(
        get_by_id_in_project=AsyncMock(
            return_value=SimpleNamespace(
                id=message_id,
                chat_id=chat_id,
                external_message_id="42",
                deleted_at=None,
                created_at=datetime.now(timezone.utc) - timedelta(hours=49),
            )
        ),
        mark_deleted=AsyncMock(),
    )
    service.telegram_sender = SimpleNamespace(delete_message=AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            service.delete_message(
                chat_id=chat_id,
                project_id=project_id,
                message_id=message_id,
                operator_id=uuid4(),
            )
        )

    assert exc_info.value.status_code == 422
    assert "48 часов" in exc_info.value.detail
    service.telegram_sender.delete_message.assert_not_awaited()
    service.message_repo.mark_deleted.assert_not_awaited()
