"""Delivery correctness and throughput with real PostgreSQL and simulated Telegram."""
import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models import *  # noqa: F403
from app.models.base import Base
from app.models.project import Project
from app.models.bot import Bot
from app.models.chat import Chat
from app.models.broadcast import Broadcast, BroadcastRecipient
from app.services.broadcast_transport import BroadcastHTTPClient
from app.services.broadcast_service import BroadcastService
from app.workers import broadcast_worker as worker_module


def test_transport_retries_only_explicit_429_and_limits_concurrent_requests():
    async def run():
        calls = []
        async def respond(request):
            calls.append(time.monotonic())
            if len(calls) == 1:
                return httpx.Response(429, json={"parameters": {"retry_after": 1}})
            return httpx.Response(200, json={"ok": True})
        async with BroadcastHTTPClient(rate=20, transport=httpx.MockTransport(respond)) as client:
            await asyncio.gather(*(client.post("https://telegram.test/send", json={}) for _ in range(8)))
        assert len(calls) == 9
        assert calls[1] - calls[0] >= .99
        assert all(b - a >= .045 for a, b in zip(calls, calls[1:]))
        calls.clear()
        async def timeout(request):
            calls.append(1)
            raise httpx.ReadTimeout("unknown delivery outcome")
        async with BroadcastHTTPClient(rate=20, transport=httpx.MockTransport(timeout)) as client:
            with pytest.raises(httpx.ReadTimeout):
                await client.post("https://telegram.test/send", json={})
        assert len(calls) == 1
        calls.clear()
        async def success(request):
            calls.append(time.monotonic())
            return httpx.Response(200, json={"ok": True})
        async with BroadcastHTTPClient(rate=20, transport=httpx.MockTransport(success)) as client:
            await client.post("https://telegram.test/send", json={"chat_id": "same"})
            await client.post("https://telegram.test/send", json={"chat_id": "same"})
        assert calls[1] - calls[0] >= .99
    asyncio.run(run())


