"""Regression for the failed production gate: actual PostgreSQL pool and Redis."""
import asyncio
import os
import json
import time
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Bot, Chat, Lead, Project
from app.repositories.chat_repository import ChatRepository
from app.services import chat_workspace_counts_service as counters
from app.services.chat_service import ChatService
from test_gambling_offers import PG, fixture

pytestmark = [PG, pytest.mark.skipif(not os.getenv("CRM_TEST_REDIS_URL"), reason="Disposable Redis required")]


async def request(sessions, actor, pid, **kwargs):
    async with sessions() as db:
        return await ChatService(db).get_workspace_counts(project_id=pid, actor=actor, **kwargs)


async def age_snapshots(redis, seconds):
    state = counters._state()
    for key, snapshot in list(state.snapshots.items()):
        state.snapshots[key] = counters.Snapshot(snapshot.counts, time.time() - seconds)
        await redis.set(key, json.dumps({"counts": snapshot.counts, "as_of": time.time() - seconds}), ex=60)


@asynccontextmanager
async def environment(monkeypatch):
    async with fixture() as (sessions, pid, actor, leads, bid, _):
        async with sessions() as db:
            schema = await db.scalar(text("SELECT current_schema()"))
            status_id = (await db.get(Lead, leads[0])).status_id
            projects = [pid]
            for n in range(2):
                project = Project(name=f"Other {n}", slug=f"other-{n}")
                db.add(project); await db.flush()
                bot = Bot(project_id=project.id, name=f"Other {n}")
                db.add(bot); await db.flush()
                for i in range(n + 1):
                    chat = Chat(project_id=project.id, bot_id=bot.id,
                        external_chat_id=str(i), external_user_id=str(i))
                    db.add(chat); await db.flush()
                    db.add(Lead(project_id=project.id, chat_id=chat.id, status_id=status_id))
                projects.append(project.id)
            await db.commit()
        engine = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"], pool_size=1,
            max_overflow=0, pool_timeout=0.5, connect_args={"server_settings": {
                "search_path": schema, "jit": "off", "max_parallel_workers_per_gather": "0",
                "statement_timeout": "3000", "default_transaction_read_only": "on"}})
        redis = Redis.from_url(os.environ["CRM_TEST_REDIS_URL"])
        async def get_redis(): return redis
        monkeypatch.setattr(counters, "get_count_db_session", async_sessionmaker(engine, expire_on_commit=False))
        monkeypatch.setattr(counters, "get_redis", get_redis)
        try:
            yield sessions, actor, projects, redis
        finally:
            close = getattr(counters, "close_counter_refreshes", None)
            if close is not None: await close()
            await engine.dispose()
            await redis.aclose()


@PG
@pytest.mark.skipif(not os.getenv("CRM_TEST_REDIS_URL"), reason="Disposable Redis required")
def test_three_projects_wait_before_real_single_connection_checkout(monkeypatch):
    async def run():
        async with environment(monkeypatch) as (sessions, actor, projects, _):
            original = ChatRepository.shared_workspace_counts
            entered = asyncio.Event()
            calls, active, peak = [], 0, 0
            async def slow(repo, **kwargs):
                nonlocal active, peak
                calls.append(kwargs["project_id"]); active += 1; peak = max(peak, active)
                entered.set()
                try:
                    await repo.db.execute(text("SELECT pg_sleep(0.9)"))
                    return await original(repo, **kwargs)
                finally: active -= 1
            monkeypatch.setattr(ChatRepository, "shared_workspace_counts", slow)
            async def request(pid):
                async with sessions() as db:
                    return await ChatService(db).get_workspace_counts(project_id=pid, actor=actor)
            first = asyncio.create_task(request(projects[0]))
            await entered.wait()
            others = await asyncio.gather(*(request(pid) for pid in projects[1:]))
            results = [await first, *others]
            assert [row.all for row in results] == [3, 1, 2]
            assert peak == 1 and calls == projects
    asyncio.run(run())


