from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.schemas.bot import BotCreate
from app.services.bot_service import BotService


def test_create_draft_bot_without_token_skips_telegram_calls() -> None:
    project_id = uuid4()
    bot_id = uuid4()
    expected = SimpleNamespace(id=bot_id)
    service = BotService.__new__(BotService)
    service.bot_repo = SimpleNamespace(create=AsyncMock(return_value=expected))
    service._resolve_project_for_create = AsyncMock(
        return_value=SimpleNamespace(id=project_id)
    )
    service._fetch_telegram_bot_info = AsyncMock()
    service._set_webhook_for_token = AsyncMock()
    service.get_bot = AsyncMock(return_value="draft-result")

    result = asyncio.run(
        service.create_bot(
            project_id=project_id,
            data=BotCreate(name="Chatterfy import", telegram_token=None),
        )
    )

    assert result == "draft-result"
    service._fetch_telegram_bot_info.assert_not_awaited()
    service._set_webhook_for_token.assert_not_awaited()
    service.bot_repo.create.assert_awaited_once_with(
        project_id=project_id,
        name="Chatterfy import",
        telegram_token=None,
        crm_description=None,
        telegram_description=None,
        telegram_about=None,
    )


def test_create_bot_requires_name_when_token_is_missing() -> None:
    project_id = uuid4()
    service = BotService.__new__(BotService)
    service.bot_repo = SimpleNamespace(create=AsyncMock())
    service._resolve_project_for_create = AsyncMock(
        return_value=SimpleNamespace(id=project_id)
    )
    service._fetch_telegram_bot_info = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            service.create_bot(
                project_id=project_id,
                data=BotCreate(name=None, telegram_token=None),
            )
        )

    assert exc_info.value.status_code == 422
    service.bot_repo.create.assert_not_awaited()
    service._fetch_telegram_bot_info.assert_not_awaited()
