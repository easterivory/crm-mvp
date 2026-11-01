import asyncio
import importlib.util
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models import Base, Project, Bot, Chat, Lead
from app.models.lead import LeadTag
from app.models.tag import Tag
from app.models.lead_status import LeadStatus
from app.models.advertising import AdvertisingConfig, AdvertisingSlot, AdvertisingEnrollment, AdvertisingDelivery
from app.models.funnel import Funnel, FunnelVersion, FunnelStep, ChatFunnelState, FunnelScheduledJob
from app.schemas.advertising import AdvertisingSettings, SlotWrite
from app.services.advertising_service import AdvertisingService, now
from app.services.advertising_backfill import eligible_chats
from app.workers.advertising_worker import process_enrollment

pytestmark = pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")


@asynccontextmanager
async def fixture():
    schema = "ad_" + uuid4().hex
    root = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"])
    engine = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"], connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with root.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as conn:
            tables = [t for t in Base.metadata.sorted_tables if not t.name.startswith("advertising_")]
            await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
        async with sessions() as db:
            p = Project(name="Advertising QA", slug="qa")
            db.add(p); await db.commit()
            pid = p.id
        spec = importlib.util.spec_from_file_location("migration_ad", "alembic/versions/20261030_0090_advertising.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        async with engine.begin() as conn:
            def upgrade(sync):
                with Operations.context(MigrationContext.configure(sync)):
                    module.upgrade()
            await conn.run_sync(upgrade)
        async with sessions() as db:
            assert (await db.get(Project, pid)).name == "Advertising QA"
            assert await db.scalar(select(func.count()).select_from(AdvertisingEnrollment)) == 0
            assert not (await AdvertisingService(db).config(pid)).enabled
            bot = Bot(project_id=pid, name="Bot", transport_type="bot_api")
            status = LeadStatus(name="New", code="new")
            audience, hot = Tag(project_id=pid, name="Advertising"), Tag(project_id=pid, name="HOT HOT")
            db.add_all([bot, status, audience, hot]); await db.flush()
            chats = [Chat(project_id=pid, bot_id=bot.id, external_chat_id=str(i), external_user_id=str(i)) for i in range(4)]
            db.add_all(chats); await db.flush()
            leads = [Lead(project_id=pid, chat_id=c.id, status_id=status.id) for c in chats]
            db.add_all(leads); await db.flush()
            service = AdvertisingService(db)
            await service.save_config(pid, AdvertisingSettings(enabled=True, bot_ids=[bot.id],
                audience_tag_id=audience.id, protected_tag_ids=[hot.id]), None)
            slots = []
            for i in range(3):
                slots.append(await service.save_slot(pid, SlotWrite(name=f"Slot {i}", enabled=True, position=i,
                    content_json={"messages": [{"type": "text", "text": f"Post {i}"}]}), None))
            await db.commit()
            yield sessions, pid, bot.id, [c.id for c in chats], [s.id for s in slots], [l.id for l in leads], hot.id
    finally:
        await engine.dispose()
        async with root.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await root.dispose()


async def enroll(sessions, chat_id):
    async with sessions() as db:
        service = AdvertisingService(db)
        await service.watch_start(chat_id)
        await service.watch_start(chat_id)
        e = await db.scalar(select(AdvertisingEnrollment).where(AdvertisingEnrollment.chat_id == chat_id,
            AdvertisingEnrollment.status != "returned"))
        assert e.due_at > now() + timedelta(minutes=179)
        e.due_at = now() - timedelta(seconds=1)
        await db.commit()
        return e.id


async def due(sessions, eid):
    async with sessions() as db:
        e = await db.get(AdvertisingEnrollment, eid)
        e.due_at = now() - timedelta(seconds=1)
        await db.commit()


def test_migration_queue_snapshot_edits_completion_and_restart():
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            eid = await enroll(sessions, chats[0])
            await process_enrollment(eid, sessions)
            sent = []
            async def sender(db, chat, delivery):
                sent.append(delivery.content_snapshot["messages"][0]["text"])
            await process_enrollment(eid, sessions, sender)
            async with sessions() as db:
                service = AdvertisingService(db)
                slot = await db.get(AdvertisingSlot, slots[1])
                await service.save_slot(pid, SlotWrite(name=slot.name, position=slot.position, enabled=True,
                    revision=slot.revision, content_json={"messages": [{"text": "Changed before send"}]}), None, slot.id)
                await service.save_slot(pid, SlotWrite(name="Extra", enabled=True, position=3,
                    content_json={"messages": [{"text": "Must not join old queue"}]}), None)
                first = await db.get(AdvertisingSlot, slots[0]); first.content_json = {"messages": [{"text": "Too late"}]}
                await db.commit()
            for _ in range(2):
                await due(sessions, eid); await process_enrollment(eid, sessions, sender)
            assert sent == ["Post 0", "Changed before send", "Post 2"]
            await process_enrollment(eid, sessions, sender)
            async with sessions() as db:
                e = await db.get(AdvertisingEnrollment, eid)
                assert e.status == "completed" and e.due_at is None
                assert await AdvertisingService(db).owns_chat(chats[0])
                deliveries = list((await db.scalars(select(AdvertisingDelivery).where(AdvertisingDelivery.enrollment_id == eid))).all())
                assert len(deliveries) == 3 and all(d.status == "sent" for d in deliveries)
                await AdvertisingService(db).return_to_main(chats[0])
                assert not await AdvertisingService(db).owns_chat(chats[0])
                await AdvertisingService(db).watch_start(chats[0]); await db.commit()
                assert await db.scalar(select(func.count()).select_from(AdvertisingEnrollment)) == 2
    asyncio.run(run())


@pytest.mark.parametrize("reason", ["protected_tag", "target_lead", "blocked", "disabled", "bot_removed"])
def test_protection_before_transition_and_each_send(reason):
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            eid = await enroll(sessions, chats[0])
            await process_enrollment(eid, sessions)
            async with sessions() as db:
                if reason == "protected_tag":
                    db.add(LeadTag(lead_id=leads[0], tag_id=hot))
                elif reason == "target_lead":
                    p = await db.get(Project, pid); p.tracking_lead_count_mode = "tags"; p.tracking_lead_tag_ids = [str(hot)]
                    c = await db.get(AdvertisingConfig, pid); c.settings_json = {**c.settings_json, "protected_tag_ids": []}
                    db.add(LeadTag(lead_id=leads[0], tag_id=hot))
                elif reason == "blocked":
                    (await db.get(Chat, chats[0])).is_blocked_by_user = True
                elif reason == "bot_removed":
                    config = await db.get(AdvertisingConfig, pid)
                    config.settings_json = {**config.settings_json, "bot_ids": []}
                else:
                    (await db.get(AdvertisingConfig, pid)).enabled = False
                await db.commit()
            sender = AsyncMock()
            await process_enrollment(eid, sessions, sender)
            sender.assert_not_called()
            if reason == "bot_removed":
                async with sessions() as db:
                    row = await db.get(AdvertisingEnrollment, eid)
                    assert row.status == "stopped" and row.due_at is None
    asyncio.run(run())


def test_crash_does_not_repeat_ambiguous_delivery():
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            eid = await enroll(sessions, chats[0]); await process_enrollment(eid, sessions)
            sender = AsyncMock(side_effect=TimeoutError("Telegram response lost"))
            await process_enrollment(eid, sessions, sender)
            await process_enrollment(eid, sessions, sender)
            assert sender.await_count == 1
            async with sessions() as db:
                delivery = await db.scalar(select(AdvertisingDelivery).where(AdvertisingDelivery.enrollment_id == eid,
                    AdvertisingDelivery.position == 0))
                assert delivery.status == "uncertain"
                assert (await db.get(AdvertisingEnrollment, eid)).due_at > now()
    asyncio.run(run())


def test_transition_cancels_main_jobs_without_deleting_history():
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            async with sessions() as db:
                f = Funnel(project_id=pid, bot_id=bid, name="Main"); db.add(f); await db.flush()
                v = FunnelVersion(funnel_id=f.id, version_number=1, status="published"); db.add(v); await db.flush()
                step = FunnelStep(funnel_version_id=v.id, key="age", title="Age", step_type="input", block_type="generic_input", config_json={})
                db.add(step); await db.flush()
                state = ChatFunnelState(chat_id=chats[0], funnel_id=f.id, funnel_version_id=v.id,
                    current_step_id=step.id, entered_step_at=now(), waiting_for_answer=True)
                db.add(state); await db.flush()
                job = FunnelScheduledJob(chat_id=chats[0], funnel_state_id=state.id, funnel_id=f.id,
                    funnel_version_id=v.id, step_id=step.id, job_type="resume_step", run_at=now(), status="pending")
                db.add(job); await db.commit(); sid, jid = state.id, job.id
            eid = await enroll(sessions, chats[0]); await process_enrollment(eid, sessions)
            async with sessions() as db:
                assert (await db.get(FunnelScheduledJob, jid)).status == "cancelled"
                state = await db.get(ChatFunnelState, sid)
                assert state.is_paused and state.runtime_json["advertising_enrollment_id"] == str(eid)
                assert await db.get(Lead, leads[0]) is not None
    asyncio.run(run())


def test_backfill_exclusions_and_concurrent_edit_conflict():
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            async with sessions() as db:
                db.add(LeadTag(lead_id=leads[1], tag_id=hot)); await db.flush()
                service = AdvertisingService(db); cfg = await service.config(pid)
                stmt = await eligible_chats(db, pid, cfg, now())
                ids = list((await db.scalars(stmt)).all())
                assert chats[1] not in ids and chats[0] in ids
                slot = await db.get(AdvertisingSlot, slots[0])
                with pytest.raises(HTTPException) as error:
                    await service.save_slot(pid, SlotWrite(name="Stale", revision=slot.revision - 1,
                        content_json={"messages": [{"text": "Wrong"}]}), None, slot.id)
                assert error.value.status_code == 409
    asyncio.run(run())


def test_empty_slots_do_not_cut_off_main_and_disabled_slot_is_skipped():
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            eid = await enroll(sessions, chats[0])
            async with sessions() as db:
                for sid in slots:
                    (await db.get(AdvertisingSlot, sid)).enabled = False
                await db.commit()
            await process_enrollment(eid, sessions)
            async with sessions() as db:
                row = await db.get(AdvertisingEnrollment, eid)
                assert row.status == "waiting" and row.started_at is None
                assert row.reason == "no_active_slots"
                assert not await AdvertisingService(db).owns_chat(chats[0])
                for sid in slots:
                    (await db.get(AdvertisingSlot, sid)).enabled = True
                await db.commit()
            await due(sessions, eid); await process_enrollment(eid, sessions)
            async with sessions() as db:
                (await db.get(AdvertisingSlot, slots[0])).enabled = False
                await db.commit()
            sender = AsyncMock()
            await process_enrollment(eid, sessions, sender)
            sender.assert_not_called()
            async with sessions() as db:
                assert await db.scalar(select(AdvertisingDelivery.status).where(
                    AdvertisingDelivery.enrollment_id == eid, AdvertisingDelivery.position == 0)) == "skipped"
    asyncio.run(run())


def test_definitive_rejection_is_not_replayed_and_stops_unreachable_chat():
    from app.services.telegram_sender import TelegramDeliveryError
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            eid = await enroll(sessions, chats[0]); await process_enrollment(eid, sessions)
            sender = AsyncMock(side_effect=TelegramDeliveryError(method="sendMessage",
                error_code=403, status_code=403, description="Forbidden: user is deactivated"))
            await process_enrollment(eid, sessions, sender)
            await process_enrollment(eid, sessions, sender)
            assert sender.await_count == 1
            async with sessions() as db:
                assert (await db.get(AdvertisingEnrollment, eid)).status == "stopped"
                statuses = list((await db.scalars(select(AdvertisingDelivery.status).where(
                    AdvertisingDelivery.enrollment_id == eid).order_by(AdvertisingDelivery.position))).all())
                assert statuses == ["failed", "cancelled", "cancelled"]
    asyncio.run(run())


def test_confirmed_backfill_rechecks_tags_and_never_sends_in_mark_only_mode():
    from types import SimpleNamespace
    from app.schemas.advertising import BackfillRequest
    from app.api.v1.routers.advertising import backfill_preview, backfill_start, tracking, participants
    from app.services.advertising_backfill import process_backfill
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            actor = SimpleNamespace(id=None)
            data = BackfillRequest(created_before=now(), stop_main=False, start_slots=False)
            async with sessions() as db:
                preview = await backfill_preview(data, pid, actor, db)
                assert preview["count"] == 4
                assert await db.scalar(select(func.count()).select_from(AdvertisingEnrollment)) == 0
                data.preview_id = preview["preview_id"]
                with pytest.raises(HTTPException) as error:
                    await backfill_start(data, pid, actor, db)
                assert error.value.status_code == 409
                data.confirmation = "ЗАПУСТИТЬ"
                await backfill_start(data, pid, actor, db)
                await backfill_start(data, pid, actor, db)
                db.add(LeadTag(lead_id=leads[0], tag_id=hot))
                await db.commit()
            async with sessions() as db:
                await process_backfill(db); await db.commit()
                await process_backfill(db); await db.commit()
                rows = list((await db.scalars(select(AdvertisingEnrollment))).all())
                assert len(rows) == 3 and all(r.status == "completed" and not r.stop_main for r in rows)
                assert await db.scalar(select(func.count()).select_from(AdvertisingDelivery)) == 0
                report = await tracking(now() - timedelta(days=1), now(), None, pid, actor, db)
                assert report["cohort_counts"] == {"completed": 3}
                assert len(await participants(50, 0, pid, actor, db)) == 3
    asyncio.run(run())


def test_management_bot_access_and_revision_conflict():
    from types import SimpleNamespace
    from app.services.advertising_bot import AdvertisingBotService
    import copy
    class State:
        value = {}
        async def get(self, chat): return copy.deepcopy(self.value)
        async def set(self, chat, value): self.value = copy.deepcopy(value)
        async def clear(self, chat): self.value = {}
    def update(data):
        return {"callback_query": {"from": {"id": 7}, "data": data,
            "message": {"chat": {"id": 7, "type": "private"}}}}
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            async with sessions() as db:
                state = State(); service = AdvertisingBotService(db, state)
                service.authorized_user = AsyncMock(return_value=None)
                _, messages = await service.handle_update(update(f"ad:slot:{slots[0]}"))
                assert "суперадминистраторам" in messages[0]["text"] and not state.value
                service.authorized_user = AsyncMock(return_value=SimpleNamespace(id=None))
                await service.handle_update(update(f"ad:slot:{slots[0]}"))
                assert state.value["draft"]["revision"] == 1
                slot = await db.get(AdvertisingSlot, slots[0]); slot.revision = 2
                await db.flush()
                _, messages = await service.handle_update(update("ad:save"))
                assert "уже изменён" in messages[0]["text"]
                assert slot.revision == 2
    asyncio.run(run())


@pytest.mark.parametrize("change", ["disabled", "target_status", "returned", "protected_tag", "slot_disabled"])
def test_changes_committed_between_claim_and_send_are_rechecked(change):
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            eid = await enroll(sessions, chats[0]); await process_enrollment(eid, sessions)
            @asynccontextmanager
            async def racing_session():
                async with sessions() as db:
                    commit = db.commit
                    changed = False
                    async def intercept_commit():
                        nonlocal changed
                        await commit()
                        if changed: return
                        changed = True
                        async with sessions() as other:
                            if change == "disabled":
                                (await other.get(AdvertisingConfig, pid)).enabled = False
                            elif change == "target_status":
                                target = LeadStatus(name="Qualified", code="qualified"); other.add(target)
                                await other.flush()
                                project = await other.get(Project, pid)
                                project.tracking_lead_count_mode = "statuses"
                                project.tracking_lead_status_codes = ["qualified"]
                                (await other.get(Lead, leads[0])).status_id = target.id
                            elif change == "returned":
                                await AdvertisingService(other).return_to_main(chats[0])
                            elif change == "slot_disabled":
                                (await other.get(AdvertisingSlot, slots[0])).enabled = False
                            else:
                                other.add(LeadTag(lead_id=leads[0], tag_id=hot))
                            await other.commit()
                    db.commit = intercept_commit
                    yield db
            sender = AsyncMock()
            await process_enrollment(eid, racing_session, sender)
            sender.assert_not_called()
    asyncio.run(run())


def test_rate_limit_defers_same_slot_without_consuming_it():
    from app.services.telegram_sender import TelegramDeliveryError
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            eid = await enroll(sessions, chats[0]); await process_enrollment(eid, sessions)
            sender = AsyncMock(side_effect=TelegramDeliveryError(method="sendMessage", error_code=429,
                status_code=429, retry_after=90, transient=True, description="Too Many Requests"))
            await process_enrollment(eid, sessions, sender)
            async with sessions() as db:
                row = await db.get(AdvertisingEnrollment, eid)
                assert row.status == "active" and row.due_at > now() + timedelta(seconds=80)
                assert await db.scalar(select(AdvertisingDelivery.status).where(
                    AdvertisingDelivery.enrollment_id == eid, AdvertisingDelivery.position == 0)) == "pending"
            sender = AsyncMock()
            await process_enrollment(eid, sessions, sender); sender.assert_not_called()
            await due(sessions, eid); await process_enrollment(eid, sessions, sender)
            sender.assert_awaited_once()
    asyncio.run(run())


def test_concurrent_workers_send_once_and_commands_cannot_escape_advertising():
    from app.services.funnel_runtime_service import FunnelRuntimeService
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            eid = await enroll(sessions, chats[0]); await process_enrollment(eid, sessions)
            async def send(db, chat, delivery):
                await asyncio.sleep(0.1)
            sender = AsyncMock(side_effect=send)
            await asyncio.gather(process_enrollment(eid, sessions, sender), process_enrollment(eid, sessions, sender))
            assert sender.await_count <= 1
            async with sessions() as db:
                runtime = FunnelRuntimeService(db)
                assert await runtime.start_funnel_for_chat(chat_id=chats[0], funnel_id=uuid4(), funnel_version_id=uuid4()) is None
                assert await runtime.execute_custom_command_for_chat(chat_id=chats[0], funnel_id=uuid4(),
                    funnel_version_id=uuid4(), command="help") is None
                await AdvertisingService(db).return_to_main(chats[0], reason="administrator_reset")
                await AdvertisingService(db).watch_start(chats[0]); await db.commit()
                assert await db.scalar(select(func.count()).select_from(AdvertisingEnrollment).where(
                    AdvertisingEnrollment.chat_id == chats[0], AdvertisingEnrollment.status == "waiting")) == 1
    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_CONTAINER"), reason="Disposable Docker PostgreSQL required")
def test_backup_restore_preserves_existing_cards_and_advertising_queue():
    import subprocess
    async def run():
        container = os.environ["CRM_TEST_POSTGRES_CONTAINER"]
        restored = "restore_" + uuid4().hex
        def command(*args, input=None):
            return subprocess.run(["docker", "exec", "-i", container, *args], input=input,
                check=True, capture_output=True).stdout
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            eid = await enroll(sessions, chats[0]); await process_enrollment(eid, sessions)
            async with sessions() as db:
                schema = await db.scalar(text("SELECT current_schema()"))
            dump = await asyncio.to_thread(command, "pg_dump", "-U", "postgres", "-d", "crm_test", "-n", schema, "-Fc")
            await asyncio.to_thread(command, "createdb", "-U", "postgres", restored)
            engine = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"].rsplit("/", 1)[0] + "/" + restored,
                connect_args={"server_settings": {"search_path": schema}})
            try:
                await asyncio.to_thread(command, "pg_restore", "-U", "postgres", "-d", restored, "--exit-on-error", input=dump)
                async with async_sessionmaker(engine)() as db:
                    assert await db.scalar(select(func.count()).select_from(Chat)) == 4
                    assert await db.scalar(select(func.count()).select_from(Lead)) == 4
                    assert (await db.get(Project, pid)).name == "Advertising QA"
                    assert (await db.get(AdvertisingEnrollment, eid)).status == "active"
                    assert await db.scalar(select(func.count()).select_from(AdvertisingDelivery)) == 3
                    assert (await db.get(AdvertisingSlot, slots[0])).content_json["messages"][0]["text"] == "Post 0"
            finally:
                await engine.dispose()
                await asyncio.to_thread(command, "dropdb", "-U", "postgres", restored)
    asyncio.run(run())


