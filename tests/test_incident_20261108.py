"""No live Telegram/partner/server calls. Real PostgreSQL continuation fences."""
import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.delivery_attempt import note_external_delivery
from app.models import Chat, Lead, Message
from app.models.funnel import Funnel, FunnelVersion, FunnelStep, FunnelEdge, ChatFunnelState, FunnelScheduledJob
from app.models.telegram_delivery import RuntimeDispatch, TelegramInbox
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.runtime_dispatch_service import (RuntimeDispatchAlreadyHandled, RuntimeDispatchDeliveryHandled,
    RuntimeDispatchNeedsReview, protect_dispatch_replay, save_runtime_dispatch)
from app.services.telegram_sender import TelegramDeliveryError, TelegramSenderService
from test_gambling_offers import fixture
from test_telegram_delivery_resilience import payload

PG = pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")


async def graph(sessions, pid, bid, chat_id, *, prompt=False):
    async with sessions() as db:
        funnel = Funnel(project_id=pid, bot_id=bid, name="QA delivery"); db.add(funnel); await db.flush()
        version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="published"); db.add(version); await db.flush()
        action = FunnelStep(funnel_version_id=version.id, key="action", title="Action", step_type="action", block_type="crm_action")
        message = FunnelStep(funnel_version_id=version.id, key="message", title="Message", step_type="input" if prompt else "message",
            block_type="generic_input" if prompt else "generic_message", config_json={"prompt": "question", "answer_type": "text"} if prompt else
            {"messages": [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}]})
        finish = FunnelStep(funnel_version_id=version.id, key="finish", title="Finish", step_type="finish", block_type="finish")
        db.add_all([action, message, finish]); await db.flush()
        db.add_all([FunnelEdge(funnel_version_id=version.id, from_step_id=action.id, to_step_id=message.id),
            FunnelEdge(funnel_version_id=version.id, from_step_id=message.id, to_step_id=finish.id)])
        state = ChatFunnelState(chat_id=chat_id, funnel_id=funnel.id, funnel_version_id=version.id, current_step_id=action.id,
            entered_step_at=datetime.now(timezone.utc), waiting_for_answer=False)
        db.add(state)
        incoming = Message(chat_id=chat_id, sender_type="user", message_type="text", body="QA answer"); db.add(incoming); await db.flush()
        await save_runtime_dispatch(db, key=f"input:{incoming.id}", kind="input", payload={"chat_id": str(chat_id), "message_id": str(incoming.id)})
        await db.commit()
        return incoming.id, action.id, message.id, state.id


@PG
@pytest.mark.parametrize("prompt", [False, True])
def test_connect_failure_continues_exact_send_without_replaying_action_or_accepted_messages(monkeypatch, prompt):
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, _):
            monkeypatch.setattr("app.services.runtime_dispatch_service.get_db_session", sessions)
            async with sessions() as db: chat_id = (await db.get(Lead, leads[0])).chat_id
            mid, aid, sid, state_id = await graph(sessions, pid, bid, chat_id, prompt=prompt)
            sent, actions = [], []
            async def action(self, **kwargs): actions.append(kwargs["step"].id); return True
            async def send(self, **kwargs):
                await self.db.commit(); note_external_delivery()
                value = kwargs["text"]; sent.append(value)
                if (value == "second" or prompt) and sent.count(value) == 1:
                    raise TelegramDeliveryError(method="sendMessage", description="Network error (ConnectError)", transient=True, definitely_not_sent=True)
                return {"message_id": len(sent), "text": value}
            monkeypatch.setattr(FunnelRuntimeService, "_execute_crm_actions", action)
            monkeypatch.setattr(TelegramSenderService, "send_message", send)
            async with sessions() as db:
                with pytest.raises(RuntimeDispatchDeliveryHandled) as handled:
                    async with protect_dispatch_replay(db, "input", mid):
                        runtime = FunnelRuntimeService(db, release_transaction_before_external_io=True, raise_on_telegram_delivery_error=True)
                        await runtime._execute_from_step(chat_id=chat_id, step=await runtime.repo.get_step(aid))
                assert handled.value.outcome == "delivery_retry_scheduled"
            async with sessions() as db:
                dispatch = await db.scalar(select(RuntimeDispatch).where(RuntimeDispatch.kind == "input"))
                assert dispatch.status == "done" and dispatch.diagnostics_json["safe_to_replay"] is False
                job = await db.get(FunnelScheduledJob, handled.value.job_id)
                assert job.step_id == sid and job.funnel_state_id == state_id
                assert job.job_type == ("input_prompt" if prompt else "message_sequence")
                assert job.payload_json.get("message_index") == (None if prompt else 1)
                runtime = FunnelRuntimeService(db, release_transaction_before_external_io=True, raise_on_telegram_delivery_error=True)
                await runtime.process_scheduled_job(job); await db.commit()
                assert actions == [aid]
                assert sent == (["question", "question"] if prompt else ["first", "second", "second"])
                outgoing = (await db.scalars(select(Message).where(Message.chat_id == chat_id, Message.sender_type == "bot"))).all()
                assert sorted(m.body for m in outgoing) == (["question"] if prompt else ["first", "second"])
                with pytest.raises(RuntimeDispatchAlreadyHandled):
                    async with protect_dispatch_replay(db, "input", mid): pytest.fail("Original input replayed")
    asyncio.run(run())


