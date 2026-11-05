"""Incident regressions: durable intake, Redis outage and transaction boundaries."""
import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from redis.exceptions import TimeoutError as RedisTimeout
from fastapi import FastAPI
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.exc import TimeoutError as PoolTimeout

from app.api.v1.routers import telegram as route
from app.core.arq_client import close_arq_client, enqueue_runtime_job, get_arq_client
from app.core.arq_queues import JOBS_QUEUE_NAME
from app.core.config import settings
from app.core.delivery_attempt import note_external_delivery
from app.models import Base, Bot, Chat, Message, Project
from app.models.telegram_delivery import RuntimeDispatch, TelegramInbox
from app.repositories.funnel_repository import FunnelRepository
from app.services.runtime_dispatch_service import acknowledge_runtime_dispatch, save_runtime_dispatch
from app.services.telegram_inbox_service import accept_telegram_update, telegram_peer_key
from app.services.telegram_service import TelegramService
from app.workers import telegram_delivery_worker as worker
from app.workers.funnel_scheduled_worker import ScheduledOperationTimeout, _error_text, _operation_timeout


def payload(number=1, user=100):
    return {"update_id": number, "message": {"message_id": number, "date": 1793790000,
        "from": {"id": user, "first_name": "QA"}, "chat": {"id": user, "type": "private"}, "text": "/start"}}


@asynccontextmanager
async def disposable_db(monkeypatch):
    url = os.getenv("CRM_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Disposable PostgreSQL required")
    schema = "delivery_" + uuid4().hex
    root = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with root.begin() as db:
            await db.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as db:
            await db.run_sync(Base.metadata.create_all)
        async with sessions() as db:
            project = Project(name="Delivery QA", slug="delivery-qa")
            db.add(project); await db.flush()
            bot = Bot(project_id=project.id, name="QA")
            db.add(bot); await db.commit()
            bot_id, project_id = bot.id, project.id
        monkeypatch.setattr(worker, "get_db_session", sessions)
        monkeypatch.setattr("app.services.runtime_dispatch_service.get_db_session", sessions)
        monkeypatch.setattr(worker, "send_operational_alert", AsyncMock())
        yield sessions, engine, bot_id, project_id
    finally:
        await engine.dispose()
        async with root.begin() as db:
            await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await root.dispose()


def test_peer_identity_keeps_callbacks_and_input_in_one_stream():
    assert telegram_peer_key(payload()) == "chat:100"
    assert telegram_peer_key({"update_id": 2, "callback_query": {"message": {"chat": {"id": 100}}}}) == "chat:100"


def test_short_typing_indicator_is_not_rounded_down_to_zero(monkeypatch):
    async def run():
        enqueue = AsyncMock(return_value="queued")
        monkeypatch.setattr(worker, "enqueue_funnel_chat_action", enqueue)
        request = {"scheduled_job_id": str(uuid4()), "chat_id": str(uuid4()), "action": "typing",
                   "duration_seconds": 1, "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=0.5)).isoformat()}
        assert await worker._dispatch("action", request)
        assert enqueue.await_args.kwargs["duration_seconds"] == 1
        enqueue.reset_mock()
        request["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        assert await worker._dispatch("action", request)
        enqueue.assert_not_awaited()
    asyncio.run(run())


def test_webhook_acknowledges_only_durable_acceptance(monkeypatch):
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, _):
            monkeypatch.setattr("app.core.database.get_db_session", sessions)
            monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "qa-secret")
            app = FastAPI(); app.include_router(route.router)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://qa") as client:
                url = f"/telegram/webhook/{bot_id}"
                assert (await client.post(url, json=payload())).status_code == 403
                headers = {"X-Telegram-Bot-Api-Secret-Token": "qa-secret"}
                for _ in range(3):
                    assert (await client.post(url, json=payload(), headers=headers)).status_code == 200
                async with sessions() as db:
                    assert await db.scalar(select(func.count()).select_from(TelegramInbox)) == 1
                    assert await db.scalar(select(func.count()).select_from(Message)) == 0
                assert (await client.post(url, content="{", headers=headers)).status_code == 400
                monkeypatch.setattr(route, "accept_telegram_update", AsyncMock(side_effect=PoolTimeout("exhausted")))
                assert (await client.post(url, json=payload(2), headers=headers)).status_code == 503
                async with sessions() as db:
                    assert await db.scalar(select(func.count()).select_from(TelegramInbox)) == 1
    asyncio.run(run())