def test_media_reuses_bot_file_id_and_preserves_caption(tmp_path):
    async def run():
        upload_id = uuid4()
        path = tmp_path / "photo.jpg"
        path.touch()
        service = BroadcastService.__new__(BroadcastService)
        service.media_cache = {}
        service.repo = SimpleNamespace(get_upload_in_project=AsyncMock(return_value=SimpleNamespace(
            media_type="photo", status="used", expires_at=None, storage_path=str(path),
            file_name="photo.jpg", mime_type="image/jpeg", file_size=0)), mark_upload_used=AsyncMock())
        service._render_text = AsyncMock(side_effect=lambda caption, *a, **k: caption)
        service.telegram_sender = SimpleNamespace(send_photo=AsyncMock(return_value={
            "message_id": 1, "photo": [{"file_id": "telegram-cached-photo"}]}))
        broadcast = SimpleNamespace(project_id=uuid4(), bot_id=uuid4())
        message = {"media": {"upload_id": str(upload_id)}, "caption": "first"}
        args = dict(broadcast=broadcast, chat=SimpleNamespace(external_chat_id="1"), lead=None,
                    message=message, message_type="photo", reply_markup=None)
        await service._send_broadcast_media(**args)
        message["caption"] = "second"
        await service._send_broadcast_media(**args)
        calls = service.telegram_sender.send_photo.call_args_list
        assert calls[0].kwargs["photo"] == path
        assert calls[1].kwargs["photo"] == "telegram-cached-photo"
        assert calls[1].kwargs["caption"] == "second"
    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_delivery_concurrency_restart_pause_errors_and_throughput(monkeypatch):
    async def run():
        schema = "broadcast_" + uuid4().hex
        root = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"])
        engine = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"], pool_size=16,
            connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(worker_module, "engine", engine)
        monkeypatch.setattr(worker_module, "get_db_session", sessions)
        calls = []
        mode = "success"
        entered = asyncio.Event()
        release = asyncio.Event()
        async def telegram(request):
            import json
            payload = json.loads(request.content)
            calls.append(payload["chat_id"])
            entered.set()
            if mode == "hold":
                await release.wait()
            await asyncio.sleep(.3)
            if mode == "forbidden":
                return httpx.Response(403, json={"ok": False, "error_code": 403,
                    "description": "Forbidden: user is deactivated"})
            return httpx.Response(200, json={"ok": True, "result": {"message_id": len(calls)}})
        monkeypatch.setattr(worker_module, "BroadcastHTTPClient", lambda **kwargs:
            BroadcastHTTPClient(**kwargs, transport=httpx.MockTransport(telegram)))
        try:
            async with root.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await conn.execute(text("ALTER TABLE broadcast_recipients DROP CONSTRAINT ck_broadcast_recipients_status"))
                await conn.execute(text("ALTER TABLE broadcast_recipients ADD CONSTRAINT ck_broadcast_recipients_status CHECK (status IN ('pending','sent','failed','skipped'))"))
                spec = importlib.util.spec_from_file_location("broadcast_migration", Path(__file__).parents[1] / "alembic/versions/20261028_0089_broadcast_delivery_claim.py")
                migration = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(migration)
                def migrate(sync_conn, fn):
                    with Operations.context(MigrationContext.configure(sync_conn)):
                        fn()
                await conn.run_sync(lambda c: migrate(c, migration.upgrade))
            async with sessions() as db:
                p = Project(name="Broadcast QA", slug=schema)
                db.add(p); await db.flush()
                bot = Bot(project_id=p.id, name="QA", telegram_token="test-token")
                db.add(bot); await db.flush()
                project_id, bot_id = p.id, bot.id
                await db.commit()
            async def seed(count, sending=False):
                async with sessions() as db:
                    bc = Broadcast(project_id=project_id, bot_id=bot_id, name="QA", status="processing",
                        content_json={"messages": [{"type": "text", "text": "Hello"}]}, total_recipients=count)
                    db.add(bc); await db.flush()
                    for i in range(count):
                        external_id = str(uuid4().int % 10**12)
                        chat = Chat(project_id=project_id, bot_id=bot_id, external_chat_id=external_id, external_user_id=external_id)
                        db.add(chat); await db.flush()
                        db.add(BroadcastRecipient(broadcast_id=bc.id, chat_id=chat.id,
                            status="sending" if sending else "pending"))
                    await db.commit()
                    return bc.id
            async def deliver(bid):
                async with sessions() as db:
                    return await worker_module.BroadcastDeliveryWorker(db).process_broadcast(broadcast_id=bid)

            bid = await seed(300)
            start = time.monotonic()
            result = await deliver(bid)
            elapsed = time.monotonic() - start
            rate = result.sent * 60 / elapsed
            print(f"\nSimulated Telegram 300ms + real DB: {result.sent} sent in {elapsed:.2f}s = {rate:.0f}/min")
            assert result.sent == 300 and result.failed == 0 and result.status == "completed"
            assert len(set(calls)) == len(calls) == 300
            assert rate >= 1000

            calls.clear(); mode = "hold"
            entered.clear()
            bid = await seed(40)
            task = asyncio.create_task(deliver(bid))
            await asyncio.wait_for(entered.wait(), 5)
            assert (await deliver(bid)).status == "busy"
            other = await seed(1)
            assert (await deliver(other)).status == "busy"
            async with sessions() as db:
                await db.execute(update(Broadcast).where(Broadcast.id == bid).values(status="paused"))
                await db.commit()
            release.set()
            result = await task
            assert result.status == "paused" and len(calls) <= 12
            mode = "success"
            async with sessions() as db:
                await db.execute(update(Broadcast).where(Broadcast.id == bid).values(status="processing"))
                await db.commit()
            await deliver(bid)
            assert len(calls) == len(set(calls)) == 40

            calls.clear()
            bid = await seed(3)
            async with sessions() as db:
                now = datetime.now(timezone.utc)
                await db.execute(update(Broadcast).where(Broadcast.id == bid).values(
                    stop_on_reply=True, started_at=now - timedelta(seconds=1)))
                chat_id = await db.scalar(select(BroadcastRecipient.chat_id).where(BroadcastRecipient.broadcast_id == bid).limit(1))
                await db.execute(update(Chat).where(Chat.id == chat_id).values(last_client_message_at=now))
                await db.commit()
            assert (await deliver(bid)).status == "paused"
            assert not calls

            bid = await seed(3)
            async with sessions() as db:
                await db.execute(update(Broadcast).where(Broadcast.id == bid).values(status="cancelled"))
                await db.commit()
            assert (await deliver(bid)).status == "cancelled"
            assert not calls

            calls.clear(); mode = "forbidden"
            bid = await seed(1)
            result = await deliver(bid)
            assert result.failed == 1 and len(calls) == 1
            async with sessions() as db:
                recipient = await db.scalar(select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == bid))
                assert "deactivated" in recipient.last_error and "403" in recipient.last_error
            mode = "success"; calls.clear()
            bid = await seed(1, sending=True)
            result = await deliver(bid)
            assert not calls and result.status == "completed"
            async with sessions() as db:
                recipient = await db.scalar(select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == bid))
                assert recipient.status == "failed" and "unknown" in recipient.last_error
            bid = await seed(1, sending=True)
            async with engine.begin() as conn:
                await conn.run_sync(lambda c: migrate(c, migration.downgrade))
            async with sessions() as db:
                recipient = await db.scalar(select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == bid))
                assert recipient.status == "failed" and "unknown" in recipient.last_error
        finally:
            await engine.dispose()
            async with root.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
