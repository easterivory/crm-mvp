"""Real PostgreSQL isolation and concurrency checks for multiple scenarios."""
import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from tests.test_advertising import fixture, enroll, pytestmark
from app.models import Bot, Chat, Lead
from app.models.advertising import AdvertisingConfig, AdvertisingEnrollment, AdvertisingDelivery, AdvertisingSlot
from app.schemas.advertising import AdvertisingSettings, SlotWrite, BackfillRequest
from app.services.advertising_service import AdvertisingService, now
from app.workers.advertising_worker import process_enrollment


def test_two_scenarios_route_and_send_only_their_own_slots():
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            first = await enroll(sessions, chats[0])
            async with sessions() as db:
                service = AdvertisingService(db)
                other = await service.create_scenario(pid, "Second", None)
                sid = other.id
                bot = Bot(project_id=pid, name="Second bot", transport_type="bot_api")
                db.add(bot); await db.flush()
                chat = Chat(project_id=pid, bot_id=bot.id, external_chat_id="555", external_user_id="555")
                db.add(chat); await db.flush()
                lead = Lead(project_id=pid, chat_id=chat.id, status_id=(await db.get(Lead, leads[0])).status_id)
                db.add(lead); await db.flush()
                second = AdvertisingService(db, sid)
                cfg = await service.config(pid)
                await second.save_config(pid, cfg.model_copy(update={"name": "Second", "bot_ids": [bot.id]}), None)
                slot = await second.save_slot(pid, SlotWrite(name="Only second", enabled=True,
                    content_json={"messages": [{"text": "Second content"}]}), None)
                slot_id, chat_id = slot.id, chat.id
                await db.commit()
            second_id = await enroll(sessions, chat_id)
            await process_enrollment(first, sessions)
            await process_enrollment(second_id, sessions)
            sent = []
            async def send(db, chat, delivery):
                sent.append((chat.id, delivery.slot_id))
            await process_enrollment(first, sessions, send)
            await process_enrollment(second_id, sessions, send)
            assert sent == [(chats[0], slots[0]), (chat_id, slot_id)]
            async with sessions() as db:
                assert (await db.get(AdvertisingEnrollment, second_id)).scenario_id == sid
                queue = list((await db.scalars(select(AdvertisingDelivery.slot_id).where(
                    AdvertisingDelivery.enrollment_id == second_id))).all())
                assert queue == [slot_id]
                await AdvertisingService(db).return_to_main(chat_id)
                await AdvertisingService(db).watch_start(chat_id)
                await db.commit()
                assert (await AdvertisingService(db).for_bot(pid, bid)).scope(pid) == pid
                with pytest.raises(HTTPException) as error:
                    await AdvertisingService(db, sid).save_slot(pid, SlotWrite(name="Wrong", revision=1,
                        content_json={"messages": [{"text": "Wrong"}]}), None, slots[0])
                assert error.value.status_code == 404
                with pytest.raises(HTTPException):
                    await AdvertisingService(db, sid).config(uuid4())
    asyncio.run(run())


def test_concurrent_assignment_has_one_winner_even_for_disabled_scenarios():
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            async with sessions() as db:
                service = AdvertisingService(db)
                a = await service.create_scenario(pid, "A", None)
                b = await service.create_scenario(pid, "B", None)
                bot = Bot(project_id=pid, name="New bot", transport_type="bot_api")
                db.add(bot); await db.commit()
                a_id, b_id, bot_id = a.id, b.id, bot.id
            async def assign(sid):
                async with sessions() as db:
                    try:
                        await AdvertisingService(db, sid).save_config(pid,
                            AdvertisingSettings(bot_ids=[bot_id]), None)
                        await db.commit()
                        return 200
                    except HTTPException as exc:
                        await db.rollback()
                        return exc.status_code
            assert sorted(await asyncio.gather(assign(a_id), assign(b_id))) == [200, 409]
    asyncio.run(run())