def test_intake_deduplicates_concurrent_requests_and_preserves_peer_order(monkeypatch):
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, _):
            async def accept(number, user=100):
                async with sessions() as db:
                    await accept_telegram_update(db, bot_id=bot_id, payload=payload(number, user))
                    await db.commit()
            await asyncio.gather(*(accept(1) for _ in range(12)))
            await accept(2); await accept(3, 200)
            a, b = await asyncio.gather(worker._claim_inbox(), worker._claim_inbox())
            assert a and b and {a[2]["update_id"], b[2]["update_id"]} == {1, 3}
            assert await worker._claim_inbox() is None
            async with sessions() as db:
                await db.execute(update(TelegramInbox).where(TelegramInbox.update_id == 1).values(status="done"))
                await db.commit()
            assert (await worker._claim_inbox())[2]["update_id"] == 2
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["none", "db", "savepoint", "after_commit", "after_delivery"])
def test_intake_retries_only_before_effects_and_does_not_replay_completed_updates(monkeypatch, failure):
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            async with sessions() as db:
                await accept_telegram_update(db, bot_id=bot_id, payload=payload())
                await db.commit()
            class Handler:
                parse_update = staticmethod(TelegramService.parse_update)
                def __init__(self, db, **kwargs): self.db = db
                async def handle_webhook_update(self, **kwargs):
                    await self.db.execute(update(Project).where(Project.id == project_id).values(name="Handled"))
                    if failure == "savepoint":
                        async with self.db.begin_nested():
                            await self.db.execute(select(Project.id))
                    if failure == "after_commit": await self.db.commit()
                    if failure == "after_delivery": note_external_delivery()
                    if failure != "none": raise PoolTimeout("synthetic DB outage")
                dispatch_post_commit_actions = AsyncMock()
            monkeypatch.setattr(worker, "TelegramService", Handler)
            assert await worker.process_next_inbox()
            async with sessions() as db:
                row = await db.scalar(select(TelegramInbox))
                assert row.status == {"none": "done", "db": "pending", "savepoint": "pending", "after_commit": "review", "after_delivery": "review"}[failure]
                assert (await db.get(Project, project_id)).name == ("Handled" if failure in {"none", "after_commit"} else "Delivery QA")
            assert not await worker.process_next_inbox()
    asyncio.run(run())


def test_dispatch_is_atomic_with_business_transaction_and_survives_redis_outage(monkeypatch):
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            key = "input:" + str(uuid4())
            async with sessions() as db:
                await save_runtime_dispatch(db, key=key, kind="input", payload={"message_id": key.split(":")[1]})
                assert not await worker.dispatch_once()
                await db.rollback()
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(RuntimeDispatch)) == 0
                await save_runtime_dispatch(db, key=key, kind="input", payload={"message_id": key.split(":")[1]})
                await db.commit()
            async def no_redis(kind, payload):
                assert engine.pool.checkedout() == 0
                # The unavailable queue cannot lock unrelated project work.
                async with sessions() as db:
                    await db.execute(update(Project).where(Project.id == project_id).values(name="Still available"))
                    await db.commit()
                return False
            monkeypatch.setattr(worker, "_dispatch", no_redis)
            assert await worker.dispatch_once()
            async with sessions() as db:
                row = await db.scalar(select(RuntimeDispatch))
                assert row.status == "pending" and row.attempts == 1 and row.last_error
                row.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                await db.commit()
            monkeypatch.setattr(worker, "_dispatch", AsyncMock(return_value=True))
            assert await worker.dispatch_once()
            async with sessions() as db:
                row = await db.scalar(select(RuntimeDispatch))
                assert row.status == "pending"  # enqueue is not execution
                await acknowledge_runtime_dispatch(db, "input", UUID(key.split(":")[1]))
                await db.commit()
            assert not await worker.dispatch_once()
    asyncio.run(run())