@PG
@pytest.mark.parametrize("outcome", ["read_timeout", "write_timeout", "http_500", "paused", "new_visit", "reset", "mtproto", "archived"])
def test_unknown_delivery_or_changed_visit_never_authorises_a_retry(monkeypatch, outcome):
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, _):
            monkeypatch.setattr("app.services.runtime_dispatch_service.get_db_session", sessions)
            async with sessions() as db: chat_id = (await db.get(Lead, leads[0])).chat_id
            mid, aid, sid, state_id = await graph(sessions, pid, bid, chat_id)
            if outcome in {"mtproto", "archived"}:
                from app.models import Bot, Project
                async with sessions() as db:
                    if outcome == "mtproto": (await db.get(Bot, bid)).transport_type = "user_mtproto"
                    else: (await db.get(Project, pid)).status = "archived"
                    await db.commit()
            async def send(self, **kwargs):
                await self.db.commit(); note_external_delivery()
                if outcome in {"paused", "new_visit", "reset"}:
                    async with sessions() as other:
                        state = await other.get(ChatFunnelState, state_id)
                        if outcome == "paused": state.is_paused = True
                        elif outcome == "new_visit": state.entered_step_at += timedelta(seconds=1)
                        else: (await other.get(Chat, chat_id)).reset_at = datetime.now(timezone.utc)
                        await other.commit()
                raise TelegramDeliveryError(method="sendMessage", description=outcome, transient=True,
                    status_code=500 if outcome == "http_500" else None, definitely_not_sent=outcome in {"paused", "new_visit", "reset", "mtproto", "archived"})
            monkeypatch.setattr(TelegramSenderService, "send_message", send)
            monkeypatch.setattr(FunnelRuntimeService, "_execute_crm_actions", AsyncMock(return_value=True))
            async with sessions() as db:
                with pytest.raises(RuntimeDispatchNeedsReview):
                    async with protect_dispatch_replay(db, "input", mid):
                        runtime = FunnelRuntimeService(db, release_transaction_before_external_io=True, raise_on_telegram_delivery_error=True)
                        await runtime._execute_from_step(chat_id=chat_id, step=await runtime.repo.get_step(aid))
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(FunnelScheduledJob)) == 0
                dispatch = await db.scalar(select(RuntimeDispatch))
                assert dispatch.status == "review" and dispatch.diagnostics_json["safe_to_replay"] is False
    asyncio.run(run())


@PG
@pytest.mark.parametrize("unavailable", [False, True])
def test_block_is_terminal_not_a_replayable_runtime_failure(monkeypatch, unavailable):
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, _):
            monkeypatch.setattr("app.services.runtime_dispatch_service.get_db_session", sessions)
            async with sessions() as db: chat_id = (await db.get(Lead, leads[0])).chat_id
            mid, *_ = await graph(sessions, pid, bid, chat_id)
            async with sessions() as db:
                with pytest.raises(RuntimeDispatchDeliveryHandled) as error:
                    async with protect_dispatch_replay(db, "input", mid):
                        note_external_delivery()
                        raise TelegramDeliveryError(method="sendMessage", description="Forbidden: user is deactivated" if unavailable else "Blocked",
                            error_code=403, blocked=not unavailable)
                assert error.value.outcome == ("delivery_recipient_unavailable" if unavailable else "delivery_blocked")
            async with sessions() as db:
                assert (await db.get(Chat, chat_id)).is_blocked_by_user is (not unavailable)
                assert (await db.scalar(select(ChatFunnelState))).is_paused
                assert (await db.scalar(select(RuntimeDispatch))).status == "done"
                assert await db.scalar(select(func.count()).select_from(FunnelScheduledJob)) == 0
    asyncio.run(run())