def test_snapshot_returns_immediately_while_refresh_is_slow_and_then_updates(monkeypatch):
    async def run():
        async with environment(monkeypatch) as (sessions, actor, projects, redis):
            first = await request(sessions, actor, projects[0])
            assert first.all == 3 and not first.counts_stale and first.counts_as_of is not None
            await age_snapshots(redis, 20)
            original, calls = ChatRepository.shared_workspace_counts, []
            async def slow(repo, **kwargs):
                calls.append(1)
                await repo.db.execute(text("SELECT pg_sleep(0.9)"))
                return await original(repo, **kwargs)
            monkeypatch.setattr(ChatRepository, "shared_workspace_counts", slow)
            began = time.monotonic()
            results = await asyncio.gather(*(request(sessions, actor, projects[0]) for _ in range(20)))
            assert time.monotonic() - began < 0.7
            assert all(row.all == 3 and row.counts_stale and row.counts_refreshing for row in results)
            await asyncio.gather(*list(counters._state().tasks.values()))
            updated = await request(sessions, actor, projects[0])
            assert not updated.counts_stale and len(calls) == 1
            assert updated.counts_as_of > results[0].counts_as_of
    asyncio.run(run())


def test_sql_timeout_does_not_break_other_projects_or_serve_expired_snapshot(monkeypatch, caplog):
    async def run():
        async with environment(monkeypatch) as (sessions, actor, projects, redis):
            await request(sessions, actor, projects[0])
            await age_snapshots(redis, 20)
            original, entered = ChatRepository.shared_workspace_counts, asyncio.Event()
            async def failing(repo, **kwargs):
                if kwargs["project_id"] == projects[0]:
                    entered.set()
                    await repo.db.execute(text("SELECT pg_sleep(3.5)"))
                return await original(repo, **kwargs)
            monkeypatch.setattr(ChatRepository, "shared_workspace_counts", failing)
            stale = await request(sessions, actor, projects[0])
            assert stale.all == 3 and stale.counts_stale
            await entered.wait()
            others = await asyncio.gather(*(request(sessions, actor, pid) for pid in projects[1:]))
            assert [row.all for row in others] == [1, 2]
            stale = await request(sessions, actor, projects[0])
            assert stale.all == 3 and stale.counts_stale and not stale.counts_refreshing
            assert "sqlstate=57014" in caplog.text and "phase=counter_pool" not in caplog.text
            await age_snapshots(redis, 61)
            with pytest.raises(HTTPException) as unavailable:
                await request(sessions, actor, projects[0])
            assert unavailable.value.status_code == 503
    asyncio.run(run())


def test_cancelled_reader_does_not_cancel_shared_refresh_and_shutdown_releases_slot(monkeypatch):
    async def run():
        async with environment(monkeypatch) as (sessions, actor, projects, _):
            original, entered, calls = ChatRepository.shared_workspace_counts, asyncio.Event(), []
            async def slow(repo, **kwargs):
                calls.append(kwargs["project_id"]); entered.set()
                await repo.db.execute(text("SELECT pg_sleep(0.9)"))
                return await original(repo, **kwargs)
            monkeypatch.setattr(ChatRepository, "shared_workspace_counts", slow)
            reader = asyncio.create_task(request(sessions, actor, projects[0]))
            await entered.wait(); reader.cancel()
            with pytest.raises(asyncio.CancelledError): await reader
            assert (await request(sessions, actor, projects[0])).all == 3 and len(calls) == 1
            entered.clear()
            reader = asyncio.create_task(request(sessions, actor, projects[1]))
            await entered.wait()
            state = counters._state()
            await counters.close_counter_refreshes()
            with pytest.raises(asyncio.CancelledError): await reader
            assert not state.tasks and not state.admission.locked()
            assert (await request(sessions, actor, projects[2])).all == 2
    asyncio.run(run())


def test_redis_outage_keeps_real_pool_serial_and_local_snapshot_available(monkeypatch):
    async def run():
        async with environment(monkeypatch) as (sessions, actor, projects, _):
            async def outage(): raise OSError("offline")
            monkeypatch.setattr(counters, "get_redis", outage)
            original, active, peak = ChatRepository.shared_workspace_counts, 0, 0
            async def slow(repo, **kwargs):
                nonlocal active, peak
                active += 1; peak = max(peak, active)
                try:
                    await repo.db.execute(text("SELECT pg_sleep(0.7)"))
                    return await original(repo, **kwargs)
                finally: active -= 1
            monkeypatch.setattr(ChatRepository, "shared_workspace_counts", slow)
            results = await asyncio.gather(*(request(sessions, actor, pid) for pid in projects))
            assert [row.all for row in results] == [3, 1, 2] and peak == 1
            began = time.monotonic()
            assert (await request(sessions, actor, projects[0])).all == 3
            assert time.monotonic() - began < 0.5
    asyncio.run(run())


