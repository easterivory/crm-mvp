"""Journey reporting on real PostgreSQL; no transport substitutes."""
import asyncio
import os
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Bot, Chat, Lead, Project, User
from app.models.funnel import ChatFunnelState, Funnel, FunnelVersion, FunnelStep, FunnelStepLog, FunnelScheduledJob
from app.models.lead import LeadTag
from app.models.lead_status import LeadStatus
from app.models.role import Role
from app.models.tag import Tag
from app.models.tracking import TrackingLink
from app.services.tracking_journey_service import TrackingJourneyService
from app.services.funnel_service import FunnelService


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_numbered_journey_cohort_states_scope_and_pagination():
    async def run():
        url = os.environ["CRM_TEST_POSTGRES_URL"]
        schema = "journey_" + uuid4().hex
        root = create_async_engine(url)
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with root.begin() as db:
                await db.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as db:
                await db.run_sync(Base.metadata.create_all)
            async with sessions() as db:
                project = Project(name="Journey", slug="journey")
                other = Project(name="Other", slug="other")
                role = Role(name="super_admin")
                status = LeadStatus(name="New", code="new")
                db.add_all([project, other, role, status]); await db.flush()
                actor = User(name="Admin", email="journey@test.local", password_hash="unused", role=role)
                bot = Bot(project_id=project.id, name="Bot")
                second = Bot(project_id=project.id, name="Second")
                tag = Tag(project_id=project.id, name="Review")
                db.add_all([actor, bot, second, tag]); await db.flush()
                funnel = Funnel(project_id=project.id, bot_id=bot.id, name="Base")
                db.add(funnel); await db.flush()
                versions = [FunnelVersion(funnel_id=funnel.id, version_number=n, status="archived" if n == 1 else "published") for n in (1, 2)]
                db.add_all(versions); await db.flush()
                funnel.current_version_id = versions[1].id
                steps = []
                # Equal coordinates deliberately: numbering must use ID, like the builder.
                for version in versions:
                    batch = [FunnelStep(id=UUID(int=version.version_number * 100 + i), funnel_version_id=version.id,
                        key=key, title="Сообщение" if i else "Старт", step_type="message" if i else "trigger",
                        block_type="message" if i else "start", position_x=0, position_y=0, config_json={})
                        for i, key in enumerate(("start", "ask", "next"))]
                    db.add_all(batch); steps.append(batch)
                link = TrackingLink(project_id=project.id, bot_id=bot.id, name="Source", title="Source", code="source", ref_code="source")
                db.add(link); await db.flush()
                now = datetime.now(timezone.utc)
                acquisition = now - timedelta(days=4)
                chats, leads, states = [], [], []
                for i in range(7):
                    chat = Chat(project_id=project.id, bot_id=second.id if i == 6 else bot.id,
                        tracking_link_id=None if i == 6 else link.id, external_chat_id=str(i), external_user_id=str(i),
                        reset_at=now if i == 5 else None)
                    db.add(chat); await db.flush()
                    lead = Lead(project_id=project.id, chat_id=chat.id, status_id=status.id, name=f"Lead {i}", created_at=acquisition)
                    db.add(lead); await db.flush()
                    current = steps[1][2] if i == 0 else steps[1][1]
                    state = ChatFunnelState(chat_id=chat.id, funnel_id=funnel.id, funnel_version_id=versions[1].id,
                        current_step_id=current.id, entered_step_at=now - timedelta(hours=48),
                        waiting_for_answer=True, is_paused=i == 2)
                    db.add(state); await db.flush()
                    chats.append(chat); leads.append(lead); states.append(state)
                    db.add(FunnelStepLog(lead_id=lead.id, funnel_id=funnel.id, funnel_version_id=versions[0].id,
                        step_id=steps[0][1].id, step_name="Сообщение", event_type="entered", created_at=acquisition + timedelta(hours=1)))
                    if i == 0:
                        db.add(FunnelStepLog(lead_id=lead.id, funnel_id=funnel.id, funnel_version_id=versions[1].id,
                            step_id=current.id, step_name="Сообщение", event_type="entered", created_at=acquisition + timedelta(hours=1)))
                # Repeat entries must not count the same lead twice; pending jobs are not stalled replies.
                db.add(FunnelStepLog(lead_id=leads[1].id, funnel_id=funnel.id, funnel_version_id=versions[1].id,
                    step_id=steps[1][1].id, step_name="Сообщение", event_type="entered", created_at=acquisition + timedelta(hours=3)))
                db.add(FunnelScheduledJob(chat_id=chats[3].id, funnel_state_id=states[3].id,
                    funnel_id=funnel.id, funnel_version_id=versions[1].id, step_id=steps[1][1].id,
                    job_type="send_message", run_at=now + timedelta(hours=1), status="pending"))
                db.add(FunnelScheduledJob(chat_id=chats[1].id, funnel_state_id=states[1].id,
                    funnel_id=funnel.id, funnel_version_id=versions[1].id, step_id=steps[1][1].id,
                    job_type="input_timeout", run_at=now + timedelta(hours=1), status="pending"))
                chats[4].current_cycle_started_at = now
                db.add(LeadTag(lead_id=leads[1].id, tag_id=tag.id))
                await db.commit()
                service = TrackingJourneyService(db)
                options = await service.steps.options(actor, project.id)
                assert [option["number"] for option in options] == [1, 2, 3]
                assert "v2 · #2 · Сообщение" in options[1]["name"]
                chat_options = await FunnelService(db).list_current_step_options(project_id=project.id, current_user=actor)
                assert [option.number for option in chat_options] == [2, 3]
                filters = dict(bot_id=bot.id, link_id=link.id, date_from=acquisition.date(), date_to=now.date())
                report = await service.report(actor, project.id, funnel.id, **filters)
                ask = report["items"][1]
                assert (ask["reached"], ask["continued"], ask["current"], ask["waiting"], ask["delayed"], ask["manual"], ask["stalled"]) == (4, 1, 3, 1, 1, 1, 1)
                assert ask["conversion"] == 25
                people = await service.chats(actor, project.id, funnel.id, steps[1][1].id, bucket="stalled", limit=1, **filters)
                assert people["total"] == 1
                assert people["items"][0]["tags"] == ["Review"]
                assert people["items"][0]["link_code"] == "source"
                page = await service.chats(actor, project.id, funnel.id, steps[1][1].id, bucket="reached", limit=1, offset=1, **filters)
                assert page["total"] == 4 and len(page["items"]) == 1
                chats[1].last_client_message_at = now
                await db.flush()
                refreshed = await service.report(actor, project.id, funnel.id, **filters)
                assert refreshed["items"][1]["waiting"] == 1
                assert refreshed["items"][1]["stalled"] == 0
                states[1].completed_at = now
                await db.flush()
                completed = await service.report(actor, project.id, funnel.id, **filters)
                assert completed["items"][1]["continued"] == 2
                assert completed["items"][1]["current"] == 2
                buyer_role = Role(name="buyer")
                db.add(buyer_role); await db.flush()
                buyer = User(name="Buyer", email="buyer@test.local", password_hash="unused",
                    project_id=project.id, role=buyer_role)
                db.add(buyer); await db.flush()
                with pytest.raises(HTTPException) as forbidden:
                    await service.report(buyer, project.id, funnel.id, **filters)
                assert forbidden.value.status_code == 404
                link.buyer_id = buyer.id
                await db.flush()
                assert (await service.report(buyer, project.id, funnel.id, **filters))["items"][1]["reached"] == 4
                with pytest.raises(HTTPException) as forbidden:
                    await service.report(buyer, project.id, funnel.id, buyer_id=uuid4(), **filters)
                assert forbidden.value.status_code == 403
                with pytest.raises(HTTPException):
                    await service.report(actor, other.id, funnel.id, **filters)
                with pytest.raises(HTTPException):
                    await service.report(actor, project.id, funnel.id, buyer_id=uuid4(), **filters)
        finally:
            await engine.dispose()
            async with root.begin() as db:
                await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
