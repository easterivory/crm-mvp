"""Real PostgreSQL: migration/trigger, person identity, cohort and ordered stages."""
import asyncio
import importlib.util
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Bot, Chat, Lead, Message, Project, User
from app.models.funnel import ChatFunnelState, Funnel, FunnelScheduledJob, FunnelStep, FunnelStepLog, FunnelVersion
from app.models.channel_tracking import TelegramChannel, TelegramChannelSubscriptionEvent
from app.models.lead import LeadTag
from app.models.lead_status import LeadStatus
from app.models.role import Role
from app.models.tag import Tag
from app.models.tracking import TrackingLink
from app.models.tracking_journey import LeadTagHistory, TrackingJourneyConfig
from app.repositories.tag_repository import TagRepository
from app.schemas.tracking_journey import JourneyConfig
from app.services.tracking_stage_journey_service import TrackingStageJourneyService


def make_config(step_keys, tag_id):
    return JourneyConfig(stages=[
        {"id": uuid4(), "name": "Старт", "source": "start"},
        {"id": uuid4(), "name": "Возраст", "source": "answered", "step_keys": [step_keys[0]]},
        {"id": uuid4(), "name": "Предложение", "source": "entered", "step_keys": [step_keys[1]], "role": "offer"},
        {"id": uuid4(), "name": "VIP", "source": "tag", "tag_ids": [tag_id], "role": "outcome"}])