def test_api_permissions_and_cross_project_slot_are_enforced():
    import httpx
    from fastapi import FastAPI
    from types import SimpleNamespace
    from app.api.v1.dependencies import get_current_user, get_db
    from app.api.v1.routers.advertising import router
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            app = FastAPI(); app.include_router(router)
            actor = SimpleNamespace(id=None, role_name="manager", project_id=pid)
            app.dependency_overrides[get_current_user] = lambda: actor
            async def dependency():
                async with sessions() as db:
                    try:
                        yield db
                        await db.commit()
                    except Exception:
                        await db.rollback()
                        raise
            app.dependency_overrides[get_db] = dependency
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                assert (await client.get("/advertising/settings")).status_code == 403
                actor.role_name = "admin"
                assert (await client.get("/advertising/settings")).status_code == 200
                assert (await client.get("/advertising/bot")).status_code == 403
                assert (await client.get("/advertising/slots", params={"project_id": str(uuid4())})).status_code == 403
                actor.role_name = "super_admin"
                response = await client.put(f"/advertising/slots/{slots[0]}", params={"project_id": str(uuid4())},
                    json={"name": "Wrong project", "revision": 1, "content_json": {"messages": [{"text": "Wrong"}]}})
                assert response.status_code == 404
            async with sessions() as db:
                assert (await db.get(AdvertisingSlot, slots[0])).name == "Slot 0"
    asyncio.run(run())