def test_manual_refresh_recomputes_fresh_cache_and_project_revisions_do_not_reuse_it(monkeypatch):
    async def run():
        async with environment(monkeypatch) as (sessions, actor, projects, _):
            first = await request(sessions, actor, projects[0])
            async with sessions() as db:
                bot = await db.scalar(select(Bot).where(Bot.project_id == projects[0]))
                db.add(Chat(project_id=projects[0], bot_id=bot.id, external_chat_id="new", external_user_id="new"))
                await db.commit()
            assert (await request(sessions, actor, projects[0])).all == first.all
            assert (await request(sessions, actor, projects[0], refresh=True)).all == 4
            async with sessions() as db:
                project = await db.get(Project, projects[0])
                project.hide_assigned_chats_from_all = True
                await db.commit()
            assert (await request(sessions, actor, projects[0])).all == 4
            assert len(counters._state().snapshots) == 2
    asyncio.run(run())


def test_counts_do_not_run_writable_lease_cleanup(monkeypatch):
    from app.services.chat_lease_service import ChatLeaseService
    async def forbidden(*args, **kwargs): pytest.fail("Counters tried to modify assignments")
    monkeypatch.setattr(ChatLeaseService, "release_expired", forbidden)
    async def run():
        async with environment(monkeypatch) as (sessions, actor, projects, _):
            assert (await request(sessions, actor, projects[0])).all == 3
    asyncio.run(run())


def test_bounded_queue_keeps_known_values_and_returns_no_fake_zero_for_cold_scope(monkeypatch):
    async def run():
        async with environment(monkeypatch) as (sessions, actor, projects, redis):
            await request(sessions, actor, projects[2])
            await age_snapshots(redis, 20)
            monkeypatch.setattr(counters, "MAX_REFRESHES", 2)
            entered, release = asyncio.Event(), asyncio.Event()
            original = ChatRepository.shared_workspace_counts
            async def blocked(repo, **kwargs):
                entered.set(); await release.wait()
                return await original(repo, **kwargs)
            monkeypatch.setattr(ChatRepository, "shared_workspace_counts", blocked)
            first = asyncio.create_task(request(sessions, actor, projects[0]))
            await entered.wait()
            second = asyncio.create_task(request(sessions, actor, projects[1]))
            for _ in range(100):
                if len(counters._state().tasks) == 2: break
                await asyncio.sleep(0.01)
            assert len(counters._state().tasks) == 2
            known = await request(sessions, actor, projects[2])
            assert known.all == 2 and known.counts_stale and not known.counts_refreshing
            async with sessions() as db: bid = await db.scalar(select(Bot.id).where(Bot.project_id == projects[2]))
            with pytest.raises(HTTPException) as cold:
                await request(sessions, actor, projects[2], bot_id=bid)
            assert cold.value.status_code == 503
            assert len(counters._state().tasks) == 2
            release.set()
            assert [row.all for row in await asyncio.gather(first, second)] == [3, 1]
    asyncio.run(run())


def test_equivalent_bot_scopes_share_cache_but_other_bots_do_not(monkeypatch):
    async def run():
        async with environment(monkeypatch) as (sessions, actor, projects, _):
            async with sessions() as db:
                bid = await db.scalar(select(Bot.id).where(Bot.project_id == projects[0]))
                other = Bot(project_id=projects[0], name="Empty")
                db.add(other); await db.commit(); other_bid = other.id
            original, calls = ChatRepository.shared_workspace_counts, []
            async def counted(repo, **kwargs): calls.append(kwargs); return await original(repo, **kwargs)
            monkeypatch.setattr(ChatRepository, "shared_workspace_counts", counted)
            assert (await request(sessions, actor, projects[0], bot_id=bid)).all == 3
            assert (await request(sessions, actor, projects[0], bot_ids=[bid, bid])).all == 3
            assert len(calls) == 1
            assert (await request(sessions, actor, projects[0], bot_id=other_bid)).all == 0
            assert (await request(sessions, actor, projects[0], bot_id=bid, bot_ids=[other_bid])).all == 0
            assert len(calls) == 3
    asyncio.run(run())