def test_upgrade_preserves_legacy_slot_and_settings():
    legacy_id = uuid4()
    enrollment_id, delivery_id = uuid4(), uuid4()
    async def before(db, pid):
        await db.execute(text("INSERT INTO advertising_configs (project_id, enabled, settings_json) VALUES (:pid, true, '{\"timeout_minutes\": 123}')"), {"pid": pid})
        await db.execute(text("""INSERT INTO advertising_slots
            (id, project_id, name, position, enabled, delay_minutes, revision, content_json)
            VALUES (:id, :pid, 'Legacy', 4, true, 150, 7, '{"messages":[{"text":"Original"}]}')"""),
            {"id": legacy_id, "pid": pid})
        bot = Bot(project_id=pid, name="Legacy bot", transport_type="bot_api")
        db.add(bot); await db.flush()
        chat = Chat(project_id=pid, bot_id=bot.id, external_chat_id="legacy", external_user_id="legacy")
        db.add(chat); await db.flush()
        await db.execute(text("""INSERT INTO advertising_enrollments
            (id, project_id, chat_id, status, due_at, started_at, source, stop_main)
            VALUES (:id, :pid, :chat, 'active', now(), now(), 'automatic', true)"""),
            {"id": enrollment_id, "pid": pid, "chat": chat.id})
        db.add(AdvertisingDelivery(id=delivery_id, enrollment_id=enrollment_id, slot_id=legacy_id,
            position=0, delay_minutes=150, status="sending", revision=7,
            content_snapshot={"messages": [{"text": "Frozen"}]}))
    async def after(db, pid):
        cfg = await db.get(AdvertisingConfig, pid)
        slot = await db.get(AdvertisingSlot, legacy_id)
        assert cfg.name == "Основной" and cfg.enabled
        assert cfg.settings_json == {"timeout_minutes": 123}
        assert slot.scenario_id == pid and slot.revision == 7 and slot.position == 4
        assert slot.content_json["messages"][0]["text"] == "Original"
        enrollment = await db.get(AdvertisingEnrollment, enrollment_id)
        delivery = await db.get(AdvertisingDelivery, delivery_id)
        assert enrollment.scenario_id == pid and enrollment.status == "active"
        assert delivery.status == "sending" and delivery.revision == 7
        assert delivery.content_snapshot["messages"][0]["text"] == "Frozen"
        # The shared fixture below expects an empty enrollment table.
        await db.delete(delivery); await db.flush()
        await db.delete(enrollment); await db.commit()
    async def run():
        async with fixture(before_scenarios=before, after_scenarios=after):
            pass
    asyncio.run(run())


def test_api_scenario_scope_for_slots_reports_and_backfill():
    import httpx
    from fastapi import FastAPI
    from types import SimpleNamespace
    from app.api.v1.dependencies import get_current_user, get_db
    from app.api.v1.routers.advertising import router
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            eid = await enroll(sessions, chats[0])
            async with sessions() as db:
                other = await AdvertisingService(db).create_scenario(pid, "Other", None)
                sid = str(other.id)
                await db.commit()
            app = FastAPI(); app.include_router(router)
            app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=None, role_name="super_admin", project_id=pid)
            async def dependency():
                async with sessions() as db:
                    yield db
                    await db.commit()
            app.dependency_overrides[get_db] = dependency
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                p = {"project_id": str(pid), "scenario_id": sid}
                assert (await client.get("/advertising/slots", params=p)).json() == []
                assert (await client.get("/advertising/participants", params=p)).json() == []
                assert (await client.get(f"/advertising/participants/{eid}/deliveries", params=p)).status_code == 404
                assert (await client.post(f"/advertising/participants/{eid}/stop", params=p)).status_code == 404
                from datetime import timedelta
                report = await client.get("/advertising/tracking", params={**p,
                    "start": (now() - timedelta(days=1)).isoformat(), "end": now().isoformat()})
                assert report.status_code == 200 and report.json()["cohort_counts"] == {}
                preview = await client.post("/advertising/backfill/preview", params={"project_id": str(pid)},
                    json={"created_before": now().isoformat()})
                assert preview.status_code == 200
                foreign = await client.post("/advertising/backfill/start", params=p,
                    json={"created_before": now().isoformat(), "preview_id": preview.json()["preview_id"], "confirmation": "ЗАПУСТИТЬ"})
                assert foreign.status_code == 404
                assert (await client.get("/advertising/settings", params={**p, "scenario_id": str(uuid4())})).status_code == 404
    asyncio.run(run())