def test_failed_migration_rolls_back_new_tables_and_preserves_existing_data():
    from unittest.mock import patch
    from sqlalchemy import inspect
    async def run():
        schema = "ad_rollback_" + uuid4().hex
        root = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"])
        engine = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"],
            connect_args={"server_settings": {"search_path": schema}})
        try:
            async with root.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as conn:
                tables = [t for t in Base.metadata.sorted_tables if not t.name.startswith("advertising_")]
                await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
            async with async_sessionmaker(engine)() as db:
                project = Project(name="Must survive rollback", slug="rollback")
                db.add(project); await db.flush(); pid = project.id; await db.commit()
            spec = importlib.util.spec_from_file_location("ad_rollback_migration", "alembic/versions/20261030_0090_advertising.py")
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            with pytest.raises(RuntimeError, match="injected migration failure"):
                async with engine.begin() as conn:
                    def upgrade(sync):
                        create = Operations.create_table
                        def failing_create(self, name, *args, **kwargs):
                            if name == "advertising_deliveries":
                                raise RuntimeError("injected migration failure")
                            return create(self, name, *args, **kwargs)
                        with Operations.context(MigrationContext.configure(sync)), patch.object(Operations, "create_table", failing_create):
                            module.upgrade()
                    await conn.run_sync(upgrade)
            async with engine.connect() as conn:
                names = await conn.run_sync(lambda sync: inspect(sync).get_table_names())
                assert not any(name.startswith("advertising_") for name in names)
                assert await conn.scalar(select(Project.name).where(Project.id == pid)) == "Must survive rollback"
        finally:
            await engine.dispose()
            async with root.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
