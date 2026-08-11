from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.schemas.bot import BotOut, BotUpdate
from app.services.bot_service import BotService


VALID_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghi"


def _bot_out(*, bot_id, project_id, warning: str | None = None) -> BotOut:
    now = datetime.now(timezone.utc)
    return BotOut(
        id=bot_id,
        project_id=project_id,
        name="VB Promo",
        has_telegram_token=True,
        telegram_bot_id=123456789,
        telegram_first_name="VB Promo",
        bot_username="vbpromobot",
        created_at=now,
        updated_at=now,
        is_deleted=False,
        telegram_setup_warning=warning,
    )


def test_token_normalization_removes_copy_artifacts() -> None:
    copied = f" bot{VALID_TOKEN[:12]}\u200b{VALID_TOKEN[12:]}\n"

    assert (
        BotService._normalize_telegram_token(copied, required=True)
        == VALID_TOKEN
    )


def test_token_normalization_rejects_full_api_url() -> None:
    with pytest.raises(HTTPException) as exc_info:
        BotService._normalize_telegram_token(
            f"https://api.telegram.org/bot{VALID_TOKEN}/getMe",
            required=True,
        )

    assert exc_info.value.status_code == 422
    assert "неверный формат" in str(exc_info.value.detail)


def test_set_webhook_retries_when_get_me_still_accepts_token() -> None:
    service = BotService.__new__(BotService)
    service.telegram_sender = SimpleNamespace(
        set_webhook=AsyncMock(
            side_effect=[RuntimeError("Unauthorized"), {"ok": True, "result": True}]
        ),
        get_me=AsyncMock(return_value={"id": 123456789, "username": "vbpromobot"}),
    )
    service._webhook_url_for_bot = lambda _bot_id: "https://crm.example/api/v1/telegram/webhook/test"

    with patch("app.services.bot_service.asyncio.sleep", new=AsyncMock()) as sleep:
        result, webhook_url = asyncio.run(
            service._set_webhook_for_token(token=VALID_TOKEN, bot_id=uuid4())
        )

    assert result["ok"] is True
    assert webhook_url.endswith("/webhook/test")
    assert service.telegram_sender.set_webhook.await_count == 2
    service.telegram_sender.get_me.assert_awaited_once_with(VALID_TOKEN)
    sleep.assert_awaited_once()


def test_update_keeps_verified_token_when_webhook_setup_needs_retry() -> None:
    bot_id = uuid4()
    project_id = uuid4()
    existing = SimpleNamespace(
        id=bot_id,
        project_id=project_id,
        name="Old name",
        telegram_token="111111111:old_token",
        crm_description=None,
        telegram_description=None,
        telegram_about=None,
    )
    updated = SimpleNamespace(**vars(existing))
    result_model = _bot_out(bot_id=bot_id, project_id=project_id)

    service = BotService.__new__(BotService)
    service.db = SimpleNamespace(commit=AsyncMock())
    service.bot_repo = SimpleNamespace(update_in_project=AsyncMock(return_value=updated))
    service.avatar_service = SimpleNamespace(invalidate=AsyncMock())
    service._get_bot_or_404 = AsyncMock(return_value=existing)
    service._fetch_telegram_bot_info = AsyncMock(
        return_value={
            "id": 123456789,
            "first_name": "VB Promo",
            "username": "vbpromobot",
        }
    )
    service._configure_saved_token = AsyncMock(
        return_value=("webhook needs retry", False)
    )
    service._delete_webhook_safely = AsyncMock()
    service.get_bot = AsyncMock(return_value=result_model)

    result = asyncio.run(
        service.update_bot(
            bot_id=bot_id,
            project_id=project_id,
            data=BotUpdate(telegram_token=VALID_TOKEN),
        )
    )

    assert result.telegram_setup_warning == "webhook needs retry"
    service.db.commit.assert_awaited_once()
    service.bot_repo.update_in_project.assert_awaited_once()
    saved_values = service.bot_repo.update_in_project.await_args.kwargs
    assert saved_values["telegram_token"] == VALID_TOKEN
    assert saved_values["bot_username"] == "vbpromobot"
    service._delete_webhook_safely.assert_not_awaited()