@PG
def test_block_persistence_does_not_upgrade_chat_lock_against_message_foreign_key(monkeypatch):
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, _):
            monkeypatch.setattr("app.services.runtime_dispatch_service.get_db_session", sessions)
            async with sessions() as db: chat_id = (await db.get(Lead, leads[0])).chat_id
            mid, *_ = await graph(sessions, pid, bid, chat_id)
            async with sessions() as foreign:
                foreign.add(Message(chat_id=chat_id, sender_type="user", message_type="text", body="QA concurrent insert"))
                await foreign.flush()
                async with sessions() as db:
                    async with asyncio.timeout(1):
                        with pytest.raises(RuntimeDispatchDeliveryHandled):
                            async with protect_dispatch_replay(db, "input", mid):
                                note_external_delivery()
                                raise TelegramDeliveryError(method="sendMessage", description="Blocked", error_code=403, blocked=True)
                await foreign.rollback()
    asyncio.run(run())


@PG
def test_newer_unblock_event_is_not_overwritten_by_old_delivery_failure(monkeypatch):
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, _):
            monkeypatch.setattr("app.services.runtime_dispatch_service.get_db_session", sessions)
            async with sessions() as db: chat_id = (await db.get(Lead, leads[0])).chat_id
            mid, *_ = await graph(sessions, pid, bid, chat_id)
            error = TelegramDeliveryError(method="sendMessage", description="Blocked", error_code=403, blocked=True)
            async with sessions() as db:
                chat = await db.get(Chat, chat_id)
                chat.is_blocked_by_user = False; chat.telegram_block_state_at = error.observed_at + timedelta(seconds=1)
                await db.commit()
                with pytest.raises(RuntimeDispatchDeliveryHandled) as handled:
                    async with protect_dispatch_replay(db, "input", mid): note_external_delivery(); raise error
                assert handled.value.outcome == "delivery_blocked_superseded"
            async with sessions() as db:
                assert (await db.get(Chat, chat_id)).is_blocked_by_user is False
                assert (await db.scalar(select(ChatFunnelState))).is_paused is False
    asyncio.run(run())


@PG
def test_existing_newer_block_remains_paused_without_rewriting_its_timestamp(monkeypatch):
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, _):
            monkeypatch.setattr("app.services.runtime_dispatch_service.get_db_session", sessions)
            async with sessions() as db: chat_id = (await db.get(Lead, leads[0])).chat_id
            mid, *_ = await graph(sessions, pid, bid, chat_id)
            error = TelegramDeliveryError(method="sendMessage", description="Blocked", error_code=403, blocked=True)
            latest = error.observed_at + timedelta(seconds=2)
            async with sessions() as db:
                chat = await db.get(Chat, chat_id)
                chat.is_blocked_by_user = True; chat.telegram_block_state_at = latest
                chat.last_user_message_at = error.observed_at + timedelta(seconds=1)
                await db.commit()
                with pytest.raises(RuntimeDispatchDeliveryHandled) as handled:
                    async with protect_dispatch_replay(db, "input", mid): note_external_delivery(); raise error
                assert handled.value.outcome == "delivery_blocked"
            async with sessions() as db:
                assert (await db.get(Chat, chat_id)).telegram_block_state_at == latest
                assert (await db.scalar(select(ChatFunnelState))).is_paused
    asyncio.run(run())


@PG
def test_queued_continuation_cannot_send_on_a_later_visit_of_the_same_step(monkeypatch):
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, _):
            async with sessions() as db: chat_id = (await db.get(Lead, leads[0])).chat_id
            _, _, sid, state_id = await graph(sessions, pid, bid, chat_id)
            async with sessions() as db:
                state = await db.get(ChatFunnelState, state_id); state.current_step_id = sid
                visit = state.entered_step_at.isoformat()
                job = FunnelScheduledJob(chat_id=chat_id, funnel_state_id=state.id, funnel_id=state.funnel_id,
                    funnel_version_id=state.funnel_version_id, step_id=sid, job_type="message_sequence",
                    run_at=datetime.now(timezone.utc), payload_json={"message_index": 1, "runtime_delivery_visit": visit})
                db.add(job); state.entered_step_at += timedelta(seconds=1); await db.commit()
                send = AsyncMock(); monkeypatch.setattr(TelegramSenderService, "send_message", send)
                await FunnelRuntimeService(db).process_scheduled_job(job)
                send.assert_not_awaited()
    asyncio.run(run())