def test_interrupted_intake_goes_to_review_and_cleanup_keeps_pending(monkeypatch):
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, _):
            old = datetime.now(timezone.utc) - timedelta(days=100)
            async with sessions() as db:
                await accept_telegram_update(db, bot_id=bot_id, payload=payload())
                await accept_telegram_update(db, bot_id=bot_id, payload=payload(2, 200))
                await accept_telegram_update(db, bot_id=bot_id, payload=payload(3, 300))
                await db.execute(update(TelegramInbox).where(TelegramInbox.update_id == 3).values(status="done", completed_at=old))
                await db.execute(update(TelegramInbox).where(TelegramInbox.update_id == 1).values(status="processing", claimed_at=old))
                await db.execute(update(TelegramInbox).values(created_at=old))
                await db.commit()
            await worker.maintain_delivery_queues()
            async with sessions() as db:
                rows = list((await db.scalars(select(TelegramInbox).order_by(TelegramInbox.update_id))).all())
                assert [row.status for row in rows] == ["review", "pending"]
    asyncio.run(run())


def test_fk_message_insert_does_not_block_runtime_lock_upgrade(monkeypatch):
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            async with sessions() as db:
                chat = Chat(project_id=project_id, bot_id=bot_id, external_chat_id="100", external_user_id="100")
                db.add(chat); await db.commit(); chat_id = chat.id
            async with sessions() as incoming, sessions() as runtime:
                # Both inserts hold FK KEY SHARE on the same parent chat.
                for db in (incoming, runtime):
                    db.add(Message(chat_id=chat_id, message_type="text", sender_type="user", body="QA"))
                    await db.flush()
                # FOR UPDATE would block here, then deadlock with incoming's UPDATE.
                async with asyncio.timeout(2):
                    assert await FunnelRepository(runtime)._lock_chat_row(chat_id)
                update_task = asyncio.create_task(incoming.execute(update(Chat).where(Chat.id == chat_id).values(is_read=False)))
                await runtime.commit()
                await asyncio.wait_for(update_task, 2)
                await incoming.commit()
    asyncio.run(run())


def test_timeouts_identify_the_actual_stage_and_limit():
    async def run():
        with pytest.raises(ScheduledOperationTimeout) as error:
            async with _operation_timeout("claim_job", 0.01):
                await asyncio.sleep(1)
        assert error.value.stage == "claim_job"
        assert "limit_seconds=0.01" in _error_text(error.value)
        assert "300" not in _error_text(TimeoutError())
    asyncio.run(run())


def test_arq_producer_reuses_pool_and_keeps_duplicate_ids(monkeypatch):
    if not os.getenv("CRM_TEST_REDIS_URL"):
        pytest.skip("Disposable Redis required")
    async def run():
        key = "qa-delivery:" + uuid4().hex
        try:
            assert get_arq_client() is get_arq_client()
            first = await enqueue_runtime_job("qa_unused", _job_id=key, _queue_name=JOBS_QUEUE_NAME)
            second = await enqueue_runtime_job("qa_unused", _job_id=key, _queue_name=JOBS_QUEUE_NAME)
            assert first is not None and second is None
        finally:
            redis = get_arq_client()
            await redis.delete("arq:job:" + key)
            await redis.zrem(JOBS_QUEUE_NAME, key)
            await close_arq_client()
    asyncio.run(run())


