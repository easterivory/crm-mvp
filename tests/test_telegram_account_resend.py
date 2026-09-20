import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from telethon.tl.functions.auth import ResendCodeRequest

from app.services.telegram_user_account_service import TelegramUserAccountService


def setup_service(*, recent=False, changed=False, fail=False):
    now = datetime.now(timezone.utc)
    pending = SimpleNamespace(auth_status="awaiting_code", api_id=123, phone_number="+10000000000",
        updated_at=now - timedelta(seconds=5 if recent else 120),
        auth_expires_at=now + timedelta(minutes=10), phone_code_hash_encrypted="encrypted-old")
    current = SimpleNamespace(**vars(pending))
    if changed:
        current.auth_status = "authorized"
    service = TelegramUserAccountService.__new__(TelegramUserAccountService)
    service.db = SimpleNamespace(commit=AsyncMock(), expire_all=Mock())
    service._get_account_bot = AsyncMock()
    service.connection_repo = SimpleNamespace(
        get_by_bot_id=AsyncMock(side_effect=[pending, current]),
        update_by_bot_id=AsyncMock(return_value=current))
    service._decrypt_login_state = Mock(return_value=("secret", "old-session", "old-hash"))
    client = AsyncMock(return_value=SimpleNamespace(phone_code_hash="new-hash"))
    if fail:
        client.side_effect = RuntimeError("network unavailable")
    service._client = Mock(return_value=client)
    service._save_session = Mock(return_value="new-session")
    service.credentials = SimpleNamespace(encrypt=lambda value: f"encrypted:{value}")
    service._audit = AsyncMock()
    service._status_out = Mock(return_value="result")
    return service, client


def test_resend_reuses_pending_session_and_replaces_encrypted_hash():
    service, client = setup_service()
    result = asyncio.run(service.resend_login_code(bot_id=uuid4(), project_id=uuid4(), actor=SimpleNamespace()))
    assert result == "result"
    request = client.await_args.args[0]
    assert isinstance(request, ResendCodeRequest)
    assert request.phone_code_hash == "old-hash"
    assert service._client.call_args.kwargs["session"] == "old-session"
    saved = service.connection_repo.update_by_bot_id.await_args.kwargs
    assert saved["phone_code_hash_encrypted"] == "encrypted:new-hash"
    assert saved["session_encrypted"] == "encrypted:new-session"
    client.disconnect.assert_awaited_once()


@pytest.mark.parametrize("recent,changed,fail,status", [(True, False, False, 429),
    (False, True, False, 409), (False, False, True, 502)])
def test_resend_guards_pending_state(recent, changed, fail, status):
    service, client = setup_service(recent=recent, changed=changed, fail=fail)
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.resend_login_code(bot_id=uuid4(), project_id=uuid4(), actor=SimpleNamespace()))
    assert error.value.status_code == status
    assert all("session_encrypted" not in call.kwargs for call in service.connection_repo.update_by_bot_id.await_args_list)
    if recent:
        client.assert_not_awaited()
    else:
        client.disconnect.assert_awaited_once()