@PG
def test_intake_uses_reserved_connections_while_general_pool_is_exhausted(monkeypatch):
    from app.api.v1.routers import telegram as route
    from app.core import telegram_intake
    async def run():
        async with fixture() as (sessions, pid, actor, _, bid, _):
            async with sessions() as db: schema = await db.scalar(text("select current_schema()"))
            def engine(url, **kwargs):
                kwargs["connect_args"]["server_settings"]["search_path"] = schema
                return create_async_engine(url, **kwargs)
            monkeypatch.setattr(telegram_intake, "create_async_engine", engine)
            await telegram_intake.close_reserved_db_pools()
            general = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"], pool_size=1, max_overflow=0, pool_timeout=0.05)
            monkeypatch.setattr("app.core.database.get_db_session", async_sessionmaker(general))
            monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "qa")
            app = FastAPI(); app.include_router(route.router)
            try:
                async with general.connect():
                    async with telegram_intake.get_count_db_session() as counting:
                        assert await counting.scalar(text("SHOW default_transaction_read_only")) == "on"
                        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://qa") as client:
                            start = time.monotonic()
                            responses = await asyncio.gather(*(client.post(f"/telegram/webhook/{bid}", json=payload(i),
                                headers={"X-Telegram-Bot-Api-Secret-Token": "qa"}) for i in range(1, 21)))
                            assert all(response.status_code == 200 for response in responses)
                            assert time.monotonic() - start < 2
                async with sessions() as db: assert await db.scalar(select(func.count()).select_from(TelegramInbox)) == 20
                pool = telegram_intake._sessions("intake").kw["bind"].pool
                assert pool.size() == 2 and pool._max_overflow == 0
            finally:
                await telegram_intake.close_reserved_db_pools(); await general.dispose()
    asyncio.run(run())


class Cache:
    def __init__(self): self.values = {}; self.deadlines = {}
    async def get(self, key):
        if self.deadlines.get(key, float("inf")) <= time.monotonic(): self.values.pop(key, None)
        return self.values.get(key)
    async def set(self, key, value, *, ex, nx=False):
        if nx and await self.get(key) is not None: return False
        self.values[key] = value; self.deadlines[key] = time.monotonic() + ex
        return True
    async def eval(self, script, number, key, ticket):
        if await self.get(key) == ticket: self.values.pop(key, None)


@PG
def test_twenty_managers_share_one_count_scan_without_mixing_personal_counts(monkeypatch):
    from app.models import User
    from app.repositories.chat_repository import ChatRepository
    from app.services.chat_service import ChatService
    from app.services import chat_workspace_counts_service as counts
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, _):
            cache = Cache()
            async def redis(): return cache
            monkeypatch.setattr(counts, "get_redis", redis)
            monkeypatch.setattr(counts, "get_count_db_session", sessions)
            async with sessions() as db:
                root = await db.get(User, actor.id)
                second = User(role_id=root.role_id, email="qa-manager@example.org", name="QA second", password_hash="unused")
                db.add(second); await db.flush(); second_id = second.id
                from app.models import Project
                project = await db.get(Project, pid); project.hide_assigned_chats_from_all = True
                for i, lid in enumerate(leads): (await db.get(Lead, lid)).manager_id = actor.id if i < 2 else second_id
                db.add(Chat(project_id=pid, bot_id=bid, external_chat_id="no-lead", external_user_id="no-lead"))
                await db.commit()
            queries = []
            original = ChatRepository.shared_workspace_counts
            async def shared(repo, **kwargs):
                queries.append(kwargs); await asyncio.sleep(0.15)
                return await original(repo, **kwargs)
            monkeypatch.setattr(ChatRepository, "shared_workspace_counts", shared)
            async def request(index, refresh=False):
                async with sessions() as db:
                    uid = actor.id if index % 2 == 0 else second_id
                    data = await ChatService(db).get_workspace_counts(project_id=pid, actor=SimpleNamespace(id=uid), bot_id=bid, refresh=refresh)
                    assert data.mine == (2 if uid == actor.id else 1)
                    assert data.all == data.mine + 1
                    assert "managers" not in data.model_dump()
                    return data
            data = await asyncio.gather(*(request(i) for i in range(20)))
            assert len(queries) == 1 and len(data) == 20
            async with sessions() as db:
                repo = ChatRepository(db)
                for uid in [actor.id, second_id]:
                    original_counts = await repo.workspace_counts(project_id=pid, viewer_id=uid, hide_assigned_from_all=True,
                        project_format="gambling", priority_rules={})
                    index = 0 if uid == actor.id else 1
                    assert data[index].model_dump(include=set(original_counts)) == original_counts
            cache.deadlines = {key: 0 for key in cache.deadlines}
            await request(0, refresh=True); assert len(queries) == 2
    asyncio.run(run())