def test_partial_runtime_dispatch_requires_review_and_cannot_run_again(monkeypatch):
    from app.services.runtime_dispatch_service import RuntimeDispatchNeedsReview, protect_dispatch_replay
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            message_id = uuid4()
            async with sessions() as db:
                await save_runtime_dispatch(db, key=f"start:{message_id}", kind="start", payload={})
                await db.commit()
            async with sessions() as db:
                with pytest.raises(RuntimeDispatchNeedsReview):
                    async with protect_dispatch_replay(db, "start", message_id):
                        await db.execute(update(Project).where(Project.id == project_id).values(name="Committed before send"))
                        await db.commit()
                        note_external_delivery()
                        raise PoolTimeout("post-send write failed")
            assert not await worker.dispatch_once()
            async with sessions() as db:
                assert (await db.scalar(select(RuntimeDispatch))).status == "review"
                with pytest.raises(RuntimeDispatchNeedsReview):
                    async with protect_dispatch_replay(db, "start", message_id):
                        pytest.fail("A reviewed dispatch was replayed")
    asyncio.run(run())


def test_migration_0095_adds_queues_without_changing_history(monkeypatch):
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            async with sessions() as db:
                chat = Chat(project_id=project_id, bot_id=bot_id, external_chat_id="history", external_user_id="history")
                db.add(chat); await db.flush()
                message = Message(chat_id=chat.id, sender_type="user", message_type="text", body="History must survive")
                db.add(message); await db.commit(); message_id = message.id
            async with engine.begin() as db:
                await db.run_sync(lambda conn: RuntimeDispatch.__table__.drop(conn))
                await db.run_sync(lambda conn: TelegramInbox.__table__.drop(conn))
                spec = importlib.util.spec_from_file_location("delivery_migration", "alembic/versions/20261105_0095_telegram_delivery.py")
                migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
                def upgrade(conn):
                    with Operations.context(MigrationContext.configure(conn)):
                        migration.upgrade()
                await db.run_sync(upgrade)
            async with sessions() as db:
                assert (await db.get(Project, project_id)).name == "Delivery QA"
                assert (await db.get(Message, message_id)).body == "History must survive"
                await accept_telegram_update(db, bot_id=bot_id, payload=payload())
                await save_runtime_dispatch(db, key="qa", kind="start", payload={})
                await db.commit()
                assert await db.scalar(select(func.count()).select_from(RuntimeDispatch)) == 1
                assert await db.scalar(select(func.count()).select_from(TelegramInbox)) == 1
            with pytest.raises(RuntimeError): migration.downgrade()
    asyncio.run(run())


