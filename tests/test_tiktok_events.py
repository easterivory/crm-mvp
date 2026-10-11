"""TikTok payload contracts and persistence against real PostgreSQL; no mocks."""
import asyncio
import hashlib
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.routers.tiktok import TikTokSettings, get_settings, save_settings, deliveries, retry_delivery
from app.core.tiktok_events import default_tiktok_mappings
from app.models import Base, Bot, Chat, Lead, Project, User
from app.models.lead_status import LeadStatus
from app.models.role import Role
from app.models.tag import Tag
from app.models.tiktok import TikTokDelivery, TikTokIntegration
from app.models.tracking import TrackingLink
from app.services.advertising_event_service import AdvertisingEventService
from app.services.ai_credential_service import AICredentialService
from app.services.lead_event_service import LeadEventService
from app.services.tiktok_event_service import TikTokEventService, build_tiktok_payload
from app.services.tiktok_lander import render_tiktok_pixel
from app.services.utm_bridge_service import UtmBridgeService
from app.services.lander_service import LanderService
from app.services.lander_admin_service import LanderAdminService
from app.schemas.lander import ProjectLanderCreate


def test_tiktok_payload_uses_real_click_identity_and_hashes_pii():
    payload = build_tiktok_payload(pixel_id="PIXEL123", event_name="CompleteRegistration", event_id="event", event_time=123,
                                  context={"ttclid": ["old", "click"], "ttp": "cookie", "client_ip_address": "203.0.113.1",
                                           "client_user_agent": "Browser", "event_source_url": "https://landing.example/l/test?ttclid=click"},
                                  external_id="123456", phone="+998 90 123 45 67", properties={"currency": "USD", "value": 10, "secret": "never"})
    assert payload["event_source"] == "web"
    event = payload["data"][0]
    assert event["event_time"] == 123 and event["event_id"] == "event"
    assert event["user"]["ttclid"] == "click" and event["user"]["ttp"] == "cookie"
    assert event["user"]["external_id"] == hashlib.sha256(b"123456").hexdigest()
    assert event["user"]["phone"] == hashlib.sha256(b"998901234567").hexdigest()
    assert event["properties"] == {"currency": "USD", "value": 10}
    assert "test_event_code" not in payload


