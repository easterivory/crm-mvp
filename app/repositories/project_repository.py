from typing import Optional
from uuid import UUID

from sqlalchemy import func, select, update

from app.models.project import Project
from app.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    model = Project

    async def list(self, limit: int = 50, offset: int = 0) -> list[Project]:
        result = await self.db.execute(
            select(Project)
            .where(Project.is_deleted.is_(False))
            .order_by(Project.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self.db.execute(
            select(func.count(Project.id)).where(Project.is_deleted.is_(False))
        )
        return result.scalar_one()

    async def get_active(self, id: UUID) -> Optional[Project]:
        result = await self.db.execute(
            select(Project).where(Project.id == id, Project.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def update_active(self, id: UUID, **values) -> Optional[Project]:
        result = await self.db.execute(
            update(Project)
            .where(Project.id == id, Project.is_deleted.is_(False))
            .values(**values)
        )
        if result.rowcount == 0:
            return None
        return await self.get_active(id)
