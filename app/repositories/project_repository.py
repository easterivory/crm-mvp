from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select, update

from app.models.project import Project
from app.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    model = Project

    async def get_by_id(self, id: UUID) -> Optional[Project]:
        return await self.get_active(id)

    async def get_by_slug(self, slug: str) -> Optional[Project]:
        result = await self.db.execute(
            select(Project).where(
                Project.slug == slug,
                Project.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def get_any_by_slug(self, slug: str) -> Optional[Project]:
        result = await self.db.execute(select(Project).where(Project.slug == slug))
        return result.scalar_one_or_none()

    async def get_any_by_id(self, id: UUID) -> Optional[Project]:
        result = await self.db.execute(select(Project).where(Project.id == id))
        return result.scalar_one_or_none()

    async def list(self, limit: int = 50, offset: int = 0) -> list[Project]:
        result = await self.db.execute(
            select(Project)
            .where(Project.is_deleted.is_(False))
            .order_by(Project.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_ids(self, ids: list[UUID]) -> list[Project]:
        if not ids:
            return []
        result = await self.db.execute(
            select(Project)
            .where(Project.id.in_(ids), Project.is_deleted.is_(False))
            .order_by(Project.created_at.desc())
        )
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self.db.execute(
            select(func.count(Project.id)).where(Project.is_deleted.is_(False))
        )
        return result.scalar_one()

    async def slug_exists(
        self,
        slug: str,
        exclude_id: Optional[UUID] = None,
    ) -> bool:
        stmt = select(func.count(Project.id)).where(Project.slug == slug)
        if exclude_id is not None:
            stmt = stmt.where(Project.id != exclude_id)
        result = await self.db.execute(stmt)
        return result.scalar_one() > 0

    async def get_active(self, id: UUID) -> Optional[Project]:
        result = await self.db.execute(
            select(Project).where(Project.id == id, Project.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def update_active(self, id: UUID, **values: Any) -> Optional[Project]:
        values["updated_at"] = func.now()
        result = await self.db.execute(
            update(Project)
            .where(Project.id == id, Project.is_deleted.is_(False))
            .values(**values)
        )
        if result.rowcount == 0:
            return None
        return await self.get_any_by_id(id)

    async def archive(self, id: UUID) -> bool:
        result = await self.db.execute(
            update(Project)
            .where(Project.id == id, Project.is_deleted.is_(False))
            .values(
                status="archived",
                is_deleted=True,
                updated_at=func.now(),
            )
        )
        return result.rowcount > 0