def test_remote_scope_lock_uses_published_snapshot_without_duplicate_sql(monkeypatch):
    async def run():
        async with environment(monkeypatch) as (sessions, actor, projects, redis):
            await request(sessions, actor, projects[0])
            await age_snapshots(redis, 20)
            key = next(iter(counters._state().snapshots))
            old = counters._state().snapshots[key]
            await redis.set(key + ":lock", "remote-owner", ex=10)
            async def forbidden(*args, **kwargs): pytest.fail("Duplicated remote refresh")
            monkeypatch.setattr(ChatRepository, "shared_workspace_counts", forbidden)
            pending = asyncio.create_task(request(sessions, actor, projects[0], refresh=True))
            await asyncio.sleep(0.2)
            await redis.set(key, json.dumps({"counts": old.counts, "as_of": time.time()}), ex=60)
            result = await pending
            assert result.all == 3 and not result.counts_stale
            assert result.counts_as_of.timestamp() > old.as_of
            assert await redis.get(key + ":lock") == b"remote-owner"
    asyncio.run(run())


def test_http_snapshot_metadata_manual_refresh_and_authorization_no_store(monkeypatch):
    import httpx
    from types import SimpleNamespace
    from app.main import app
    from app.api.v1.dependencies import get_current_user, get_db
    async def run():
        async with environment(monkeypatch) as (sessions, actor, projects, _):
            previous = dict(app.dependency_overrides)
            current_user = actor
            async def user(): return current_user
            async def database():
                async with sessions() as db: yield db
            app.dependency_overrides[get_current_user] = user
            app.dependency_overrides[get_db] = database
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    response = await client.get("/api/v1/chats/workspace-counts", params={"project_id": str(projects[0]), "refresh": "true"})
                    assert response.status_code == 200
                    assert response.json()["all"] == 3 and response.json()["counts_as_of"] is not None
                    assert response.json()["counts_stale"] is False
                    assert "managers" not in response.json()
                    assert response.headers["cache-control"] == "private, no-store"
                    assert "Authorization" in response.headers["vary"]
                    current_user = SimpleNamespace(id=actor.id, role_name="manager", project_id=projects[1])
                    denied = await client.get("/api/v1/chats/workspace-counts", params={"project_id": str(projects[0])})
                    assert denied.status_code == 403 and "counts_as_of" not in denied.json()
                    assert denied.headers["cache-control"] == "private, no-store"
            finally:
                app.dependency_overrides.clear(); app.dependency_overrides.update(previous)
    asyncio.run(run())


def test_remote_lock_wait_does_not_occupy_other_projects_sql_admission(monkeypatch):
    async def run():
        async with environment(monkeypatch) as (sessions, actor, projects, redis):
            await request(sessions, actor, projects[0])
            await age_snapshots(redis, 20)
            key = next(iter(counters._state().snapshots))
            snapshot = counters._state().snapshots[key]
            await redis.set(key + ":lock", "peer", ex=10)
            original_set, entered = redis.set, asyncio.Event()
            async def observed_set(name, value, **kwargs):
                result = await original_set(name, value, **kwargs)
                if name == key + ":lock" and kwargs.get("nx"): entered.set()
                return result
            monkeypatch.setattr(redis, "set", observed_set)
            pending = asyncio.create_task(request(sessions, actor, projects[0], refresh=True))
            await entered.wait()
            other = await asyncio.wait_for(request(sessions, actor, projects[1]), 1)
            assert other.all == 1
            await redis.set(key, json.dumps({"counts": snapshot.counts, "as_of": time.time()}), ex=60)
            assert (await pending).all == 3
            assert await redis.get(key + ":lock") == b"peer"
    asyncio.run(run())