@PG
def test_shared_priority_counts_equal_existing_filter_semantics(monkeypatch):
    from app.models import Tag
    from app.models.lead import LeadTag
    from app.repositories.chat_repository import ChatRepository
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, _):
            async with sessions() as db:
                tag = Tag(project_id=pid, name="QA HOT"); db.add(tag); await db.flush()
                db.add(LeadTag(lead_id=leads[0], tag_id=tag.id))
                for lid in leads:
                    chat = await db.get(Chat, (await db.get(Lead, lid)).chat_id)
                    chat.last_client_message_at = datetime.now(timezone.utc); chat.is_read = False
                await db.commit()
                rules = {"enabled": True, "tag_ids": [str(tag.id)]}
                repo = ChatRepository(db)
                arguments = dict(project_id=pid, priority_rules=rules, project_format="gambling")
                legacy = await repo.workspace_counts(viewer_id=actor.id, hide_assigned_from_all=False, **arguments)
                shared = await repo.shared_workspace_counts(**arguments)
                assert shared["totals"] == {k: v for k, v in legacy.items() if k != "mine"}
                assert legacy["priority"] == 1
                expected_priority = await db.scalar(select(func.count()).select_from(Chat).where(Chat.project_id == pid,
                    ChatRepository.priority_expr(rules)))
                assert expected_priority == shared["totals"]["priority"]
    asyncio.run(run())


@PG
def test_interrupted_new_continuation_is_not_replayed_after_worker_restart(monkeypatch):
    from app.repositories.funnel_repository import FunnelRepository
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, _):
            async with sessions() as db: chat_id = (await db.get(Lead, leads[0])).chat_id
            _, _, sid, state_id = await graph(sessions, pid, bid, chat_id)
            async with sessions() as db:
                state = await db.get(ChatFunnelState, state_id)
                job = FunnelScheduledJob(chat_id=chat_id, funnel_state_id=state.id, funnel_id=state.funnel_id,
                    funnel_version_id=state.funnel_version_id, step_id=sid, job_type="message_sequence", status="running", attempts=1,
                    run_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)-timedelta(hours=1),
                    payload_json={"message_index": 1, "runtime_delivery_visit": state.entered_step_at.isoformat()})
                db.add(job); await db.commit()
                requeued, failed = await FunnelRepository(db).recover_stale_running_jobs(
                    stale_before=datetime.now(timezone.utc)-timedelta(minutes=5), max_attempts=3)
                await db.commit(); await db.refresh(job)
                assert (requeued, failed) == (0, 1) and job.status == "failed" and "uncertain" in job.last_error
    asyncio.run(run())


@PG
@pytest.mark.parametrize("definite", [False, True])
def test_scheduled_delivery_retries_only_known_rejections(monkeypatch, definite):
    from app.workers import funnel_scheduled_worker as worker
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, _):
            monkeypatch.setattr(worker, "get_db_session", sessions)
            async with sessions() as db: chat_id = (await db.get(Lead, leads[0])).chat_id
            _, _, sid, state_id = await graph(sessions, pid, bid, chat_id)
            async with sessions() as db:
                state = await db.get(ChatFunnelState, state_id); state.current_step_id = sid
                job = FunnelScheduledJob(chat_id=chat_id, funnel_state_id=state.id, funnel_id=state.funnel_id,
                    funnel_version_id=state.funnel_version_id, step_id=sid, job_type="message_sequence", status="running", attempts=1,
                    run_at=datetime.now(timezone.utc), payload_json={"message_index": 1})
                db.add(job); await db.commit(); jid = job.id
            error = TelegramDeliveryError(method="sendMessage", description="ConnectError" if definite else "ReadTimeout",
                transient=True, definitely_not_sent=definite)
            result = await worker._resolve_delivery_failure(jid, error, str(error))
            assert result["status"] == ("retry_scheduled" if definite else "failed")
            async with sessions() as db:
                assert (await db.get(FunnelScheduledJob, jid)).status == ("pending" if definite else "failed")
                if not definite: assert result["delivery_uncertain"]
    asyncio.run(run())


