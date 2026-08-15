import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from sqlalchemy.dialects import postgresql

from app.repositories.chat_repository import ChatRepository
from app.repositories.message_repository import MessageRepository
from app.services.chat_service import ChatService
from app.services.chat_user_block_service import ChatUserBlockService
from app.services.telegram_sender import TelegramSenderService


def test_chat_date_range_uses_browser_local_midnight() -> None:
    start, end = ChatService.date_range_to_datetimes(
        date(2026, 7, 4),
        date(2026, 7, 7),
        timezone_offset_minutes=-180,
    )

    assert start == datetime(2026, 7, 3, 21, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 7, 21, tzinfo=timezone.utc)


def test_chat_date_filter_matches_visible_latest_activity() -> None:
    repo = ChatRepository(AsyncMock())
    stmt = repo._apply_filters(
        repo._base_select(uuid4()),
        only_unread=False,
        only_unanswered=False,
        only_red=False,
        only_hot_lead=False,
        sla_threshold_minutes=30,
        manager_id=None,
        assigned_user_id=None,
        unassigned=False,
        search_query=None,
        tracking_link_id=None,
        date_from=datetime(2026, 7, 4, tzinfo=timezone.utc),
        date_to=datetime(2026, 7, 8, tzinfo=timezone.utc),
        tag_ids=(),
        tag_mode="any",
        lead_statuses=(),
        funnel_state=None,
    )
    sql = str(stmt.compile(dialect=postgresql.dialect()))

    assert "coalesce(chats.last_message_at, chats.current_cycle_started_at, chats.created_at)" in sql


def test_user_blocked_chat_is_not_marked_unanswered_or_sla() -> None:
    now = datetime.now(timezone.utc)
    chat = SimpleNamespace(
        is_blocked=False,
        is_blocked_by_user=True,
        last_message_at=now,
        last_read_at=None,
        last_user_message_at=now,
        last_manager_reply_at=None,
    )

    flags = ChatService._compute_flags(chat, sla_threshold_minutes=0)

    assert flags["unanswered"] is False
    assert flags["is_red"] is False


def test_telegram_user_block_pauses_active_funnel() -> None:
    chat = SimpleNamespace(id=uuid4())
    state = SimpleNamespace(completed_at=None, is_paused=False)
    service = ChatUserBlockService.__new__(ChatUserBlockService)
    service.chat_repo = SimpleNamespace(
        set_blocked_by_user=AsyncMock(return_value=chat),
    )
    service.funnel_repo = SimpleNamespace(
        get_chat_funnel_state=AsyncMock(return_value=state),
        cancel_scheduled_jobs_for_chat=AsyncMock(),
        set_chat_funnel_paused=AsyncMock(),
    )

    async def run():
        return await service.set_blocked_by_user(
            project_id=uuid4(),
            bot_id=uuid4(),
            external_chat_id="12345",
            is_blocked_by_user=True,
        )

    result = asyncio.run(run())

    assert result is chat
    service.funnel_repo.cancel_scheduled_jobs_for_chat.assert_awaited_once_with(
        chat_id=chat.id,
    )
    service.funnel_repo.set_chat_funnel_paused.assert_awaited_once()


def test_telegram_forbidden_response_persists_user_block() -> None:
    project_id = uuid4()
    bot_id = uuid4()
    sender = TelegramSenderService.__new__(TelegramSenderService)
    sender._get_token = AsyncMock(return_value="test-token")
    sender._record_bot_blocked = AsyncMock()

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, json):
            request = httpx.Request("POST", url, json=json)
            return httpx.Response(
                403,
                request=request,
                json={
                    "ok": False,
                    "error_code": 403,
                    "description": "Forbidden: bot was blocked by the user",
                },
            )

    async def run():
        with patch("app.services.telegram_sender.httpx.AsyncClient", return_value=FakeClient()):
            return await sender.send_message(
                project_id=project_id,
                bot_id=bot_id,
                external_chat_id="12345",
                text="Проверка",
            )

    result = asyncio.run(run())

    assert result is None
    sender._record_bot_blocked.assert_awaited_once_with(
        project_id=project_id,
        bot_id=bot_id,
        external_chat_id="12345",
    )


def test_expired_assignment_does_not_reopen_read_chat() -> None:
    chat_id = uuid4()
    lead_id = uuid4()
    manager_id = uuid4()

    class RowsResult:
        @staticmethod
        def all():
            return [(chat_id, lead_id, manager_id)]

    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[RowsResult(), SimpleNamespace(rowcount=1), SimpleNamespace(rowcount=1)]
        )
    )
    repository = ChatRepository(db)

    result = asyncio.run(
        repository.release_expired_assignments(
            project_id=uuid4(),
            expires_before=datetime.now(timezone.utc),
        )
    )

    assert result == [(chat_id, lead_id, manager_id)]
    chat_update = db.execute.await_args_list[2].args[0]
    sql = str(chat_update.compile(dialect=postgresql.dialect()))
    assert "assignment_expires_at" in sql
    assert "is_read=" not in sql


def test_message_history_cursor_uses_oldest_loaded_message() -> None:
    chat_id = uuid4()
    anchor_id = uuid4()
    anchor_created_at = datetime.now(timezone.utc)

    class AnchorResult:
        @staticmethod
        def one_or_none():
            return SimpleNamespace(created_at=anchor_created_at, id=anchor_id)

    class MessagesResult:
        @staticmethod
        def scalars():
            return SimpleNamespace(all=lambda: [])

    db = SimpleNamespace(execute=AsyncMock(side_effect=[AnchorResult(), MessagesResult()]))
    repository = MessageRepository(db)

    result = asyncio.run(
        repository.list_by_chat(
            chat_id,
            limit=100,
            offset=900,
            before_message_id=anchor_id,
        )
    )

    assert result == []
    page_query = db.execute.await_args_list[1].args[0]
    sql = str(page_query.compile(dialect=postgresql.dialect()))
    assert "(messages.created_at, messages.id) <" in sql
    assert " OFFSET " not in sql
