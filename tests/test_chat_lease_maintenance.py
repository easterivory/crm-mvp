import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from sqlalchemy import func, select

from app.models import Chat, Lead, Project
from app.models.audit_log import AuditLog
from app.services.chat_lease_service import ChatLeaseService
from app.services import chat_lease_maintenance_service as maintenance
from test_chat_counts_coordination import environment, pytestmark


def test_jobs_worker_is_not_needed_for_api_maintenance():
    from app.workers.postback_worker import WorkerSettings
    assert maintenance.maintain_chat_leases_task not in WorkerSettings.functions
    assert not any(row.coroutine is maintenance.maintain_chat_leases_task for row in WorkerSettings.cron_jobs)
    assert maintenance.PASS_TIMEOUT_SECONDS < maintenance.LOCK_SECONDS < maintenance.INTERVAL_SECONDS


def test_expired_leases_release_once_with_audit_and_current_leases_remain(monkeypatch):
    async def run():
        async with environment(monkeypatch) as (sessions, actor, projects, _):
            monkeypatch.setattr(maintenance, "get_db_session", sessions)
            async with sessions() as db:
                leads = list((await db.scalars(select(Lead).where(Lead.project_id == projects[0]).order_by(Lead.id))).all())
                for i, lead in enumerate(leads):
                    lead.manager_id = actor.id
                    chat = await db.get(Chat, lead.chat_id)
                    chat.assignment_expires_at = datetime.now(timezone.utc) + timedelta(minutes=-5 if i == 0 else 5)
                await db.commit()
                expired, current = leads[0].id, [lead.id for lead in leads[1:]]
            outcomes = await asyncio.gather(maintenance.maintain_chat_leases_task({}), maintenance.maintain_chat_leases_task({}))
            assert sum(row["released"] for row in outcomes) == 1
            async with sessions() as db:
                assert (await db.get(Lead, expired)).manager_id is None
                assert all(lead.manager_id == actor.id for lead in [await db.get(Lead, lid) for lid in current])
                logs = list((await db.scalars(select(AuditLog).where(AuditLog.entity_id == expired))).all())
                assert len(logs) == 1 and logs[0].meta["reason"] == "chat_lease_expired"
    asyncio.run(run())


def test_one_project_failure_rolls_back_and_does_not_stop_other_expiries(monkeypatch):
    async def run():
        async with environment(monkeypatch) as (sessions, actor, projects, _):
            monkeypatch.setattr(maintenance, "get_db_session", sessions)
            async with sessions() as db:
                for lead in (await db.scalars(select(Lead))).all():
                    lead.manager_id = actor.id
                    (await db.get(Chat, lead.chat_id)).assignment_expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
                await db.commit()
            original = ChatLeaseService.release_expired
            async def fail_after_write(self, **kwargs):
                count = await original(self, **kwargs)
                if kwargs["project_id"] == projects[0]: raise TimeoutError("simulated failure after write")
                return count
            monkeypatch.setattr(ChatLeaseService, "release_expired", fail_after_write)
            outcome = await maintenance.maintain_chat_leases_task({})
            assert outcome["released"] == 3
            async with sessions() as db:
                original_leads = list((await db.scalars(select(Lead).where(Lead.project_id == projects[0]))).all())
                assert all(lead.manager_id == actor.id for lead in original_leads)
                assert await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.project_id == projects[0])) == 0
    asyncio.run(run())


def test_cursor_covers_bounded_project_pages_and_skips_disabled_projects(monkeypatch):
    async def run():
        async with environment(monkeypatch) as (sessions, _, projects, _):
            monkeypatch.setattr(maintenance, "get_db_session", sessions)
            async with sessions() as db:
                for n in range(10): db.add(Project(name=f"Page {n}", slug=f"page-{n}"))
                disabled = Project(name="Disabled", slug="disabled", chat_lease_minutes=0)
                archived = Project(name="Archived", slug="archived", status="archived")
                db.add_all([disabled, archived]); await db.commit()
                disabled_ids = {disabled.id, archived.id}
            seen = []
            async def record(self, **kwargs): seen.append(kwargs["project_id"]); return 0
            monkeypatch.setattr(ChatLeaseService, "release_expired", record)
            ctx = {}
            assert (await maintenance.maintain_chat_leases_task(ctx))["projects"] == 8
            assert (await maintenance.maintain_chat_leases_task(ctx))["projects"] == 5
            assert len(set(seen)) == 13 and not (set(seen) & disabled_ids)
            assert ctx["chat_lease_cursor"] is None
    asyncio.run(run())