@PG
@pytest.mark.skipif(os.getenv("CRM_LARGE_QA") != "1", reason="Explicit 100k synthetic PostgreSQL workload")
def test_counts_on_one_hundred_thousand_synthetic_chats(monkeypatch):
    from sqlalchemy import Integer, String, case, cast, literal, and_
    from app.models import Tag
    from app.models.lead import LeadTag
    from app.repositories.chat_repository import ChatRepository
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, _):
            async with sessions() as db:
                status_id = (await db.get(Lead, leads[0])).status_id
                series = func.generate_series(1, 100000).table_valued("n").render_derived()
                source = select(func.gen_random_uuid(), literal(pid), literal(bid),
                    literal("bench-") + cast(series.c.n, String), literal("bench-") + cast(series.c.n, String),
                    literal(False), func.now(), series.c.n % 7 == 0)
                await db.execute(Chat.__table__.insert().from_select(["id", "project_id", "bot_id", "external_chat_id", "external_user_id",
                    "is_read", "last_client_message_at", "is_favorite"], source))
                source = select(func.gen_random_uuid(), literal(pid), Chat.id, literal(status_id),
                    case((cast(func.substr(Chat.external_chat_id, 7), Integer) % 2 == 0,
                        literal(actor.id, type_=Lead.__table__.c.manager_id.type)), else_=None), literal(0))
                source = source.where(Chat.external_chat_id.like("bench-%"))
                await db.execute(Lead.__table__.insert().from_select(["id", "project_id", "chat_id", "status_id", "manager_id", "score_percent"], source))
                tag = Tag(project_id=pid, name="QA HOT"); db.add(tag); await db.flush()
                source = select(Lead.id, literal(tag.id)).join(Chat, Chat.id == Lead.chat_id).where(Chat.external_chat_id.like("bench-%"),
                    cast(func.substr(Chat.external_chat_id, 7), Integer) % 3 == 0)
                await db.execute(LeadTag.__table__.insert().from_select(["lead_id", "tag_id"], source))
                for table in ["chats", "leads", "lead_tags", "funnel_step_logs", "lead_submissions", "chat_funnel_states"]:
                    await db.execute(text("ANALYZE " + table))
                await db.commit()
                rules = {"enabled": True, "tag_ids": [str(tag.id)]}
                legacy = select(func.count(Chat.id).filter(ChatRepository.priority_expr(rules)).label("priority"),
                    func.count(Chat.id).filter(ChatRepository._workspace_unread_expr(project_format="submission", push_unread_threshold=1, use_confidence_score=True)).label("unread"),
                    func.count(Chat.id).filter(ChatRepository.unanswered_expr()).label("unanswered"),
                    func.count(Chat.id).filter(Lead.manager_id == actor.id).label("mine"), func.count(Chat.id).label("all"),
                    func.count(Chat.id).filter(Chat.is_favorite.is_(True)).label("favorites")).select_from(Chat).outerjoin(Lead,
                    and_(Lead.chat_id == Chat.id, Lead.is_deleted.is_(False))).where(Chat.project_id == pid, Chat.is_deleted.is_(False), Chat.reset_at.is_(None))
                start = time.monotonic(); previous = dict((await db.execute(legacy)).one()._mapping); old_ms = (time.monotonic()-start)*1000
                start = time.monotonic(); shared = await ChatRepository(db).shared_workspace_counts(project_id=pid, priority_rules=rules,
                    project_format="submission", use_confidence_score=True); new_ms = (time.monotonic()-start)*1000
                assert shared["totals"] == {k: v for k, v in previous.items() if k != "mine"}
                assert shared["managers"][str(actor.id)] == previous["mine"]
                assert previous["all"] == 100003 and previous["priority"] == 33333
                assert new_ms < 3000
                print(f"\n100k synthetic chats: legacy per-viewer aggregate {old_ms:.1f}ms; optimized shared aggregate {new_ms:.1f}ms; exact metrics matched")
    asyncio.run(run())