def test_tiktok_attribution_survives_bridge_and_channel_snapshot():
    context = UtmBridgeService.build_bridge_payload({"ttclid": "ad-click", "utm_source": "tiktok"}, browser_context={"_ttp": "browser"})
    assert context["ttp"] == "browser"
    snapshot = LanderService._attribution_snapshot(context)
    assert snapshot == context
    markup = render_tiktok_pixel("PIXEL123", default_tiktok_mappings(), "/l/test/bridge/start_1234567890", "start_1234567890", uuid4())
    assert "analytics.tiktok.com" in markup and "Access-Token" not in markup
    assert "window.__crmTrackTelegramOpen=function" in markup


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_tiktok_opt_in_atomic_deduplication_rules_permissions_and_delivery_log():
    async def run():
        schema = "tiktok_" + uuid4().hex
        root = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"])
        engine = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"], connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with root.begin() as db:
                await db.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as db:
                await db.run_sync(Base.metadata.create_all)
            async with sessions() as db:
                project, other = Project(name="TikTok", slug="tiktok"), Project(name="Other", slug="other")
                status = LeadStatus(name="New", code="new")
                role = Role(name="admin")
                buyer_role = Role(name="buyer")
                db.add_all([project, other, status, role, buyer_role])
                await db.flush()
                admin = User(project_id=project.id, role=role, name="Admin", email="admin@test.local", password_hash="unused")
                buyer = User(project_id=project.id, role=buyer_role, name="Buyer", email="buyer@test.local", password_hash="unused")
                bot = Bot(project_id=project.id, name="Bot")
                tag = Tag(project_id=project.id, name="Registration")
                db.add_all([admin, buyer, bot, tag])
                await db.flush()
                link = TrackingLink(project_id=project.id, bot_id=bot.id, name="TikTok", title="TikTok", code="tiktok", ref_code="tiktok", fb_campaign_enabled=False)
                db.add(link)
                await db.flush()
                chat = Chat(project_id=project.id, bot_id=bot.id, tracking_link_id=link.id, external_chat_id="12345", external_user_id="12345")
                db.add(chat)
                await db.flush()
                lead = Lead(project_id=project.id, chat_id=chat.id, status_id=status.id, custom_fields={"fb_data": {"ttclid": "click", "ttp": "cookie"}})
                db.add(lead)
                await db.commit()
                service = TikTokEventService(db)
                assert (await get_settings(link.id, project.id, admin, db))["enabled"] is False
                link.buyer_id = buyer.id
                await db.flush()
                with pytest.raises(HTTPException) as exc:
                    await LanderAdminService(db).create_lander(project_id=project.id, actor=buyer,
                        data=ProjectLanderCreate(name="Disabled integration", slug="disabled", type="default_tg_redirect", tracking_link_id=link.id))
                assert exc.value.status_code == 403
                link.buyer_id = None
                await db.flush()
                await AdvertisingEventService(db).enqueue_mapped_event(lead_id=lead.id, source_event="bot_start", event_reference="first")
                assert await db.scalar(select(func.count()).select_from(TikTokDelivery)) == 0
                with pytest.raises(HTTPException) as exc:
                    await save_settings(link.id, TikTokSettings(enabled=True, pixel_id="PIXEL123"), project.id, admin, db)
                assert exc.value.status_code == 422
                cfg = await save_settings(link.id, TikTokSettings(enabled=True, pixel_id="PIXEL123", access_token="token-secret"), project.id, admin, db)
                assert cfg["has_token"] and "token-secret" not in str(cfg)
                config = await db.get(TikTokIntegration, link.id)
                assert config.encrypted_token != "token-secret"
                assert AICredentialService().decrypt(config.encrypted_token) == "token-secret"
                await save_settings(link.id, TikTokSettings(enabled=True, pixel_id="PIXEL123"), project.id, admin, db)
                assert AICredentialService().decrypt(config.encrypted_token) == "token-secret"
                with pytest.raises(HTTPException) as exc:
                    await get_settings(link.id, project.id, buyer, db)
                assert exc.value.status_code == 404
                with pytest.raises(HTTPException):
                    await get_settings(link.id, other.id, admin, db)
                link.buyer_id = buyer.id
                await db.flush()
                page = await LanderAdminService(db).create_lander(project_id=project.id, actor=buyer,
                    data=ProjectLanderCreate(name="TikTok buyer landing", slug="tiktok-buyer", type="default_tg_redirect", tracking_link_id=link.id))
                assert page.tracking_link_id == link.id
                await service.mapped_event(lead_id=lead.id, source_event="bot_start", event_reference="first")
                await service.mapped_event(lead_id=lead.id, source_event="bot_start", event_reference="first")
                assert await db.scalar(select(func.count()).select_from(TikTokDelivery)) == 1
                await db.commit()
                async with sessions() as cancelled:
                    await TikTokEventService(cancelled).browser_event(link_id=link.id, source="page_view", start_key="start_1234567890", context={"ttclid": "browser"})
                    await cancelled.rollback()
                assert await db.scalar(select(func.count()).select_from(TikTokDelivery)) == 1
                lead_id, link_id = lead.id, link.id
                events = LeadEventService(db)
                await events.record_event(lead=lead, event_type="registration", source="manual")
                await events.record_event(lead=lead, event_type="registration", source="funnel")
                assert await db.scalar(select(func.count()).select_from(TikTokDelivery).where(TikTokDelivery.source_event == "registration")) == 1
                await events.record_event(lead=lead, event_type="redeposit", source="manual")
                await events.record_event(lead=lead, event_type="redeposit", source="postback")
                assert await db.scalar(select(func.count()).select_from(TikTokDelivery).where(TikTokDelivery.source_event == "resale")) == 2
                mappings = default_tiktok_mappings()
                registration = next(m for m in mappings if m["source_event"] == "registration")
                registration["triggers"] = [{"type": "lead_tag", "value": str(tag.id)}]
                await save_settings(link_id, TikTokSettings(enabled=True, pixel_id="PIXEL123", mappings=mappings), project.id, admin, db)
                before = await db.scalar(select(func.count()).select_from(TikTokDelivery))
                await service.triggered_event(lead_id=lead_id, trigger_type="lead_tag", trigger_value=uuid4())
                assert await db.scalar(select(func.count()).select_from(TikTokDelivery)) == before
                await service.triggered_event(lead_id=lead_id, trigger_type="lead_tag", trigger_value=tag.id)
                assert await db.scalar(select(func.count()).select_from(TikTokDelivery)) == before
                log = await deliveries(link_id, project.id, admin, db)
                assert log and all("payload_json" not in i and "token" not in i for i in log)
                assert log[0]["has_click_id"]
                item = await db.get(TikTokDelivery, log[0]["id"])
                item.status = "failed"
                await retry_delivery(link_id, item.id, project.id, admin, db)
                assert item.status == "pending"
                await db.commit()
                # Two independent DB transactions cannot insert the same conversion twice.
                async def concurrent_insert():
                    async with sessions() as transaction:
                        await TikTokEventService(transaction).browser_event(link_id=link_id, source="page_view", start_key="same_visit", context={"ttclid": "ad"})
                        await transaction.commit()
                await asyncio.gather(concurrent_insert(), concurrent_insert())
                assert await db.scalar(select(func.count()).select_from(TikTokDelivery).where(TikTokDelivery.source_event == "page_view")) == 1
        finally:
            await engine.dispose()
            async with root.begin() as db:
                await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