def test_stage_config_requires_tag_outcome_unique_ids_and_valid_sources():
    config = make_config(["age", "offer"], uuid4())
    data = config.model_dump()
    data["stages"][-1]["source"] = "entered"
    with pytest.raises(ValidationError):
        JourneyConfig.model_validate(data)
    data = config.model_dump()
    data["stages"][1]["id"] = data["stages"][0]["id"]
    with pytest.raises(ValidationError):
        JourneyConfig.model_validate(data)
    data = config.model_dump()
    data["stages"][1]["step_keys"] = []
    with pytest.raises(ValidationError):
        JourneyConfig.model_validate(data)


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_stage_journey_real_database_and_migration():
    async def run():
        url = os.environ["CRM_TEST_POSTGRES_URL"]
        schema = "stages_" + uuid4().hex
        root = create_async_engine(url)
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        path = Path(__file__).parents[1] / "alembic/versions/20261012_0084_tracking_journey_stages.py"
        spec = importlib.util.spec_from_file_location("stage_migration", path)
        migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
        def migrate(conn, direction):
            with Operations.context(MigrationContext.configure(conn)):
                getattr(migration, direction)()
        try:
            async with root.begin() as db:
                await db.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as db:
                await db.run_sync(Base.metadata.create_all)
                # Copy of the previous head schema, including existing tag data.
                await db.run_sync(TrackingJourneyConfig.__table__.drop)
                await db.run_sync(LeadTagHistory.__table__.drop)
            async with sessions() as db:
                project = Project(name="Vacancies", slug="stage-test")
                other = Project(name="Gambling", slug="other-stage-test")
                admin_role = Role(name="super_admin"); buyer_role = Role(name="buyer")
                status = LeadStatus(name="New", code="new")
                db.add_all([project, other, admin_role, buyer_role, status]); await db.flush()
                actor = User(name="Admin", email="stages@test.local", password_hash="unused", role=admin_role)
                buyer = User(name="Buyer", email="stagebuyer@test.local", password_hash="unused", role=buyer_role, project_id=project.id)
                bot = Bot(name="Acquisition", project_id=project.id)
                secondary = Bot(name="Named account", project_id=project.id)
                vip = Tag(name="VIP", project_id=project.id)
                foreign = Tag(name="VIP", project_id=other.id)
                db.add_all([actor, buyer, bot, secondary, vip, foreign]); await db.flush()
                funnel = Funnel(name="Base", project_id=project.id, bot_id=bot.id)
                db.add(funnel); await db.flush()
                version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="published")
                db.add(version); await db.flush(); funnel.current_version_id = version.id
                steps = [FunnelStep(funnel_version_id=version.id, key=k, title=k, step_type="message", block_type="message", config_json={}, position_x=0, position_y=i)
                         for i, k in enumerate(["age", "offer"])]
                link = TrackingLink(project_id=project.id, bot_id=bot.id, name="FB", title="FB", code="stages-fb", ref_code="stages-fb", buyer_id=buyer.id)
                db.add_all([*steps, link]); await db.flush()
                now = datetime.now(timezone.utc)
                arrival = now - timedelta(days=5)
                chats, leads = [], []
                for i in range(5):
                    chat = Chat(project_id=project.id, bot_id=bot.id, external_chat_id=str(i), external_user_id=str(i), tracking_link_id=link.id)
                    db.add(chat); await db.flush()
                    lead = Lead(project_id=project.id, chat_id=chat.id, status_id=status.id, name=f"Person {i}")
                    db.add(lead); await db.flush()
                    db.add(Message(chat_id=chat.id, body="/start", sender_type="user", tracking_link_id=link.id, created_at=arrival + timedelta(hours=i)))
                    chats.append(chat); leads.append(lead)
                    if i < 3:
                        # A shown question alone is not a completed age stage.
                        for event in ["entered", "answered", "answered"]:
                            db.add(FunnelStepLog(lead_id=lead.id, funnel_id=funnel.id, funnel_version_id=version.id,
                                step_id=steps[0].id, step_name="age", event_type=event, created_at=arrival + timedelta(hours=8)))
                    if i < 2:
                        db.add(FunnelStepLog(lead_id=lead.id, funnel_id=funnel.id, funnel_version_id=version.id,
                            step_id=steps[1].id, step_name="offer", event_type="entered", created_at=arrival + timedelta(hours=9)))
                db.add(LeadTag(lead_id=leads[0].id, tag_id=vip.id, created_at=arrival + timedelta(hours=10)))
                await db.commit()
            async with engine.begin() as db:
                await db.run_sync(lambda c: migrate(c, "upgrade"))
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(LeadTagHistory)) == 1
                actor = await db.get(User, actor.id); actor.role = await db.get(Role, admin_role.id)
                buyer = await db.get(User, buyer.id); buyer.role = await db.get(Role, buyer_role.id)
                service = TrackingStageJourneyService(db)
                config = make_config(["age", "offer"], vip.id)
                await service.save(actor, project.id, funnel.id, config)
                filters = dict(date_from=arrival.date(), date_to=now.date())
                report = await service.report(actor, project.id, funnel.id, **filters)
                assert report["people"] == 5
                assert [s["reached"] for s in report["items"]] == [5, 3, 2, 1]
                assert report["conversion"] == 20 and report["offer_conversion"] == 50
                original = await db.get(Chat, chats[0].id)
                original.tracking_link_id = None
                await db.flush()
                assert (await service.report(actor, project.id, funnel.id, link_id=link.id, **filters))["people"] == 5
                origin_detail = await service.chats(actor, project.id, funnel.id, config.stages[-1].id, **filters)
                assert origin_detail["items"][0]["link_code"] == "stages-fb"
                assert [s["remaining"] for s in report["items"]] == [2, 1, 1, 0]
                assert [s["next"] for s in report["items"]] == [3, 2, 1, None]
                assert len(report["daily"]) == (now.date() - arrival.date()).days + 1
                assert report["daily"][-1]["people"] == 0
                repo = TagRepository(db)
                await repo.remove_tag_from_lead(leads[0].id, vip.id)
                assert (await service.report(actor, project.id, funnel.id, **filters))["outcomes"] == 1
                # The same person in another bot is neither a new arrival nor a lost handoff.
                handoff = Chat(project_id=project.id, bot_id=secondary.id, external_chat_id="0", external_user_id="0")
                db.add(handoff); await db.flush()
                handoff_lead = Lead(project_id=project.id, chat_id=handoff.id, status_id=status.id)
                db.add(handoff_lead); await db.flush()
                db.add(Message(chat_id=handoff.id, body="/start", sender_type="user", created_at=now))
                await db.flush()
                assert await repo.add_tag_to_lead(handoff_lead.id, vip.id)
                assert not await repo.add_tag_to_lead(handoff_lead.id, vip.id)
                assert (await service.report(actor, project.id, funnel.id, **filters))["outcomes"] == 1
                await repo.add_tag_to_lead(leads[1].id, vip.id)
                # Repeat assignment is a fact but does not double-count a person.
                await repo.remove_tag_from_lead(leads[1].id, vip.id)
                await repo.add_tag_to_lead(leads[1].id, vip.id)
                report = await service.report(actor, project.id, funnel.id, granularity="week", **filters)
                assert report["people"] == 5 and report["outcomes"] == 2 and report["physical_chats"] == 6
                assert report["offer_conversion"] == 100 and report["sources"][0]["outcomes"] == 2
                assert all(date.fromisoformat(str(d["date"])).weekday() == 0 for d in report["daily"])
                people = await service.chats(actor, project.id, funnel.id, config.stages[-1].id, limit=1, offset=1, **filters)
                assert people["total"] == 2 and len(people["items"]) == 1
                # Out-of-order VIP before offer is not an offer -> VIP conversion.
                await repo.add_tag_to_lead(leads[2].id, vip.id)
                db.add(LeadTagHistory(lead_id=leads[2].id, tag_id=vip.id, tag_name="VIP", source="legacy_snapshot",
                    occurred_at=arrival + timedelta(hours=8, minutes=30)))
                db.add(FunnelStepLog(lead_id=leads[2].id, funnel_id=funnel.id, funnel_version_id=version.id,
                    step_id=steps[1].id, step_name="offer", event_type="entered", created_at=arrival + timedelta(hours=9)))
                await db.flush()
                report = await service.report(actor, project.id, funnel.id, **filters)
                assert report["outcomes"] == 3 and report["offer_conversion"] == pytest.approx(200 / 3)
                assert (await service.report(actor, project.id, funnel.id, date_from=now.date(), date_to=now.date()))["people"] == 0
                assert (await service.report(buyer, project.id, funnel.id, **filters))["people"] == 5
                secondary_funnel = Funnel(name="Second", project_id=project.id, bot_id=secondary.id)
                db.add(secondary_funnel); await db.flush()
                secondary_version = FunnelVersion(funnel_id=secondary_funnel.id, version_number=1, status="published")
                db.add(secondary_version); await db.flush()
                db.add(FunnelStep(funnel_version_id=secondary_version.id, key="start", title="Start", step_type="trigger", block_type="start", config_json={}))
                await db.flush()
                short_config = JourneyConfig(stages=[config.stages[0], config.stages[-1]])
                await service.save(actor, project.id, secondary_funnel.id, short_config)
                assert (await service.report(actor, project.id, secondary_funnel.id, **filters))["people"] == 0
                # The same Telegram ID in a different project is a new person there.
                other_bot = Bot(project_id=other.id, name="Other bot")
                db.add(other_bot); await db.flush()
                other_funnel = Funnel(name="Other", project_id=other.id, bot_id=other_bot.id)
                db.add(other_funnel); await db.flush()
                other_version = FunnelVersion(funnel_id=other_funnel.id, version_number=1, status="published")
                db.add(other_version); await db.flush()
                db.add(FunnelStep(funnel_version_id=other_version.id, key="start", title="Start", step_type="trigger", block_type="start", config_json={}))
                other_chat = Chat(project_id=other.id, bot_id=other_bot.id, external_chat_id="0", external_user_id="0")
                db.add(other_chat); await db.flush()
                db.add(Message(chat_id=other_chat.id, body="/start", sender_type="user", created_at=now))
                await db.flush()
                other_config = JourneyConfig(stages=[config.stages[0], dict(id=uuid4(), name="VIP", source="tag", tag_ids=[foreign.id], role="outcome")])
                await service.save(actor, other.id, other_funnel.id, other_config)
                assert (await service.report(actor, other.id, other_funnel.id, **filters))["people"] == 1
                with pytest.raises(HTTPException) as forbidden:
                    await service.save(buyer, project.id, funnel.id, config)
                assert forbidden.value.status_code == 403
                bad = make_config(["age", "offer"], foreign.id)
                with pytest.raises(HTTPException):
                    await service.save(actor, project.id, funnel.id, bad)
                with pytest.raises(HTTPException):
                    await service.report(actor, other.id, funnel.id, **filters)
                # Pending delivery and manual review must not be classified as idle replies.
                state = ChatFunnelState(chat_id=chats[3].id, funnel_id=funnel.id, funnel_version_id=version.id,
                    current_step_id=steps[0].id, waiting_for_answer=True, entered_step_at=arrival)
                db.add(state); await db.flush()
                assert (await service.report(actor, project.id, funnel.id, **filters))["items"][0]["stalled"] == 1
                job = FunnelScheduledJob(chat_id=chats[3].id, funnel_state_id=state.id, funnel_id=funnel.id,
                    funnel_version_id=version.id, step_id=steps[0].id, job_type="send_message", status="pending", run_at=now)
                db.add(job); await db.flush()
                assert (await service.report(actor, project.id, funnel.id, **filters))["items"][0]["stalled"] == 0
                job.status = "done"; state.is_paused = True; await db.flush()
                assert (await service.report(actor, project.id, funnel.id, **filters))["items"][0]["stalled"] == 0
                # Several funnels of one bot require explicit cross-funnel mapping,
                # even when their stable keys happen to have the same spelling.
                alternative = Funnel(name="Alternative", project_id=project.id, bot_id=bot.id)
                db.add(alternative); await db.flush()
                alt_version = FunnelVersion(funnel_id=alternative.id, version_number=1, status="published")
                db.add(alt_version); await db.flush()
                alt_step = FunnelStep(funnel_version_id=alt_version.id, key="age", title="Alternative age", step_type="message", block_type="message", config_json={})
                alt_chat = Chat(project_id=project.id, bot_id=bot.id, external_chat_id="100", external_user_id="100")
                db.add_all([alt_step, alt_chat]); await db.flush()
                alt_lead = Lead(project_id=project.id, chat_id=alt_chat.id, status_id=status.id)
                db.add(alt_lead); await db.flush()
                db.add(Message(chat_id=alt_chat.id, body="/start", sender_type="user", created_at=arrival))
                for event in ["entered", "answered"]:
                    db.add(FunnelStepLog(lead_id=alt_lead.id, funnel_id=alternative.id, funnel_version_id=alt_version.id,
                        step_id=alt_step.id, step_name="Alternative age", event_type=event, created_at=arrival + timedelta(hours=1)))
                await db.flush()
                report = await service.report(actor, project.id, funnel.id, **filters)
                assert report["people"] == 6 and report["items"][1]["reached"] == 3
                combined = config.model_copy(deep=True)
                combined.stages[1].step_keys = []
                from app.schemas.tracking_journey import JourneyStepReference
                combined.stages[1].step_refs = [JourneyStepReference(funnel_id=funnel.id, key="age"),
                                               JourneyStepReference(funnel_id=alternative.id, key="age")]
                await service.save(actor, project.id, funnel.id, combined)
                assert (await service.report(actor, project.id, funnel.id, **filters))["items"][1]["reached"] == 4
                combined.scope = "funnel"
                with pytest.raises(HTTPException):
                    await service.save(actor, project.id, funnel.id, combined)
                config.scope = "funnel"
                await service.save(actor, project.id, funnel.id, config)
                assert (await service.report(actor, project.id, funnel.id, **filters))["people"] == 5
                config.scope = "bot"
                await service.save(actor, project.id, funnel.id, config)
                paged_sources = await service.report(actor, project.id, funnel.id, sources_offset=1, sources_limit=1, **filters)
                assert paged_sources["sources_total"] == 2 and len(paged_sources["sources"]) == 1
                # Auto-start precedes a later unreferenced /start; its original
                # subscription source survives subsequent chat attribution edits.
                channel = TelegramChannel(project_id=project.id, tracker_bot_id=bot.id, telegram_chat_id=-10012345, title="Channel")
                db.add(channel); await db.flush()
                entered_at = arrival + timedelta(hours=3, minutes=59)
                db.add(FunnelStepLog(lead_id=leads[4].id, funnel_id=funnel.id, funnel_version_id=version.id,
                    step_id=steps[0].id, step_name="age", event_type="entered", created_at=entered_at))
                db.add(TelegramChannelSubscriptionEvent(project_id=project.id, channel_id=channel.id, tracker_bot_id=bot.id,
                    tracking_link_id=link.id, telegram_user_id=4, telegram_update_id=99, event_type="join",
                    occurred_at=entered_at, funnel_started_at=entered_at, funnel_start_chat_id=chats[4].id))
                await db.execute(update(Chat).where(Chat.id == chats[4].id).values(tracking_link_id=None))
                await db.execute(update(Message).where(Message.chat_id == chats[4].id).values(tracking_link_id=None))
                await db.flush()
                assert (await service.report(actor, project.id, funnel.id, link_id=link.id, **filters))["people"] == 5
                # Moscow day boundaries must not use the UTC calendar day.
                await db.execute(update(Message).where(Message.chat_id == other_chat.id)
                    .values(created_at=datetime(2026, 9, 24, 21, 15, tzinfo=timezone.utc)))
                assert (await service.report(actor, other.id, other_funnel.id, date_from=date(2026, 9, 25), date_to=date(2026, 9, 25)))["people"] == 1
                assert (await service.report(actor, other.id, other_funnel.id, date_from=date(2026, 9, 24), date_to=date(2026, 9, 24)))["people"] == 0
                await db.commit()
            async with engine.begin() as db:
                await db.run_sync(lambda c: migrate(c, "downgrade"))
                assert await db.scalar(text("SELECT to_regclass('tracking_journey_configs')")) is None
                assert await db.scalar(text("SELECT count(*) FROM chats")) == 8
                await db.run_sync(lambda c: migrate(c, "upgrade"))
        finally:
            await engine.dispose()
            async with root.begin() as db:
                await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