def test_real_funnel_start_and_answer_pass_through_durable_pipeline_once(monkeypatch):
    from app.models import LeadStatus
    from app.models.funnel import ChatFunnelState, Funnel, FunnelEdge, FunnelStep, FunnelVersion
    from app.services.telegram_sender import TelegramSenderService
    from app.workers import postback_worker as jobs
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            monkeypatch.setattr(jobs, "get_db_session", sessions)
            sends = []
            async def send(sender, **kwargs):
                if sender.release_transaction_before_network and sender.db.in_transaction():
                    await sender.db.commit()
                note_external_delivery()
                sends.append(kwargs["text"])
                return {"message_id": 1000 + len(sends)}
            monkeypatch.setattr(TelegramSenderService, "send_message", send)
            async with sessions() as db:
                db.add(LeadStatus(name="New", code="new"))
                funnel = Funnel(project_id=project_id, bot_id=bot_id, name="Pipeline")
                db.add(funnel); await db.flush()
                version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="published")
                db.add(version); await db.flush()
                bot = await db.get(Bot, bot_id)
                bot.active_funnel_id, bot.active_funnel_version_id = funnel.id, version.id
                funnel.current_version_id = version.id
                start = FunnelStep(funnel_version_id=version.id, key="start", title="Start", step_type="trigger", block_type="generic_start", config_json={})
                question = FunnelStep(funnel_version_id=version.id, key="question", title="Question", step_type="input", block_type="generic_input", config_json={"prompt": "Continue?", "timeout_seconds": 0})
                final = FunnelStep(funnel_version_id=version.id, key="final", title="Final", step_type="input", block_type="generic_input", config_json={"prompt": "Done", "timeout_seconds": 0})
                db.add_all([start, question, final]); await db.flush()
                db.add_all([FunnelEdge(funnel_version_id=version.id, from_step_id=start.id, to_step_id=question.id),
                            FunnelEdge(funnel_version_id=version.id, from_step_id=question.id, to_step_id=final.id, condition_json={"source_key": "input:next"})])
                await accept_telegram_update(db, bot_id=bot_id, payload=payload())
                await db.commit(); final_id = final.id
            assert await worker.process_next_inbox()
            async with sessions() as db:
                row = await db.scalar(select(RuntimeDispatch).where(RuntimeDispatch.kind == "start"))
                request = dict(row.payload_json)
                assert await db.scalar(select(func.count()).select_from(Message)) == 1
            assert (await jobs.process_funnel_start_task({}, request["chat_id"], request["message_id"], True))["status"] == "processed"
            assert (await jobs.process_funnel_start_task({}, request["chat_id"], request["message_id"], True))["status"] == "already_processed"
            assert sends == ["Continue?"]
            answer = payload(2); answer["message"]["text"] = "Yes"
            async with sessions() as db:
                await accept_telegram_update(db, bot_id=bot_id, payload=answer)
                await db.commit()
            assert await worker.process_next_inbox()
            async with sessions() as db:
                row = await db.scalar(select(RuntimeDispatch).where(RuntimeDispatch.kind == "input"))
                request = dict(row.payload_json)
            await asyncio.sleep(2.1)
            assert (await jobs.process_user_input_task({}, request["chat_id"], request["message_id"]))["status"] == "processed"
            assert (await jobs.process_user_input_task({}, request["chat_id"], request["message_id"]))["status"] == "already_processed"
            async with sessions() as db:
                state = await db.scalar(select(ChatFunnelState))
                assert state.current_step_id == final_id and state.waiting_for_answer
                assert list((await db.scalars(select(RuntimeDispatch.status))).all()) == ["done", "done"]
                assert list((await db.scalars(select(TelegramInbox.status))).all()) == ["done", "done"]
            assert sends == ["Continue?", "Done"]
    asyncio.run(run())


