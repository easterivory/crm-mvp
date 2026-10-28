import asyncio
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import *  # noqa: F403
from app.models.base import Base
from app.models.project import Project
from app.models.chat import Chat
from app.models.user import User
from app.models.role import Role
from app.models.scheduled_message import ScheduledMessage
from app.repositories.scheduled_message_repository import ScheduledMessageRepository
from app.workers import scheduled_message_worker as worker


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_interrupted_scheduled_delivery_not_replayed_and_live_worker_protected(monkeypatch):
    async def run():
        schema = "restart_" + uuid4().hex
        url = os.environ["CRM_TEST_POSTGRES_URL"]
        root = create_async_engine(url)
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(worker, "engine", engine)
        monkeypatch.setattr(worker, "get_db_session", sessions)
        entered, release = asyncio.Event(), asyncio.Event()
        try:
            async with root.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with sessions() as db:
                p = Project(name="Restart", slug=schema)
                role = Role(name="manager")
                db.add_all([p, role]); await db.flush()
                user = User(project_id=p.id, role_id=role.id, name="Manager", email="restart@example.test", password_hash="unused")
                chat = Chat(project_id=p.id, external_chat_id="123", external_user_id="123")
                db.add_all([user, chat]); await db.flush()
                rows = [ScheduledMessage(project_id=p.id, chat_id=chat.id, created_by_user_id=user.id,
                    scheduled_at=datetime.now(timezone.utc), text=s, status=s) for s in ["running", "pending", "sent", "failed", "cancelled"]]
                db.add_all(rows); await db.commit()
                ids = {r.status: r.id for r in rows}

            async def process(service, *, limit):
                repo = ScheduledMessageRepository(service.db)
                assert await repo.mark_running(ids["pending"])
                await service.db.commit()
                entered.set()
                await release.wait()
                return 0
            monkeypatch.setattr(worker.ScheduledMessageService, "process_due_messages", process)
            task = asyncio.create_task(worker.run_once())
            await asyncio.wait_for(entered.wait(), 5)
            assert await worker.run_once() == 0
            async with sessions() as db:
                assert (await db.get(ScheduledMessage, ids["pending"])).status == "running"
                assert (await db.get(ScheduledMessage, ids["running"])).status == "failed"
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            async def no_send(service, *, limit):
                assert not await service.repo.list_due(datetime.now(timezone.utc))
                return 0
            monkeypatch.setattr(worker.ScheduledMessageService, "process_due_messages", no_send)
            assert await worker.run_once() == 0
            async with sessions() as db:
                row = await db.get(ScheduledMessage, ids["pending"])
                assert row.status == "failed" and "неизвестен" in row.last_error
                for status in ["sent", "failed", "cancelled"]:
                    assert (await db.get(ScheduledMessage, ids[status])).status == status
        finally:
            await engine.dispose()
            async with root.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())


@pytest.mark.skipif(os.getenv("CRM_TEST_REDIS_REBOOT") != "1", reason="Disposable Docker Redis test opt-in")
@pytest.mark.parametrize("interrupted_conversion", [False, True])
def test_redis_rdb_upgrade_and_abrupt_restart_preserve_queue(interrupted_conversion):
    name = "crm-restart-" + uuid4().hex[:12]
    volume = name + "-data"
    script = Path(__file__).parents[1] / "docker/redis-start.sh"
    def docker(*args, check=True):
        return subprocess.run(["docker", *args], check=check, capture_output=True, text=True).stdout.strip()
    def ready():
        for _ in range(120):
            if docker("exec", name, "redis-cli", "ping", check=False) == "PONG":
                return
            time.sleep(.25)
        raise AssertionError(docker("logs", name))
    try:
        docker("volume", "create", volume)
        docker("run", "-d", "--name", name, "-v", volume + ":/data", "redis:7-alpine")
        ready()
        docker("exec", name, "redis-cli", "RPUSH", "qa:queue", "old-job")
        docker("exec", name, "redis-cli", "SAVE")
        if interrupted_conversion:
            docker("exec", name, "touch", "/data/.crm-aof-converting")
        docker("stop", name)
        docker("rm", name)
        docker("run", "-d", "--name", name, "-v", volume + ":/data", "-v", str(script) + ":/redis-start.sh:ro",
               "redis:7-alpine", "sh", "/redis-start.sh")
        ready()
        assert docker("exec", name, "redis-cli", "LPOP", "qa:queue") == "old-job"
        assert docker("exec", name, "redis-cli", "CONFIG", "GET", "appendonly") == "appendonly\nyes"
        docker("exec", name, "redis-cli", "RPUSH", "qa:queue", "new-job")
        time.sleep(2)
        docker("kill", "--signal", "KILL", name)
        docker("start", name)
        ready()
        assert docker("exec", name, "redis-cli", "LRANGE", "qa:queue", "0", "-1") == "new-job"
        docker("restart", name)
        ready()
        assert docker("exec", name, "redis-cli", "LRANGE", "qa:queue", "0", "-1") == "new-job"
    finally:
        docker("rm", "-f", name, check=False)
        docker("volume", "rm", volume, check=False)