def test_api_lifespan_starts_without_waiting_and_drains_before_clients_close(monkeypatch):
    import app.main as main
    from app.services import chat_workspace_counts_service as counters
    from app.core import assistant, telegram_intake
    async def run():
        entered, drained, order = asyncio.Event(), asyncio.Event(), []
        async def loop():
            entered.set()
            try: await asyncio.Event().wait()
            finally: drained.set(); order.append("drained")
        async def webhook(): await asyncio.Event().wait()
        async def close():
            assert drained.is_set()
            order.append("close")
        monkeypatch.setattr(maintenance, "run_chat_lease_maintenance", loop)
        monkeypatch.setattr(main, "sync_telegram_webhook_subscriptions", webhook)
        for module, name in [(main, "close_redis"), (main, "close_arq_client"),
                (counters, "close_counter_refreshes"), (assistant, "close_assistant_db"),
                (telegram_intake, "close_reserved_db_pools")]:
            monkeypatch.setattr(module, name, close)
        async with main.lifespan(main.app):
            await asyncio.wait_for(entered.wait(), 1)
            assert not drained.is_set()
        assert order == ["drained"] + ["close"] * 5
    asyncio.run(run())


def test_redis_lock_serializes_api_processes_and_release_is_token_owned(monkeypatch):
    async def run():
        async with environment(monkeypatch) as (_, _, _, redis):
            async def get_redis(): return redis
            monkeypatch.setattr(maintenance, "get_redis", get_redis)
            monkeypatch.setattr(maintenance, "LOCK_KEY", f"qa:leases:{uuid4().hex}")
            entered, resume = asyncio.Event(), asyncio.Event()
            calls = []
            async def work(ctx):
                calls.append(ctx); entered.set(); await resume.wait()
                return {"projects": 1, "released": 1}
            monkeypatch.setattr(maintenance, "maintain_chat_leases_task", work)
            first = asyncio.create_task(maintenance.maintain_chat_leases_once({}))
            await asyncio.wait_for(entered.wait(), 1)
            assert await maintenance.maintain_chat_leases_once({}) is None
            assert len(calls) == 1
            # An expired/replaced owner must never have its lock deleted by us.
            await redis.set(maintenance.LOCK_KEY, "other-owner", ex=25)
            resume.set(); assert (await first)["released"] == 1
            assert await redis.get(maintenance.LOCK_KEY) == b"other-owner"
            await redis.delete(maintenance.LOCK_KEY)
    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_pass_timeout_and_shutdown_cancel_roll_back_writes_and_release_lock(monkeypatch, cancel):
    async def run():
        async with environment(monkeypatch) as (sessions, actor, projects, redis):
            async def get_redis(): return redis
            monkeypatch.setattr(maintenance, "get_db_session", sessions)
            monkeypatch.setattr(maintenance, "get_redis", get_redis)
            monkeypatch.setattr(maintenance, "LOCK_KEY", f"qa:leases:{uuid4().hex}")
            monkeypatch.setattr(maintenance, "PASS_TIMEOUT_SECONDS", 2 if cancel else 0.2)
            async with sessions() as db:
                lead = (await db.scalars(select(Lead).where(Lead.project_id == projects[0]))).first()
                lead.manager_id = actor.id
                (await db.get(Chat, lead.chat_id)).assignment_expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
                await db.commit(); lid = lead.id
            entered = asyncio.Event()
            original = ChatLeaseService.release_expired
            async def block_after_write(self, **kwargs):
                await original(self, **kwargs)
                entered.set(); await asyncio.Event().wait()
            monkeypatch.setattr(ChatLeaseService, "release_expired", block_after_write)
            task = asyncio.create_task(maintenance.maintain_chat_leases_once({}))
            await asyncio.wait_for(entered.wait(), 1)
            if cancel: task.cancel()
            with suppress(asyncio.CancelledError): await task
            assert not await redis.exists(maintenance.LOCK_KEY)
            async with sessions() as db:
                assert (await db.get(Lead, lid)).manager_id == actor.id
                assert await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.entity_id == lid)) == 0
    asyncio.run(run())


def test_loop_recovers_after_error_without_overlapping_passes(monkeypatch):
    async def run():
        calls, active, peak = 0, 0, 0
        reached = asyncio.Event()
        contexts = []
        async def work(ctx):
            nonlocal calls, active, peak
            calls += 1; active += 1; peak = max(peak, active); contexts.append(ctx)
            try:
                if calls == 1: raise RuntimeError("simulated")
                await asyncio.sleep(0.01)
                if calls == 3: reached.set()
            finally: active -= 1
        monkeypatch.setattr(maintenance, "maintain_chat_leases_once", work)
        monkeypatch.setattr(maintenance, "INTERVAL_SECONDS", 0.01)
        task = asyncio.create_task(maintenance.run_chat_lease_maintenance())
        await asyncio.wait_for(reached.wait(), 1)
        task.cancel()
        with suppress(asyncio.CancelledError): await task
        assert calls == 3 and peak == 1 and all(ctx is contexts[0] for ctx in contexts)
    asyncio.run(run())


def test_unavailable_redis_skips_writes_instead_of_failing_api(monkeypatch):
    from redis.exceptions import ConnectionError
    async def run():
        async def unavailable(): raise ConnectionError("disposable failure")
        async def forbidden(ctx): raise AssertionError("No unlocked maintenance writes")
        monkeypatch.setattr(maintenance, "get_redis", unavailable)
        monkeypatch.setattr(maintenance, "maintain_chat_leases_task", forbidden)
        assert await maintenance.maintain_chat_leases_once({}) is None
    asyncio.run(run())
