"""Tag qualification against isolated PostgreSQL, without transport mocks."""
import asyncio
import os
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Project, Chat, Lead, Bot, User
from app.models.lead import LeadTag
from app.models.lead_status import LeadStatus
from app.models.role import Role
from app.models.tag import Tag
from app.models.tracking import TrackingLink
from app.repositories.tracking_metrics_repository import TrackingMetricsRepository
from app.repositories.project_metrics_repository import ProjectMetricsRepository
from app.schemas.project import ProjectUpdate
from app.services.project_service import ProjectService
from app.services.info_bot_reports import InfoBotReports


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_tag_only_qualification_and_safe_status_default():
    async def run():
        url = os.environ["CRM_TEST_POSTGRES_URL"]
        schema = "taglead_" + uuid4().hex
        root = create_async_engine(url)
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with root.begin() as db:
                await db.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as db:
                await db.run_sync(Base.metadata.create_all)
            async with sessions() as db:
                project = Project(name="Tags", slug="tag-leads", tracking_lead_status_codes=["qualified"])
                other = Project(name="Other", slug="other")
                statuses = [LeadStatus(name="New", code="new"), LeadStatus(name="Qualified", code="qualified")]
                role = Role(name="super_admin")
                db.add_all([project, other, *statuses, role]); await db.flush()
                actor = User(name="Admin", email="tag-test@test.local", password_hash="unused", role=role)
                bot = Bot(project_id=project.id, name="Bot")
                tags = [Tag(project_id=project.id, name="One"), Tag(project_id=project.id, name="Two"), Tag(project_id=other.id, name="Foreign")]
                db.add_all([actor, bot, *tags]); await db.flush()
                link = TrackingLink(project_id=project.id, bot_id=bot.id, name="Link", title="Link", code="tag-link", ref_code="tag-link")
                db.add(link); await db.flush()
                chats = [Chat(project_id=project.id, bot_id=bot.id, tracking_link_id=link.id, external_chat_id=str(index), external_user_id=str(index)) for index in (1, 2)]
                db.add_all(chats); await db.flush()
                when = datetime(2025, 1, 6, 12, tzinfo=timezone.utc)
                leads = [Lead(project_id=project.id, chat_id=chats[0].id, status_id=statuses[0].id, created_at=when),
                         Lead(project_id=project.id, chat_id=chats[1].id, status_id=statuses[1].id, created_at=when)]
                db.add_all(leads); await db.flush()
                db.add_all([LeadTag(lead_id=leads[0].id, tag_id=tag.id) for tag in tags[:2]])
                await db.commit()
                repo = TrackingMetricsRepository(db)
                day = date(2025, 1, 6)
                assert project.tracking_lead_count_mode == "statuses"
                assert await repo.aggregate_leads_by_link(link.id, day, day, ["qualified"]) == 1
                service = ProjectService(db)
                with pytest.raises(HTTPException):
                    await service.update_project(project.id, ProjectUpdate(tracking_lead_count_mode="tags"), actor=actor)
                with pytest.raises(HTTPException):
                    await service.update_project(project.id, ProjectUpdate(tracking_lead_count_mode="tags", tracking_lead_tag_ids=[tags[2].id]), actor=actor)
                await service.update_project(project.id, ProjectUpdate(tracking_lead_count_mode="tags", tracking_lead_tag_ids=[tag.id for tag in tags[:2]]), actor=actor)
                assert await repo.aggregate_leads_by_link(link.id, day, day, ["qualified"]) == 1
                # The tagged New lead is counted, the untagged Qualified lead is not.
                leads[1].status_id = statuses[0].id
                await db.flush()
                assert await repo.aggregate_leads_by_project(project.id, None, day, day, ["qualified"]) == 1
                assert (await ProjectMetricsRepository(db).header_metrics(project.id, day))["leads_today"] == 1
                assert (await InfoBotReports(db).summary(project, day, day, link))["leads"] == 1
                for tag in tags[:2]:
                    await db.execute(text("DELETE FROM lead_tags WHERE lead_id=:lead AND tag_id=:tag"), {"lead": leads[0].id, "tag": tag.id})
                assert await repo.aggregate_leads_by_link(link.id, day, day, ["qualified"]) == 0
                await service.update_project(project.id, ProjectUpdate(tracking_lead_count_mode="statuses"), actor=actor)
                leads[1].status_id = statuses[1].id
                await db.flush()
                assert await repo.aggregate_leads_by_link(link.id, day, day, ["qualified"]) == 1
        finally:
            await engine.dispose()
            async with root.begin() as db:
                await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
