"""Optional real PostgreSQL tests: business commit and lost-response retry."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import importlib.util
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models import Base, Project, Bot, Chat, Lead
from app.models.lead_status import LeadStatus
from app.models.lead_event import LeadEvent
from app.models.postback import PostbackEndpoint, PostbackReceipt, PostbackRelayDelivery
from app.core.config import settings
from app.api.v1.dependencies import get_db
from app.api.v1.routers.postback_relay import router
from app.services.postback_relay_service import RelayEnvelope, deliver
from app.services.postback_endpoint_service import PostbackEndpointService
from postback_gateway.config import Config
from postback_gateway.queue import Queue
from postback_gateway.relay import Relay, headers, DELIVERY_PATH, MANIFEST_PATH

pytestmark = pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
SECRET = "relay-integration-test-" * 3
TOKEN = "q" * 43


@asynccontextmanager
async def fixture():
    schema = "relay_" + uuid4().hex
    root = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"])
    engine = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"], connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with root.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as conn:
            tables = [t for t in Base.metadata.sorted_tables if t.name != "postback_relay_deliveries"]
            await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
            spec = importlib.util.spec_from_file_location("relay_migration", "alembic/versions/20261102_0092_postback_relay.py")
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            def migrate(sync):
                with Operations.context(MigrationContext.configure(sync)):
                    module.upgrade()
            await conn.run_sync(migrate)
        async with sessions() as db:
            project = Project(name="Relay QA", slug="relay-qa")
            db.add(project); await db.flush()
            bot = Bot(project_id=project.id, name="QA", transport_type="bot_api")
            status = LeadStatus(name="New", code="new")
            db.add_all([bot, status]); await db.flush()
            chat = Chat(project_id=project.id, bot_id=bot.id, external_chat_id="123", external_user_id="123")
            db.add(chat); await db.flush()
            lead = Lead(project_id=project.id, chat_id=chat.id, status_id=status.id)
            endpoint = PostbackEndpoint(project_id=project.id, name="QA callback", secret_token=TOKEN,
                event_type="registration", parameter_mapping={"identifier_type": "lead_id", "identifier_param": "lead_id",
                    "external_event_id_param": "event_id"})
            db.add_all([lead, endpoint]); await db.commit()
            pid, lid, eid = project.id, lead.id, endpoint.id
        app = FastAPI(); app.include_router(router)
        async def dependency():
            async with sessions() as db:
                try:
                    yield db
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
        app.dependency_overrides[get_db] = dependency
        yield sessions, app, pid, lid, eid
    finally:
        await engine.dispose()
        async with root.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await root.dispose()


def enable(monkeypatch, pid):
    monkeypatch.setattr(settings, "POSTBACK_RELAY_ENABLED", True)
    monkeypatch.setattr(settings, "POSTBACK_RELAY_SECRET", SECRET)
    monkeypatch.setattr(settings, "POSTBACK_RELAY_PROJECT_IDS", str(pid))


def test_lost_response_concurrent_retry_and_partner_dedup(tmp_path, monkeypatch):
    async def run():
        async with fixture() as (sessions, app, pid, lid, eid):
            enable(monkeypatch, pid)
            cfg = Config(crm_origin="http://crm.test", secret=SECRET, database=str(tmp_path / "queue.sqlite3"), min_free_bytes=0)
            q = Queue(cfg); q.initialize()
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport) as client:
                relay = Relay(cfg, q, client)
                await relay.sync()
                delivery_id = q.enqueue(TOKEN, "POST", {}, {"lead_id": str(lid), "event_id": "partner-1"})
                original = client.post
                async def lost(*args, **kwargs):
                    response = await original(*args, **kwargs)
                    assert response.status_code == 200
                    raise httpx.ReadTimeout("Lost after durable commit")
                client.post = lost
                await relay.send_one()
                assert q.stats()["counts"] == {"pending": 1}
                client.post = original
                with q.connect() as db:
                    db.execute("UPDATE jobs SET due=0")
                    payload = bytes(db.execute("SELECT payload FROM jobs WHERE id=?", (delivery_id,)).fetchone()[0])
                responses = await asyncio.gather(*(client.post(cfg.crm_origin + DELIVERY_PATH, content=payload,
                    headers=headers(SECRET, "POST", DELIVERY_PATH, payload)) for _ in range(3)))
                assert all(r.status_code == 200 for r in responses)
                await relay.send_one()
                assert q.stats()["counts"] == {"done": 1}
                q.enqueue(TOKEN, "POST", {}, {"lead_id": str(lid), "event_id": "partner-1"})
                await relay.send_one()
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(LeadEvent)) == 1
                assert await db.scalar(select(func.count()).select_from(PostbackReceipt)) == 2
                assert await db.scalar(select(func.count()).select_from(PostbackRelayDelivery)) == 2
                assert set((await db.scalars(select(PostbackReceipt.status))).all()) == {"processed", "duplicate"}
                assert (await db.get(Lead, lid)).chat_id is not None
    asyncio.run(run())


def test_atomic_rollback_scope_rotation_and_payload_conflict(tmp_path, monkeypatch):
    async def run():
        async with fixture() as (sessions, app, pid, lid, eid):
            enable(monkeypatch, pid)
            envelope = RelayEnvelope(delivery_id=uuid4(), secret_token=TOKEN, request_method="GET",
                query_payload={"lead_id": str(lid)}, body_payload={})
            body = envelope.model_dump_json().encode()
            async with sessions() as db:
                result = await deliver(db, envelope, body)
                assert result["status"] == "processed"
                await db.rollback()
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(LeadEvent)) == 0
                assert await db.scalar(select(func.count()).select_from(PostbackRelayDelivery)) == 0
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://crm.test") as client:
                async def send(raw):
                    return await client.post(DELIVERY_PATH, content=raw, headers=headers(SECRET, "POST", DELIVERY_PATH, raw))
                monkeypatch.setattr(settings, "POSTBACK_RELAY_PROJECT_IDS", str(uuid4()))
                assert (await send(body)).status_code == 404
                m = await client.get(MANIFEST_PATH, headers=headers(SECRET, "GET", MANIFEST_PATH))
                assert m.json()["token_hashes"] == []
                monkeypatch.setattr(settings, "POSTBACK_RELAY_PROJECT_IDS", str(pid))
                assert (await send(body)).status_code == 200
                changed = envelope.model_copy(update={"body_payload": {"amount": 100}}).model_dump_json().encode()
                assert (await send(changed)).status_code == 409
                async with sessions() as db:
                    (await db.get(PostbackEndpoint, eid)).is_active = False
                    await db.commit()
                # Already committed delivery can be acknowledged after token revocation.
                assert (await send(body)).status_code == 200
                new = envelope.model_copy(update={"delivery_id": uuid4()}).model_dump_json().encode()
                assert (await send(new)).status_code == 404
    asyncio.run(run())


def test_first_delivery_race_without_partner_event_id(monkeypatch):
    async def run():
        async with fixture() as (sessions, app, pid, lid, eid):
            enable(monkeypatch, pid)
            body = RelayEnvelope(delivery_id=uuid4(), secret_token=TOKEN, request_method="POST",
                query_payload={}, body_payload={"lead_id": str(lid)}).model_dump_json().encode()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://crm.test") as client:
                responses = await asyncio.gather(*(client.post(DELIVERY_PATH, content=body,
                    headers=headers(SECRET, "POST", DELIVERY_PATH, body)) for _ in range(4)))
                assert all(r.status_code == 200 for r in responses)
                assert len({r.json()["result"]["event_id"] for r in responses}) == 1
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(LeadEvent)) == 1
                assert await db.scalar(select(func.count()).select_from(PostbackReceipt)) == 1
    asyncio.run(run())