def test_lost_redis_ack_does_not_create_another_start_job(monkeypatch):
    if not os.getenv("CRM_TEST_REDIS_URL"):
        pytest.skip("Disposable Redis required")
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            message_id, chat_id = uuid4(), uuid4()
            key = f"funnel-start:{message_id}"
            original = worker._dispatch
            try:
                async with sessions() as db:
                    await save_runtime_dispatch(db, key=f"start:{message_id}", kind="start", payload={
                        "chat_id": str(chat_id), "message_id": str(message_id), "fresh_lifecycle": True})
                    await db.commit()
                async def lose_ack(kind, payload):
                    assert engine.pool.checkedout() == 0
                    assert await original(kind, payload)
                    raise TimeoutError("lost enqueue response")
                monkeypatch.setattr(worker, "_dispatch", lose_ack)
                assert await worker.dispatch_once()
                async with sessions() as db:
                    await db.execute(update(RuntimeDispatch).values(available_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
                    await db.commit()
                monkeypatch.setattr(worker, "_dispatch", original)
                assert await worker.dispatch_once()
                redis = get_arq_client()
                from arq.jobs import Job
                job = await Job(key, redis).info()
                assert job.args == (str(chat_id), str(message_id), True)
                assert sum(item.decode() == key for item in await redis.zrange(JOBS_QUEUE_NAME, 0, -1)) == 1
            finally:
                redis = get_arq_client()
                await redis.delete("arq:job:" + key)
                await redis.zrem(JOBS_QUEUE_NAME, key)
                await close_arq_client()
    asyncio.run(run())


def test_consumer_ack_is_not_overwritten_by_slow_dispatcher(monkeypatch):
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            message_id = uuid4()
            async with sessions() as db:
                await save_runtime_dispatch(db, key=f"input:{message_id}", kind="input", payload={})
                await db.commit()
            async def consumer_is_faster(kind, payload):
                async with sessions() as db:
                    await acknowledge_runtime_dispatch(db, "input", message_id)
                    await db.commit()
                return True
            monkeypatch.setattr(worker, "_dispatch", consumer_is_faster)
            assert await worker.dispatch_once()
            async with sessions() as db:
                assert (await db.scalar(select(RuntimeDispatch))).status == "done"
    asyncio.run(run())


def test_unresponsive_redis_has_bounded_producer_wait(monkeypatch):
    async def run():
        writers = []
        def ignore(reader, writer): writers.append(writer)
        server = await asyncio.start_server(ignore, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr(settings, "REDIS_URL", f"redis://127.0.0.1:{port}/0")
        monkeypatch.setattr(settings, "RUNTIME_REDIS_TIMEOUT_SECONDS", 0.05)
        try:
            async with asyncio.timeout(1):
                with pytest.raises((TimeoutError, RedisTimeout)):
                    await enqueue_runtime_job("qa_unused", _queue_name=JOBS_QUEUE_NAME)
        finally:
            await close_arq_client()
            server.close(); await server.wait_closed()
            for writer in writers: writer.close()
            for writer in writers: await writer.wait_closed()
    asyncio.run(run())


def test_execution_fence_serializes_consumers_and_recovers_interruption_to_review(monkeypatch):
    from app.services.runtime_dispatch_service import RuntimeDispatchAlreadyHandled, protect_dispatch_replay
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            message_id = uuid4()
            async with sessions() as db:
                await save_runtime_dispatch(db, key=f"start:{message_id}", kind="start", payload={})
                await db.commit()
            async with sessions() as first:
                async with protect_dispatch_replay(first, "start", message_id):
                    async with sessions() as second:
                        with pytest.raises(RuntimeDispatchAlreadyHandled) as busy:
                            async with protect_dispatch_replay(second, "start", message_id):
                                pytest.fail("Concurrent consumer passed the execution fence")
                        assert busy.value.status == "already_processing"
                    assert not await worker.dispatch_once()
                    # Simulate a process that exits before acknowledging its job.
            async with sessions() as db:
                await db.execute(update(RuntimeDispatch).values(claimed_at=datetime.now(timezone.utc) - timedelta(hours=1)))
                await db.commit()
            await worker.maintain_delivery_queues()
            async with sessions() as db:
                assert (await db.scalar(select(RuntimeDispatch))).status == "review"
    asyncio.run(run())


def test_db_error_before_effects_releases_execution_fence_for_retry(monkeypatch):
    from app.services.runtime_dispatch_service import protect_dispatch_replay
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            message_id = uuid4()
            async with sessions() as db:
                await save_runtime_dispatch(db, key=f"input:{message_id}", kind="input", payload={})
                await db.commit()
            async with sessions() as db:
                with pytest.raises(PoolTimeout):
                    async with protect_dispatch_replay(db, "input", message_id):
                        raise PoolTimeout("before any runtime write/send")
            async with sessions() as db:
                assert (await db.scalar(select(RuntimeDispatch))).status == "pending"
            async with sessions() as db:
                async with protect_dispatch_replay(db, "input", message_id):
                    await acknowledge_runtime_dispatch(db, "input", message_id)
                    await db.commit()
            async with sessions() as db:
                assert (await db.scalar(select(RuntimeDispatch))).status == "done"
    asyncio.run(run())


def test_intake_burst_preserves_every_update_while_redis_is_unavailable(monkeypatch):
    from app.models import Lead, LeadStatus
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            monkeypatch.setattr("app.core.database.get_db_session", sessions)
            async with sessions() as db:
                db.add(LeadStatus(code="new", name="New")); await db.commit()
            app = FastAPI(); app.include_router(route.router)
            monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", None)
            unavailable = AsyncMock(return_value=False)
            monkeypatch.setattr(worker, "_dispatch", unavailable)
            count = 160
            limiter = asyncio.Semaphore(12)
            started = time.monotonic()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://qa") as client:
                async def accept(number):
                    async with limiter:
                        response = await client.post(f"/telegram/webhook/{bot_id}", json=payload(number, 1000 + number % 80))
                        assert response.status_code == 200
                async with asyncio.timeout(30):
                    await asyncio.gather(*(accept(i) for i in range(1, count + 1)))
                    async def drain():
                        while await worker.process_next_inbox(): pass
                    await asyncio.gather(*(drain() for _ in range(4)))
            unavailable.assert_not_awaited()
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(TelegramInbox).where(TelegramInbox.status == "done")) == count
                assert await db.scalar(select(func.count()).select_from(Message)) == count
                assert await db.scalar(select(func.count()).select_from(RuntimeDispatch).where(RuntimeDispatch.status == "pending")) == count
                assert await db.scalar(select(func.count()).select_from(Chat)) == 80
                assert await db.scalar(select(func.count()).select_from(Lead)) == 80
            assert await worker.dispatch_once()
            print(f"\nDurable intake burst: {count} updates persisted in {time.monotonic() - started:.2f}s; Redis unavailable")
    asyncio.run(run())


def test_failed_migration_rolls_back_queue_tables_and_keeps_existing_data(monkeypatch):
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            async with sessions() as db:
                chat = Chat(project_id=project_id, bot_id=bot_id, external_chat_id="history", external_user_id="history")
                db.add(chat); await db.flush()
                message = Message(chat_id=chat.id, sender_type="user", message_type="text", body="History must survive failed DDL")
                db.add(message); await db.commit(); message_id = message.id
            async with engine.begin() as db:
                await db.run_sync(lambda conn: RuntimeDispatch.__table__.drop(conn))
                await db.run_sync(lambda conn: TelegramInbox.__table__.drop(conn))
            spec = importlib.util.spec_from_file_location("failed_delivery_migration", "alembic/versions/20261105_0095_telegram_delivery.py")
            migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
            create_index = migration.op.create_index
            def fail_index(name, *args, **kwargs):
                if name == "ix_runtime_dispatches_due": raise RuntimeError("Simulated DDL failure")
                return create_index(name, *args, **kwargs)
            def upgrade(conn):
                with Operations.context(MigrationContext.configure(conn)):
                    with monkeypatch.context() as patch:
                        patch.setattr(migration.op, "create_index", fail_index)
                        migration.upgrade()
            with pytest.raises(RuntimeError, match="Simulated DDL failure"):
                async with engine.begin() as db:
                    await db.run_sync(upgrade)
            async with sessions() as db:
                assert await db.scalar(text("SELECT to_regclass('telegram_inbox')")) is None
                assert await db.scalar(text("SELECT to_regclass('runtime_dispatches')")) is None
                assert (await db.get(Project, project_id)).name == "Delivery QA"
                assert await db.get(Bot, bot_id) is not None
                assert (await db.get(Message, message_id)).body == "History must survive failed DDL"
    asyncio.run(run())


def test_start_advertising_event_observes_committed_lead_message_and_dispatch(monkeypatch):
    from app.models import Lead, LeadStatus
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            async with sessions() as db:
                db.add(LeadStatus(code="new", name="New"))
                await accept_telegram_update(db, bot_id=bot_id, payload=payload())
                await db.commit()
            observed = []
            async def check_visibility(service, *, lead_id, **kwargs):
                async with sessions() as consumer:
                    assert await consumer.get(Lead, lead_id) is not None
                    assert await consumer.scalar(select(func.count()).select_from(Message)) == 1
                    assert await consumer.scalar(select(func.count()).select_from(RuntimeDispatch)) == 1
                observed.append(lead_id)
            monkeypatch.setattr(TelegramService, "_enqueue_facebook_event_safely", check_visibility)
            assert await worker.process_next_inbox()
            assert len(observed) == 1
            async with sessions() as db:
                assert (await db.scalar(select(TelegramInbox))).status == "done"
    asyncio.run(run())


def test_legacy_start_recovery_does_not_claim_or_replay_durable_inputs(monkeypatch):
    from app.services import funnel_start_recovery_service as recovery
    from app.services.funnel_start_queue import FunnelStartEnqueueResult
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            async with sessions() as db:
                chat = Chat(project_id=project_id, bot_id=bot_id, external_chat_id="100", external_user_id="100")
                db.add(chat); await db.flush()
                messages = [Message(chat_id=chat.id, sender_type="user", message_type="text", body="/start") for _ in range(3)]
                db.add_all(messages); await db.flush()
                for kind, message in zip(("start", "input"), messages):
                    await save_runtime_dispatch(db, key=f"{kind}:{message.id}", kind=kind, payload={})
                await db.commit()
                ids = [message.id for message in messages]
            enqueue = AsyncMock(return_value=FunnelStartEnqueueResult(1, 1, 0, 0))
            monkeypatch.setattr(recovery, "enqueue_funnel_starts", enqueue)
            async with sessions() as db:
                result = await recovery.FunnelStartRecoveryService(db).recover(job_scope="qa")
                assert result.scanned == result.eligible == 1
                assert enqueue.await_args.args[0][0].message_id == ids[2]
                for message_id in ids[:2]:
                    assert (await db.get(Message, message_id)).funnel_processed_at is None
    asyncio.run(run())


def test_partial_message_claim_does_not_consume_the_unhandled_answer(monkeypatch):
    from app.repositories.message_repository import MessageRepository
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            async with sessions() as db:
                chat = Chat(project_id=project_id, bot_id=bot_id, external_chat_id="100", external_user_id="100")
                db.add(chat); await db.flush()
                first = Message(chat_id=chat.id, sender_type="user", message_type="text", body="/start", funnel_processed_at=datetime.now(timezone.utc))
                answer = Message(chat_id=chat.id, sender_type="user", message_type="text", body="Answer")
                db.add_all([first, answer]); await db.commit()
                first_id, answer_id = first.id, answer.id
                repo = MessageRepository(db)
                assert not await repo.claim_funnel_processing([first_id, answer_id])
                await db.refresh(answer)
                assert answer.funnel_processed_at is None
                assert await repo.claim_funnel_processing([answer_id])
                await db.commit()
                await db.refresh(answer)
                assert answer.funnel_processed_at is not None
    asyncio.run(run())


def test_new_answer_batch_does_not_replay_inputs_waiting_for_review(monkeypatch):
    from app.repositories.message_repository import MessageRepository
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            async with sessions() as db:
                chat = Chat(project_id=project_id, bot_id=bot_id, external_chat_id="100", external_user_id="100")
                db.add(chat); await db.flush()
                now = datetime.now(timezone.utc)
                messages = [Message(chat_id=chat.id, sender_type="user", message_type="text", body=str(i),
                                    created_at=now - timedelta(seconds=30 - i)) for i in range(3)]
                db.add_all(messages); await db.flush()
                for kind, message in zip(("start", "input"), messages):
                    await save_runtime_dispatch(db, key=f"{kind}:{message.id}", kind=kind, payload={})
                await db.execute(update(RuntimeDispatch).values(status="review"))
                await db.commit()
                batch = await MessageRepository(db).list_unprocessed_user_input_batch(chat.id, through_message=messages[2])
                assert [item.id for item in batch] == [messages[2].id]
                assert messages[0].funnel_processed_at is None and messages[1].funnel_processed_at is None
    asyncio.run(run())


def test_runtime_input_lock_refreshes_lifecycle_flags_before_processing(monkeypatch):
    from app.repositories.chat_repository import ChatRepository
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            async with sessions() as db:
                chat = Chat(project_id=project_id, bot_id=bot_id, external_chat_id="100", external_user_id="100")
                db.add(chat); await db.commit(); chat_id = chat.id
            async with sessions() as reader:
                cached = await reader.get(Chat, chat_id)
                assert cached.reset_at is None
                async with sessions() as writer:
                    await writer.execute(update(Chat).where(Chat.id == chat_id).values(reset_at=datetime.now(timezone.utc)))
                    await writer.commit()
                locked = await ChatRepository(reader).get_for_runtime_input(chat_id)
                assert locked is cached and locked.reset_at is not None
    asyncio.run(run())
