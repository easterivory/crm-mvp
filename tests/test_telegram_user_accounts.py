from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

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
