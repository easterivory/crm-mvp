import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.repositories.chat_repository import ChatRepository
from app.schemas.chat import ChatFilters
from app.schemas.telegram import TelegramChatMemberUpdated
from app.services.chat_service import ChatService
from app.services.telegram_service import TelegramService


@pytest.mark.parametrize("method", ["list", "count"])
def test_exact_id_queries_do_not_scan_messages(method):
    async def run():
        db = AsyncMock()
        db.execute.return_value = MagicMock()
        project_id, bot_id = uuid4(), uuid4()
        await getattr(ChatRepository(db), method)(
            project_id=project_id, bot_id=bot_id,
            search_query="521049813", exact_telegram_id=True,
        )
        stmt = db.execute.call_args.args[0]
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        assert "messages" not in sql
        assert " LIKE " not in sql
        assert "chats.external_user_id =" in sql
        assert "chats.external_chat_id =" in sql
        assert "chats.project_id =" in sql
        assert "chats.bot_id =" in sql
        assert "chats.reset_at IS NULL" in sql
    asyncio.run(run())


@pytest.mark.parametrize("query,exists,exact", [
    ("521049813", True, True),
    ("521049813", False, False),
    ("+998 90 1234567", False, False),
    ("some text", False, False),
])
def test_search_prefers_identity_but_preserves_fallback(query, exists, exact):
    async def run():
        service = ChatService(AsyncMock())
        service.project_repo = AsyncMock()
        service.project_repo.get_active.return_value = SimpleNamespace(
            sla_threshold_minutes=30, project_format="submission",
            push_unread_threshold=1, use_confidence_score=True,
        )
        service.chat_lease = AsyncMock()
        service.chat_repo = AsyncMock()
        service.chat_repo.has_telegram_identity.return_value = exists
        service.chat_repo.list.return_value = []
        service.chat_repo.count.return_value = 0
        service.funnel_repo = AsyncMock()
        await service.get_chat_list(uuid4(), ChatFilters(q=query), limit=50, offset=0)
        for method in (service.chat_repo.list, service.chat_repo.count):
            assert method.call_args.kwargs["exact_telegram_id"] is exact
            assert method.call_args.kwargs["search_query"] == query
        assert service.chat_repo.search_hit_messages_for_chats.await_count == (0 if exact else 1)
    asyncio.run(run())


@pytest.mark.parametrize("status", ["kicked", "member"])
@pytest.mark.parametrize("timestamp", [1793259387, 0, None])
def test_member_event_converts_unix_time_before_database(status, timestamp):
    async def run():
        event = TelegramChatMemberUpdated.model_validate({
            "chat": {"id": 521049813, "type": "private"},
            "date": timestamp,
            "old_chat_member": {"status": "member", "user": {"id": 123, "is_bot": True, "first_name": "Bot"}},
            "new_chat_member": {"status": status, "user": {"id": 123, "is_bot": True, "first_name": "Bot"}},
        })
        service = object.__new__(TelegramService)
        service.db = AsyncMock()
        with patch("app.services.telegram_service.ChatUserBlockService") as cls:
            cls.return_value.set_blocked_by_user = AsyncMock(return_value=None)
            await service._handle_my_chat_member(event, project_id=uuid4(), bot_id=uuid4())
            kwargs = cls.return_value.set_blocked_by_user.call_args.kwargs
            expected = datetime.fromtimestamp(timestamp, timezone.utc) if timestamp is not None else None
            assert kwargs["observed_at"] == expected
            assert kwargs["is_blocked_by_user"] == (status == "kicked")
    asyncio.run(run())
