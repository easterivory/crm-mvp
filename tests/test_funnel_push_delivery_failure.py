import asyncio
import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.chat import Chat
from app.models.funnel import ChatFunnelState
from app.repositories.funnel_repository import FunnelRepository
from app.services.telegram_sender import TelegramDeliveryError
from app.workers import funnel_push_worker as worker


def delivery_error(description="Forbidden: bot can't initiate conversation with a user", code=403):
    return TelegramDeliveryError(method="sendMessage", description=description,
                                 status_code=code, error_code=code, transient=code >= 500)


@pytest.mark.parametrize("description,code,expected", [
    ("Forbidden: bot can't initiate conversation with a user", 403, True),
    ("Forbidden: bot was blocked by the user", 403, False),
    ("Unauthorized", 401, False),
    ("Bad Request: message is too long", 400, False),
    ("upstream unavailable", 503, False),
])
def test_only_cannot_initiate_errors_trigger_suspension(description, code, expected):
    assert delivery_error(description, code).cannot_initiate is expected


def setup_worker(monkeypatch, *, error=None, suspended=False, moved=False):
    sessions = [AsyncMock(), AsyncMock()]
    for session in sessions:
        session.__aenter__.return_value = session
    state = SimpleNamespace(funnel_id=uuid4(), funnel_version_id=uuid4(), current_step_id=uuid4(),
                            entered_step_at=datetime.now(timezone.utc), runtime_json={"existing": True})
    current = SimpleNamespace(**vars(state))
    if moved:
        current.current_step_id = uuid4()
    repos = [SimpleNamespace(lock_chat_for_runtime=AsyncMock(return_value=True),
                             is_push_delivery_suspended=AsyncMock(return_value=suspended),
                             get_chat_funnel_state=AsyncMock(return_value=item),
                             update_chat_funnel_runtime=AsyncMock()) for item in (state, current)]
    monkeypatch.setattr(worker, "get_db_session", Mock(side_effect=sessions))
    monkeypatch.setattr(worker, "FunnelRepository", Mock(side_effect=repos))
    runtime = SimpleNamespace(mark_push_sent=AsyncMock(return_value=True, side_effect=error))
    factory = Mock(return_value=runtime)
    monkeypatch.setattr(worker, "FunnelRuntimeService", factory)
    alert = AsyncMock()
    monkeypatch.setattr(worker, "send_operational_alert", alert)
    return sessions, repos, runtime, factory, alert


def test_terminal_failure_rolls_back_and_persists_in_fresh_session(monkeypatch):
    sessions, repos, runtime, factory, alert = setup_worker(monkeypatch, error=delivery_error())
    assert not asyncio.run(worker._process_candidate(uuid4(), uuid4()))
    sessions[0].rollback.assert_awaited_once()
    sessions[0].commit.assert_not_awaited()
    sessions[1].commit.assert_awaited_once()
    saved = repos[1].update_chat_funnel_runtime.await_args.kwargs["runtime_json"]
    assert saved["existing"] is True
    assert saved["push_delivery_suspended"]["reason"] == "telegram_cannot_initiate_conversation"
    assert "push_rules_sent" not in saved
    assert factory.call_args.kwargs["raise_on_telegram_delivery_error"] is True
    alert.assert_awaited_once()


def test_suspended_chat_does_not_send_another_rule_or_alert(monkeypatch):
    sessions, repos, runtime, factory, alert = setup_worker(monkeypatch, suspended=True)
    assert not asyncio.run(worker._process_candidate(uuid4(), uuid4()))
    factory.assert_not_called()
    alert.assert_not_awaited()


def test_new_step_is_not_suspended_by_an_old_failure(monkeypatch):
    sessions, repos, runtime, factory, alert = setup_worker(monkeypatch, error=delivery_error(), moved=True)
    assert not asyncio.run(worker._process_candidate(uuid4(), uuid4()))
    repos[1].update_chat_funnel_runtime.assert_not_awaited()
    alert.assert_not_awaited()


def test_transient_failure_does_not_suspend_chat(monkeypatch):
    sessions, repos, runtime, factory, alert = setup_worker(monkeypatch, error=delivery_error("timeout", 503))
    with pytest.raises(TelegramDeliveryError):
        asyncio.run(worker._process_candidate(uuid4(), uuid4()))
    repos[1].update_chat_funnel_runtime.assert_not_awaited()
    sessions[0].rollback.assert_awaited_once()


def test_success_keeps_existing_commit_path(monkeypatch):
    sessions, repos, runtime, factory, alert = setup_worker(monkeypatch)
    assert asyncio.run(worker._process_candidate(uuid4(), uuid4()))
    sessions[0].commit.assert_awaited_once()
    sessions[0].rollback.assert_not_awaited()
    alert.assert_not_awaited()


def test_candidate_filter_checks_incoming_and_new_step_with_null_safe_timestamp():
    query = select(ChatFunnelState.chat_id).join(Chat, Chat.id == ChatFunnelState.chat_id).where(
        FunnelRepository._push_delivery_allowed())
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "push_delivery_suspended" in sql
    assert "last_user_message_at" in sql and "entered_step_at" in sql
    assert "coalesce" in sql and "IS NULL" in sql


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL URL not provided")
def test_postgres_suspension_and_recovery_without_changing_other_chats():
    async def run():
        engine = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"])
        try:
            async with engine.begin() as conn:
                await conn.execute(text("CREATE TEMP TABLE chats (id uuid, last_user_message_at timestamptz) ON COMMIT DROP"))
                await conn.execute(text("CREATE TEMP TABLE chat_funnel_states (chat_id uuid, runtime_json jsonb, entered_step_at timestamptz) ON COMMIT DROP"))
                chat_id = uuid4()
                await conn.execute(text("INSERT INTO chats VALUES (:id, NULL)"), {"id": chat_id})
                await conn.execute(text("INSERT INTO chat_funnel_states VALUES (:id, '{}', to_timestamp(100))"), {"id": chat_id})
                async with AsyncSession(bind=conn) as session:
                    repo = FunnelRepository(session)
                    assert not await repo.is_push_delivery_suspended(chat_id)
                    await conn.execute(text("UPDATE chat_funnel_states SET runtime_json = CAST(:runtime AS jsonb)"),
                                       {"runtime": json.dumps({"push_delivery_suspended": {"at_epoch": 200}})})
                    assert await repo.is_push_delivery_suspended(chat_id)
                    await conn.execute(text("UPDATE chats SET last_user_message_at = to_timestamp(199)"))
                    assert await repo.is_push_delivery_suspended(chat_id)
                    await conn.execute(text("UPDATE chats SET last_user_message_at = to_timestamp(201)"))
                    assert not await repo.is_push_delivery_suspended(chat_id)
                    await conn.execute(text("UPDATE chats SET last_user_message_at = NULL"))
                    await conn.execute(text("UPDATE chat_funnel_states SET entered_step_at = to_timestamp(201)"))
                    assert not await repo.is_push_delivery_suspended(chat_id)
        finally:
            await engine.dispose()
    asyncio.run(run())
