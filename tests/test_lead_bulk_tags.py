"""Atomic tag deltas with real PostgreSQL and existing lifecycle triggers."""
import asyncio
import os
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Project, Chat, Lead, Bot
from app.models.lead_status import LeadStatus
from app.models.lead_event import LeadEvent
from app.models.tag import Tag
from app.repositories.tag_repository import TagRepository
from app.schemas.tag import LeadTagsUpdate
from app.services.tag_service import TagService


def test_bulk_tags_disallow_conflicting_changes():
    tag_id = uuid4()
    with pytest.raises(ValidationError):
        LeadTagsUpdate(add_tag_ids=[tag_id], remove_tag_ids=[tag_id])
    with pytest.raises(ValidationError):
        LeadTagsUpdate(add_tag_ids=[uuid4() for _ in range(101)])


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_bulk_tag_delta_atomic_idempotent_and_trigger_compatible():
    async def run():
        url = os.environ["CRM_TEST_POSTGRES_URL"]
        schema = "bulktags_" + uuid4().hex
        root = create_async_engine(url)
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        try:
            async with root.begin() as db:
                await db.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as db:
                await db.run_sync(Base.metadata.create_all)
            async with sessions() as db:
                project = Project(name="Bulk tags", slug="bulk-tags")
                other = Project(name="Other", slug="other")
                status = LeadStatus(code="new", name="New")
                db.add_all([project, other, status]); await db.flush()
                bot = Bot(project_id=project.id, name="Bot")
                tags = [Tag(project_id=project.id, name=name) for name in ("Keep", "Remove", "Registration", "New")]
                foreign = Tag(project_id=other.id, name="Foreign")
                db.add_all([bot, *tags, foreign]); await db.flush()
                chat = Chat(project_id=project.id, bot_id=bot.id, external_chat_id="1", external_user_id="1")
                db.add(chat); await db.flush()
                lead = Lead(project_id=project.id, chat_id=chat.id, status_id=status.id, name="Lead")
                db.add(lead); await db.flush()
                project.facebook_tag_event_rules = [{"tag_id": str(tags[2].id), "source_event": "registration"}]
                repo = TagRepository(db)
                for tag in tags[:2]:
                    await repo.add_tag_to_lead(lead.id, tag.id)
                await db.commit()
                service = TagService(db)
                before = {tag.id for tag in await repo.list_for_lead(lead.id)}
                with pytest.raises(HTTPException):
                    await service.update_lead_tags(lead.id, project.id, LeadTagsUpdate(
                        add_tag_ids=[tags[2].id, foreign.id], remove_tag_ids=[tags[1].id]))
                assert {tag.id for tag in await repo.list_for_lead(lead.id)} == before
                assert await db.scalar(select(func.count()).select_from(LeadEvent)) == 0
                change = LeadTagsUpdate(add_tag_ids=[tags[2].id, tags[3].id, tags[2].id], remove_tag_ids=[tags[1].id])
                updated = await service.update_lead_tags(lead.id, project.id, change)
                assert {tag.id for tag in updated} == {tags[0].id, tags[2].id, tags[3].id}
                events = (await db.scalars(select(LeadEvent))).all()
                assert len(events) == 1 and events[0].event_type == "registration" and events[0].source == "tag"
                await service.update_lead_tags(lead.id, project.id, change)
                assert await db.scalar(select(func.count()).select_from(LeadEvent)) == 1
                assert lead.score_calculated_at is not None
                # Unchanged single-tag endpoints keep their original semantics.
                await service.add_tag_to_lead(lead.id, tags[1].id, project.id)
                await service.remove_tag_from_lead(lead.id, tags[3].id, project.id)
                assert {tag.id for tag in await repo.list_for_lead(lead.id)} == {tags[0].id, tags[1].id, tags[2].id}
                with pytest.raises(HTTPException):
                    await service.update_lead_tags(lead.id, other.id, LeadTagsUpdate(remove_tag_ids=[tags[0].id]))
        finally:
            await engine.dispose()
            async with root.begin() as db:
                await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
