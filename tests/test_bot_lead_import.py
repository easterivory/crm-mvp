from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.repositories.chat_repository import ChatRepository
from app.schemas.telegram import TelegramMessage
from app.services.bot_lead_import_service import BotLeadImportService
from app.services.telegram_service import TelegramService


def test_import_row_accepts_single_sheet_fields_and_splits_tags() -> None:
    service = BotLeadImportService.__new__(BotLeadImportService)

    row, issues = service._parse_row(
        2,
        [
            "8053174284",
            "Виктор Смирнов",
            "@smmirnovvictor",
            "+7 477 649 98 5",
            "KZ",
            "Registered",
            "VIP, Chatterfy only; Deposit pending",
            "1000 USD",
            "Связаться вечером",
        ],
    )

    assert row is not None
    assert not [issue for issue in issues if issue.level == "error"]
    assert row.telegram_id == "8053174284"
    assert row.username == "smmirnovvictor"
    assert row.tags == ("VIP", "Chatterfy only", "Deposit pending")
    assert row.expected_start_amount == "1000 USD"


def test_import_row_allows_username_only_but_warns() -> None:
    service = BotLeadImportService.__new__(BotLeadImportService)

    row, issues = service._parse_row(
        3,
        ["", "Анна", "https://telegram.me/anna_test", "", "", "", "", "", ""],
    )

    assert row is not None
    assert row.telegram_id is None
    assert row.username == "anna_test"
    assert [issue.level for issue in issues] == ["warning"]


def test_import_row_rejects_missing_telegram_identity() -> None:
    service = BotLeadImportService.__new__(BotLeadImportService)

    row, issues = service._parse_row(
        4,
        ["", "Без связи", "", "", "", "", "", "", ""],
    )

    assert row is None
    assert any(issue.field == "Telegram ID / Username" for issue in issues)


def test_pending_import_claim_is_atomic_and_scoped() -> None:
    result = SimpleNamespace(scalar_one_or_none=lambda: None)
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    repo = ChatRepository(db)

    asyncio.run(
        repo.claim_pending_import_identity(
            project_id=uuid4(),
            bot_id=uuid4(),
            username_key="anna_test",
            external_chat_id="100500",
            external_user_id="100500",
            contact_name="Анна",
        )
    )

    statement = db.execute.await_args_list[0].args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "chats.is_imported IS true" in sql
    assert "chats.import_identity_pending IS true" in sql
    assert "chats.import_username_key" in sql
    assert "external_chat_id" in sql


def test_existing_imported_chat_never_requests_fresh_funnel_start() -> None:
    imported_chat = SimpleNamespace(
        id=uuid4(),
        contact_name="Импортированное имя",
        is_imported=True,
        import_identity_pending=True,
    )
    message = TelegramMessage.model_validate(
        {
            "message_id": 1,
            "chat": {"id": 8053174284},
            "from": {
                "id": 8053174284,
                "first_name": "Telegram",
                "last_name": "Profile",
                "username": "smmirnovvictor",
            },
            "text": "/start",
        }
    )

    service = TelegramService.__new__(TelegramService)
    service.chat_repo = SimpleNamespace(
        get_by_external=AsyncMock(return_value=imported_chat),
        update_by_id=AsyncMock(return_value=imported_chat),
    )

    chat, should_start, reactivated = asyncio.run(
        service._find_or_create_chat(
            message,
            project_id=uuid4(),
            bot_id=uuid4(),
        )
    )

    assert chat is imported_chat
    assert should_start is False
    assert reactivated is False
    service.chat_repo.update_by_id.assert_awaited_once_with(
        imported_chat.id,
        external_user_id="8053174284",
        import_identity_pending=False,
    )


def test_username_only_import_is_claimed_without_starting_funnel() -> None:
    claimed_chat = SimpleNamespace(
        id=uuid4(),
        contact_name="Импортированное имя",
    )
    message = TelegramMessage.model_validate(
        {
            "message_id": 1,
            "chat": {"id": 100500},
            "from": {
                "id": 100500,
                "first_name": "Анна",
                "username": "anna_test",
            },
            "text": "Здравствуйте",
        }
    )

    @asynccontextmanager
    async def nested_transaction():
        yield

    service = TelegramService.__new__(TelegramService)
    service.db = SimpleNamespace(begin_nested=nested_transaction)
    service.chat_repo = SimpleNamespace(
        get_by_external=AsyncMock(return_value=None),
        get_by_external_user=AsyncMock(return_value=None),
        claim_pending_import_identity=AsyncMock(return_value=claimed_chat),
    )

    chat, should_start, reactivated = asyncio.run(
        service._find_or_create_chat(
            message,
            project_id=uuid4(),
            bot_id=uuid4(),
        )
    )

    assert chat is claimed_chat
    assert should_start is False
    assert reactivated is False
