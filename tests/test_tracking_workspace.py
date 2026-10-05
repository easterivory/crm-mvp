import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models.base import Base
from app.models.project import Project
from app.models.role import Role
from app.models.user import User
from app.models.bot import Bot
from app.models.chat import Chat
from app.models.lead import Lead, LeadTag
from app.models.lead_status import LeadStatus
from app.models.lead_event import LeadEvent
from app.models.tag import Tag
from app.models.partner import PartnerIntegration, LeadSubmission
from app.models.tracking import TrackingLink, TrackingEvent
from app.models.funnel import Funnel, FunnelVersion, FunnelStep, FunnelStepLog
from app.services.tracking_metrics_service import TrackingMetricsService
from app.services.tracking_step_metrics_service import TrackingStepMetricsService
from app.services.tracking_cohort_service import TrackingCohortService


async def seed(db):
    now = datetime.now(timezone.utc)
    project = Project(name="Tracking acceptance", slug="tracking-acceptance", project_format="gambling")
    admin_role, buyer_role = Role(name="admin"), Role(name="buyer")
    db.add_all([project, admin_role, buyer_role]); await db.flush()
    admin = User(name="Tracking admin", email="tracking@test.local", password_hash="disabled", role=admin_role, project_id=project.id)
    buyer = User(name="Buyer A", email="buyer-a@test.local", password_hash="disabled", role=buyer_role, project_id=project.id)
    other = User(name="Buyer B", email="buyer-b@test.local", password_hash="disabled", role=buyer_role, project_id=project.id)
    bot = Bot(name="Acceptance bot", project_id=project.id, bot_username="acceptance_test_bot")
    status = LeadStatus(name="Qualified", code="qualified")
    tag = Tag(name="Нет 18", project_id=project.id)
    db.add_all([admin, buyer, other, bot, status, tag]); await db.flush()
    links = [TrackingLink(project_id=project.id, bot_id=bot.id, buyer_id=u.id, buyer_name=u.name,
        name=f"Campaign {i}", title=f"Campaign {i}", code=f"acceptance-{i}", ref_code=f"acceptance-{i}") for i,u in enumerate([buyer,other])]
    funnel = Funnel(project_id=project.id, bot_id=bot.id, name="Welcome")
    db.add_all([*links, funnel]); await db.flush()
    versions = [FunnelVersion(funnel_id=funnel.id, version_number=i+1, status="published") for i in range(2)]
    db.add_all(versions); await db.flush()
    steps = [FunnelStep(funnel_version_id=v.id, key="name", title="Имя", step_type="message", block_type="message") for v in versions]
    db.add_all(steps); await db.flush()
    leads=[]
    for i in range(6):
        entered = now - timedelta(days=2)
        chat = Chat(project_id=project.id, bot_id=bot.id, tracking_link_id=links[i % 2].id,
            external_chat_id=str(100+i), external_user_id=str(100+i), created_at=entered,
            current_cycle_started_at=entered, reset_at=now if i == 5 else None)
        db.add(chat); await db.flush()
        lead = Lead(project_id=project.id, chat_id=chat.id, name=f"Acceptance {i}", status_id=status.id, created_at=entered)
        db.add(lead); await db.flush(); leads.append(lead)
        db.add(LeadTag(lead_id=lead.id, tag_id=tag.id))
        for v,s in zip(versions,steps):
            db.add(FunnelStepLog(lead_id=lead.id, funnel_id=funnel.id, funnel_version_id=v.id, step_id=s.id,
                step_name=s.title, event_type="entered", created_at=now - timedelta(days=3) if i==4 else now-timedelta(days=1)))
        if i in (0,1):
            for source in ("manual", "postback"):
                db.add(LeadEvent(project_id=project.id, lead_id=lead.id, tracking_link_id=links[i%2].id,
                    event_type="registration", source=source, occurred_at=now-timedelta(days=1)))
        if i==0:
            db.add(LeadEvent(project_id=project.id, lead_id=lead.id, tracking_link_id=links[0].id,
                event_type="deposit", source="manual", occurred_at=now))
    for link in links:
        db.add(TrackingEvent(project_id=project.id, tracking_link_id=link.id, bucket_start=now, clicks=100, created_at=now))
    await db.commit()
    return project, admin, buyer, other, links, steps, tag


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_real_tracking_workspace_scopes_and_reached_steps():
    async def run():
        url = os.environ["CRM_TEST_POSTGRES_URL"]
        schema = "workspace_" + uuid4().hex
        root = create_async_engine(url)
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        try:
            async with root.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                project, admin, buyer, other, links, steps, tag = await seed(db)
                today = datetime.now(timezone.utc).date()
                scope = dict(date_from=today-timedelta(days=6), date_to=today)
                service = TrackingMetricsService(db)
                all_metrics = await service.get_project_metrics(admin, project.id, **scope)
                own_metrics = await service.get_project_metrics(admin, project.id, buyer_id=buyer.id, **scope)
                assert all_metrics.summary.clicks == 200
                assert own_metrics.summary.clicks == 100
                assert len(own_metrics.links) == 1
                assert own_metrics.summary.registrations == 1
                assert own_metrics.summary.first_deposits == 1
                assert (await service.get_project_metrics(buyer, project.id, **scope)).summary == own_metrics.summary
                with pytest.raises(HTTPException) as exc:
                    await service.get_project_metrics(buyer, project.id, buyer_id=other.id, **scope)
                assert exc.value.status_code == 403
                step_service = TrackingStepMetricsService(db)
                options = await step_service.options(admin, project.id)
                assert len(options) == 1 and options[0]["id"] == steps[1].id
                counts = await step_service.get(admin, project.id, steps[1].id, **scope)
                assert counts["total"] == 4  # repeated versions count once; pre-reset history excluded
                assert (await step_service.get(admin, project.id, steps[1].id, buyer_id=buyer.id, **scope))["total"] == 2
                assert (await service.get_tag_metrics(current_user=admin, project_id=project.id, tag_id=tag.id, buyer_id=buyer.id, **scope)).total == 3
                cohort = TrackingCohortService(db)
                result = await cohort.get(admin, project.id, "registrations", "first_deposits", **scope)
                assert result["base"] == 2 and result["converted"] == 1 and result["percent"] == 50
                result = await cohort.get(admin, project.id, f"step:{steps[1].id}", f"tag:{tag.id}", **scope)
                assert result["base"] == 4 and result["percent"] == 100
                result = await cohort.get(admin, project.id, "redeposits", "registrations", **scope)
                assert result["base"] == 0 and result["percent"] is None
                partner = PartnerIntegration(project_id=project.id, name="Acceptance partner",
                    postback_url="https://example.invalid/unused")
                db.add(partner)
                await db.flush()
                lead_id = await db.scalar(select(Lead.id).join(Chat, Chat.id == Lead.chat_id)
                    .where(Chat.tracking_link_id == links[0].id).order_by(Lead.id).limit(1))
                now = datetime.now(timezone.utc)
                db.add_all([LeadSubmission(lead_id=lead_id, partner_integration_id=partner.id,
                    status="success", submitted_at=now-timedelta(hours=hours)) for hours in (24, 1)])
                await db.commit()
                result = await cohort.get(admin, project.id, "arrivals", "submitted_leads", **scope)
                assert result["base"] == 5 and result["converted"] == 1 and result["percent"] == 20
                result = await cohort.get(admin, project.id, "submitted_leads", "arrivals", **scope)
                assert result["base"] == 1 and result["converted"] == 1 and result["percent"] == 100
                with pytest.raises(HTTPException):
                    await cohort.get(buyer, project.id, "arrivals", "registrations", link_id=links[1].id, **scope)
                with pytest.raises(HTTPException):
                    await step_service.get(admin, project.id, uuid4(), **scope)
        finally:
            await engine.dispose()
            async with root.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
