"""
TagService - project-scoped tag CRUD and lead/tag bindings.
"""
import logging
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.lead_repository import LeadRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.tag_repository import TagRepository
from app.schemas.tag import TagCreate, TagOut, TagUpdate
from app.models.lead import Lead
from app.models.tag import Tag, random_tag_color
from app.services.facebook_campaign_service import FacebookCampaignService
from app.services.lead_event_service import LeadEventService
from app.services.lead_scoring_service import LeadScoringService


logger = logging.getLogger(__name__)


class TagService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.tag_repo = TagRepository(db)
        self.lead_repo = LeadRepository(db)
        self.project_repo = ProjectRepository(db)
        self.facebook_campaign = FacebookCampaignService(db)
        self.lead_events = LeadEventService(db)
        self.scoring = LeadScoringService(db)

    async def list_tags(
        self,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[TagOut], int]:
        tags = await self.tag_repo.list_by_project(
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
        total = await self.tag_repo.count_by_project(project_id)
        return [TagOut.model_validate(tag) for tag in tags], total

    async def create_tag(self, project_id: UUID, data: TagCreate) -> TagOut:
        name = self._normalize_name(data.name)
        color = self._normalize_color(data.color) or random_tag_color()

        existing = await self.tag_repo.get_by_name(project_id, name)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tag with this name already exists in this project",
            )

        try:
            async with self.db.begin_nested():
                tag = await self.tag_repo.create(project_id=project_id, name=name, color=color)
        except IntegrityError:
            existing = await self.tag_repo.get_by_name(project_id, name)
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Tag with this name already exists in this project",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not create tag",
            )

        return TagOut.model_validate(tag)

    async def delete_tag(self, tag_id: UUID, project_id: UUID) -> None:
        tag = await self.tag_repo.get_by_id_in_project(tag_id, project_id)
        if tag is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tag not found",
            )
        deleted = await self.tag_repo.delete_from_project(tag_id, project_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tag not found",
            )
        project = await self.project_repo.get_active(project_id)
        if project is not None:
            tag_id_text = str(tag_id)
            rules = [
                rule
                for rule in (project.facebook_tag_event_rules or [])
                if not isinstance(rule, dict)
                or str(rule.get("tag_id") or "") != tag_id_text
            ]
            vip_tags = [
                value
                for value in (project.vip_tags or [])
                if value not in {tag_id_text, tag.name}
            ]
            if (
                rules != (project.facebook_tag_event_rules or [])
                or vip_tags != (project.vip_tags or [])
            ):
                await self.project_repo.update_active(
                    project_id,
                    facebook_tag_event_rules=rules,
                    vip_tags=vip_tags,
                )

    async def update_tag(
        self,
        tag_id: UUID,
        project_id: UUID,
        data: TagUpdate,
    ) -> TagOut:
        values = data.model_dump(exclude_unset=True)
        updates: dict[str, str] = {}

        if "name" in values and values["name"] is not None:
            name = self._normalize_name(values["name"])
            existing = await self.tag_repo.get_by_name(project_id, name)
            if existing is not None and existing.id != tag_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Tag with this name already exists in this project",
                )
            updates["name"] = name

        if "color" in values and values["color"] is not None:
            updates["color"] = self._normalize_color(values["color"]) or random_tag_color()

        try:
            tag = await self.tag_repo.update_in_project(tag_id, project_id, **updates)
        except IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tag with this name already exists in this project",
            )

        if tag is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tag not found",
            )
        return TagOut.model_validate(tag)

    async def add_tag_to_lead(
        self,
        lead_id: UUID,
        tag_id: UUID,
        project_id: UUID,
    ) -> None:
        lead, tag = await self._ensure_lead_and_tag_in_project(
            lead_id=lead_id,
            tag_id=tag_id,
            project_id=project_id,
        )

        added = False
        try:
            async with self.db.begin_nested():
                added = await self.tag_repo.add_tag_to_lead(
                    lead_id=lead_id,
                    tag_id=tag_id,
                )
        except IntegrityError:
            # Idempotent under races: another request may have inserted the
            # same composite PK after our pre-check.
            existing = await self.tag_repo.get_lead_tag(lead_id, tag_id)
            if existing is not None:
                return
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not attach tag to lead",
            )
        if added:
            await self.facebook_campaign.enqueue_tag_added(
                lead_id=lead_id,
                tag_id=tag_id,
            )
            project = await self.project_repo.get_active(project_id)
            if project is not None:
                lifecycle_types = {
                    "registration": "registration",
                    "sale": "deposit",
                    "resale": "redeposit",
                }
                event_types = {
                    lifecycle_types[source_event]
                    for rule in (project.facebook_tag_event_rules or [])
                    if isinstance(rule, dict)
                    and str(rule.get("tag_id") or "") == str(tag_id)
                    and (source_event := str(rule.get("source_event") or ""))
                    in lifecycle_types
                }
                for event_type in sorted(event_types):
                    try:
                        async with self.db.begin_nested():
                            await self.lead_events.record_event(
                                lead=lead,
                                event_type=event_type,
                                source="tag",
                                payload={
                                    "tag_id": str(tag.id),
                                    "tag_name": tag.name,
                                },
                            )
                    except Exception:
                        logger.exception(
                            "Lifecycle event write failed without blocking tag assignment "
                            "lead_id=%s tag_id=%s event_type=%s",
                            lead_id,
                            tag_id,
                            event_type,
                        )
            await self.scoring.update_lead_score(lead_id)

    async def remove_tag_from_lead(
        self,
        lead_id: UUID,
        tag_id: UUID,
        project_id: UUID,
    ) -> None:
        await self._ensure_lead_and_tag_in_project(
            lead_id=lead_id,
            tag_id=tag_id,
            project_id=project_id,
        )
        await self.tag_repo.remove_tag_from_lead(lead_id=lead_id, tag_id=tag_id)
        await self.scoring.update_lead_score(lead_id)

    async def _ensure_lead_and_tag_in_project(
        self,
        lead_id: UUID,
        tag_id: UUID,
        project_id: UUID,
    ) -> tuple[Lead, Tag]:
        lead = await self.lead_repo.get_active(lead_id, project_id)
        if lead is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found",
            )

        tag = await self.tag_repo.get_by_id_in_project(tag_id, project_id)
        if tag is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tag not found",
            )
        return lead, tag

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Tag name must not be empty",
            )
        return normalized

    @staticmethod
    def _normalize_color(color: str | None) -> str | None:
        if color is None:
            return None
        return color.strip().upper()
