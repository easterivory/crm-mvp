"""Real database regressions: priority lifecycle and duplicate-card cohorts."""
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
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import *  # noqa: F403
from app.models.base import Base
from app.models.bot import Bot
from app.models.chat import Chat
from app.models.funnel import Funnel, FunnelVersion, FunnelStep, FunnelStepLog
from app.models.lead import Lead, LeadTag
from app.models.lead_status import LeadStatus
from app.models.project import Project
from app.models.role import Role
from app.models.tag import Tag
from app.models.tracking import TrackingLink
from app.models.user import User
from app.repositories.chat_repository import ChatRepository
from app.schemas.project import PriorityChatRules, ProjectUpdate
from app.services.project_service import ProjectService
from app.services.tracking_duplicate_service import TrackingDuplicateService
from app.services.tracking_step_metrics_service import TrackingStepMetricsService


def test_priority_schema_requires_valid_identifiers_and_is_opt_in():
    assert not PriorityChatRules().enabled
    assert ProjectUpdate(priority_chat_rules={"enabled": False}).priority_chat_rules.tag_ids == []
    with pytest.raises(ValueError):
        PriorityChatRules(tag_ids=["HOT"])


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_priority_lifecycle_duplicate_sources_permissions_and_migration():
    async def run():
        schema = "priority_" + uuid4().hex
        url = os.environ["CRM_TEST_POSTGRES_URL"]
        root = create_async_engine(url)
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
        try:
            async with root.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with sessions() as db:
                projects = [Project(name=str(i), slug=f"project-{i}") for i in range(3)]
                status = LeadStatus(code="new", name="New")
                db.add_all([*projects, status]); await db.flush()
                p, other, hidden = projects
                bots = [Bot(project_id=project.id, name=f"Bot {i}") for i, project in enumerate(projects)]
                hot, foreign = Tag(project_id=p.id, name="HOT"), Tag(project_id=other.id, name="HOT")
                db.add_all([*bots, hot, foreign]); await db.flush()
                funnel = Funnel(project_id=p.id, bot_id=bots[0].id, name="Priority")
                db.add(funnel); await db.flush()
                versions = [FunnelVersion(funnel_id=funnel.id, version_number=i, status="published") for i in (1, 2)]
                db.add_all(versions); await db.flush()
                steps = [FunnelStep(funnel_version_id=v.id, key="contacts", title="Contacts", step_type="input", block_type="generic_input") for v in versions]
                db.add_all(steps); await db.flush()
                chats = [Chat(project_id=p.id, bot_id=bots[0].id, external_chat_id=f"priority-{i}",
                    external_user_id=f"priority-{i}", last_client_message_at=now, current_cycle_started_at=now - timedelta(hours=1),
                    is_read=False, is_blocked_by_user=i == 5) for i in range(6)]
                db.add_all(chats); await db.flush()
                leads = [Lead(project_id=p.id, chat_id=c.id, status_id=status.id) for c in chats]
                db.add_all(leads); await db.flush()
                db.add_all([LeadTag(lead_id=leads[i].id, tag_id=hot.id) for i in (0, 1, 5)])
                chats[1].last_manager_reply_at = now + timedelta(seconds=1)
                for i, at in [(2, now), (3, now - timedelta(days=1))]:
                    db.add(FunnelStepLog(lead_id=leads[i].id, funnel_id=funnel.id, funnel_version_id=versions[1].id,
                        step_id=steps[1].id, step_name="Contacts", event_type="entered", created_at=at))
                rules = {"enabled": True, "tag_ids": [str(hot.id)], "step_ids": [str(steps[0].id)]}
                actor = User(id=uuid4(), role=Role(name="super_admin"))
                options = await TrackingStepMetricsService(db).options(actor, p.id, include_equivalent_ids=True)
                assert len(options) == 1 and set(options[0]["equivalent_step_ids"]) == {step.id for step in steps}
                service = ProjectService(db)
                await service.update_project(p.id, ProjectUpdate(priority_chat_rules=rules), actor=actor)
                with pytest.raises(HTTPException):
                    await service.update_project(p.id, ProjectUpdate(priority_chat_rules={"enabled": True}), actor=actor)
                with pytest.raises(HTTPException):
                    await service.update_project(p.id, ProjectUpdate(priority_chat_rules={"enabled": True, "tag_ids": [foreign.id]}), actor=actor)
                await db.commit()
                repo = ChatRepository(db)
                kwargs = dict(project_id=p.id, workspace_view="priority", priority_rules=rules)
                assert {c.id for c in await repo.list(**kwargs)} == {chats[0].id, chats[2].id}
                assert await repo.count(**kwargs) == 2
                counts = await repo.workspace_counts(project_id=p.id, viewer_id=actor.id, hide_assigned_from_all=False, priority_rules=rules)
                assert counts["priority"] == 2
                await repo.mark_as_read(chats[0].id)
                assert await repo.count(**kwargs) == 2
                await repo.update_timestamps(chats[0].id, "manager", now + timedelta(seconds=2))
                assert await repo.count(**kwargs) == 1
                await repo.update_timestamps(chats[0].id, "user", now + timedelta(seconds=3))
                assert await repo.count(**kwargs) == 2
                assert await repo.count(project_id=p.id, workspace_view="priority") == 0
                assert await repo.count(**{**kwargs, "bot_id": bots[1].id}) == 0
                await db.execute(LeadTag.__table__.delete().where(LeadTag.lead_id == leads[0].id))
                assert await repo.count(**kwargs) == 1

                buyer_id = uuid4()
                # Buyer is only used as a filter; persist its FK in the source table.
                buyer = User(id=buyer_id, name="Buyer", email=f"{buyer_id}@qa.test", password_hash="not-a-login", role=Role(name="buyer"), project_id=p.id)
                db.add(buyer)
                await db.flush()
                links = [TrackingLink(project_id=p.id, bot_id=bots[0].id, name=f"Link {i}", ref_code=f"link-{i}", code=f"link-{i}", title=f"Link {i}", buyer_id=buyer_id if i == 0 else None) for i in range(2)]
                db.add_all(links); await db.flush()
                async def card(project_index, created_at, *, phone=None, username=None, telegram=None, link=None):
                    chat = Chat(project_id=projects[project_index].id, bot_id=bots[project_index].id,
                        external_chat_id=str(uuid4()), external_user_id=telegram or str(uuid4()), tracking_link_id=link, created_at=created_at)
                    db.add(chat); await db.flush()
                    lead = Lead(project_id=chat.project_id, chat_id=chat.id, status_id=status.id,
                        phone=phone, username=username, created_at=created_at)
                    db.add(lead); await db.flush()
                    return lead
                await card(0, now - timedelta(days=6), phone="+7 (900) 123-45-67", telegram="100")
                await card(1, now - timedelta(days=5), phone="79001234567")
                await card(2, now - timedelta(days=4), username="hidden")
                base = now - timedelta(days=1)
                await card(0, base, phone="79001234567", telegram="100", username="alice", link=links[0].id)
                await card(0, base + timedelta(minutes=1), username="@Alice", link=links[1].id)
                await card(0, base + timedelta(minutes=2), username="hidden")
                await card(0, base + timedelta(minutes=3), username="not-yet-duplicate", link=links[0].id)
                await card(0, now + timedelta(days=1), username="not-yet-duplicate")
                await db.commit()
                report = await TrackingDuplicateService(db).report(actor, p.id, date_from=date(2026, 10, 25), date_to=date(2026, 10, 25))
                assert report["summary"] == {"cards": 4, "duplicates": 3, "within_project": 2, "cross_project": 2}
                for key in report["summary"]:
                    assert sum(source[key] for source in report["sources"]) == report["summary"][key]
                    assert sum(day[key] for day in report["daily"]) == report["summary"][key]
                scoped_actor = User(id=uuid4(), project_id=p.id, role=Role(name="admin"))
                scoped = await TrackingDuplicateService(db).report(scoped_actor, p.id, date_from=date(2026, 10, 25), date_to=date(2026, 10, 25))
                assert scoped["summary"]["duplicates"] == 2 and scoped["summary"]["cross_project"] == 0
                owned = await TrackingDuplicateService(db).report(actor, p.id, buyer_id=buyer_id, date_from=base.date(), date_to=base.date())
                assert owned["summary"]["cards"] == 2 and owned["summary"]["duplicates"] == 1
                one = await TrackingDuplicateService(db).report(actor, p.id, link_id=links[1].id, date_from=base.date(), date_to=base.date())
                assert one["summary"]["duplicates"] == 1
                own = await TrackingDuplicateService(db).report(buyer, p.id, date_from=base.date(), date_to=base.date())
                assert own["summary"]["cards"] == 2 and own["summary"]["duplicates"] == 1
                with pytest.raises(HTTPException) as forbidden:
                    await TrackingDuplicateService(db).report(buyer, p.id, buyer_id=uuid4())
                assert forbidden.value.status_code == 403
                with pytest.raises(HTTPException) as forbidden:
                    await service.update_project(p.id, ProjectUpdate(priority_chat_rules=rules), actor=buyer)
                assert forbidden.value.status_code == 403
                with pytest.raises(HTTPException):
                    await TrackingDuplicateService(db).report(scoped_actor, other.id)
                await db.execute(text("SET LOCAL enable_seqscan = off"))
                query = TrackingDuplicateService.query(p.id, base.date(), base.date())
                sql = str(query.compile(engine.sync_engine, compile_kwargs={"literal_binds": True}))
                plan = " ".join((await db.execute(text("EXPLAIN " + sql))).scalars())
                assert "ix_leads_phone_digits" in plan and "ix_leads_username_lower" in plan

            path = Path(__file__).parents[1] / "alembic/versions/20261026_0088_priority_chat_rules.py"
            spec = importlib.util.spec_from_file_location("priority_migration", path)
            migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
            def migrate(conn, direction):
                with Operations.context(MigrationContext.configure(conn)):
                    getattr(migration, direction)()
            async with engine.begin() as conn:
                before = await conn.scalar(text("SELECT count(*) FROM chats"))
                await conn.run_sync(migrate, "downgrade")
                await conn.run_sync(migrate, "upgrade")
                assert await conn.scalar(text("SELECT count(*) FROM chats")) == before
                assert await conn.scalar(text("SELECT bool_and(priority_chat_rules = '{}'::jsonb) FROM projects"))
        finally:
            await engine.dispose()
            async with root.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
