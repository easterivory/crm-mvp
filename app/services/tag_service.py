"""
TagService - project-scoped tag CRUD and lead/tag bindings.
"""
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.lead_repository import LeadRepository
from app.repositories.tag_repository import TagRepository
from app.schemas.tag import TagCreate, TagOut, TagUpdate


class TagService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.tag_repo = TagRepository(db)
        self.lead_repo = LeadRepository(db)

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

        existing = await self.tag_repo.get_by_name(project_id, name)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tag with this name already exists in this project",
            )

        try:
            async with self.db.begin_nested():
                tag = await self.tag_repo.create(project_id=project_id, name=name)
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
        deleted = await self.tag_repo.delete_from_project(tag_id, project_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tag not found",
            )

    async def update_tag(
        self,
        tag_id: UUID,
        project_id: UUID,
        data: TagUpdate,
    ) -> TagOut:
        name = self._normalize_name(data.name)
        existing = await self.tag_repo.get_by_name(project_id, name)
        if existing is not None and existing.id != tag_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tag with this name already exists in this project",
            )

        try:
            tag = await self.tag_repo.update_name_in_project(tag_id, project_id, name)
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
        await self._ensure_lead_and_tag_in_project(
            lead_id=lead_id,
            tag_id=tag_id,
            project_id=project_id,
        )

        try:
            async with self.db.begin_nested():
                await self.tag_repo.add_tag_to_lead(lead_id=lead_id, tag_id=tag_id)
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

    async def _ensure_lead_and_tag_in_project(
        self,
        lead_id: UUID,
        tag_id: UUID,
        project_id: UUID,
    ) -> None:
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

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Tag name must not be empty",
            )
        return normalized
