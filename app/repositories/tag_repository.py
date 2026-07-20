"""
Tag repository.

Tags are project-scoped. LeadTag is the many-to-many junction between leads
and tags; service code must validate both sides belong to the same project
before calling junction-table mutations.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.models.lead import LeadTag
from app.models.tag import Tag
from app.repositories.base import BaseRepository


class TagRepository(BaseRepository[Tag]):
    model = Tag

    async def get_by_name(self, project_id: UUID, name: str) -> Optional[Tag]:
        result = await self.db.execute(
            select(Tag).where(Tag.project_id == project_id, Tag.name == name)
        )
        return result.scalar_one_or_none()

    async def get_by_id_in_project(
        self,
        tag_id: UUID,
        project_id: UUID,
    ) -> Optional[Tag]:
        result = await self.db.execute(
            select(Tag).where(Tag.id == tag_id, Tag.project_id == project_id)
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self,
        project_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Tag]:
        result = await self.db.execute(
            select(Tag)
            .where(Tag.project_id == project_id)
            .order_by(Tag.name.asc(), Tag.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_project(self, project_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count(Tag.id)).where(Tag.project_id == project_id)
        )
        return result.scalar_one()

    async def list_for_lead(self, lead_id: UUID) -> list[Tag]:
        result = await self.db.execute(
            select(Tag)
            .join(LeadTag, LeadTag.tag_id == Tag.id)
            .where(LeadTag.lead_id == lead_id)
            .order_by(Tag.name.asc(), Tag.created_at.desc())
        )
        return list(result.scalars().all())

    async def delete_from_project(self, tag_id: UUID, project_id: UUID) -> bool:
        tag = await self.get_by_id_in_project(tag_id, project_id)
        if tag is None:
            return False

        await self.db.execute(delete(LeadTag).where(LeadTag.tag_id == tag_id))
        await self.db.execute(delete(Tag).where(Tag.id == tag_id))
        return True

    async def update_in_project(
        self,
        tag_id: UUID,
        project_id: UUID,
        **values,
    ) -> Optional[Tag]:
        if not values:
            return await self.get_by_id_in_project(tag_id, project_id)

        result = await self.db.execute(
            update(Tag)
            .where(Tag.id == tag_id, Tag.project_id == project_id)
            .values(**values)
        )
        if result.rowcount == 0:
            return None
        return await self.get_by_id_in_project(tag_id, project_id)

    async def get_lead_tag(self, lead_id: UUID, tag_id: UUID) -> Optional[LeadTag]:
        result = await self.db.execute(
            select(LeadTag).where(
                LeadTag.lead_id == lead_id,
                LeadTag.tag_id == tag_id,
            )
        )
        return result.scalar_one_or_none()

    async def add_tag_to_lead(self, lead_id: UUID, tag_id: UUID) -> bool:
        result = await self.db.execute(
            insert(LeadTag)
            .values(lead_id=lead_id, tag_id=tag_id)
            .on_conflict_do_nothing(
                index_elements=[LeadTag.lead_id, LeadTag.tag_id],
            )
        )
        return result.rowcount == 1

    async def remove_tag_from_lead(self, lead_id: UUID, tag_id: UUID) -> bool:
        result = await self.db.execute(
            delete(LeadTag).where(
                LeadTag.lead_id == lead_id,
                LeadTag.tag_id == tag_id,
            )
        )
        return result.rowcount > 0
