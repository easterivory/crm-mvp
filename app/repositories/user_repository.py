"""
User repository.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select

from app.models.role import Role
from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.db.execute(
            select(User)
            .where(
                func.lower(User.email) == email.lower(),
                User.is_deleted.is_(False),
            )
            .order_by(User.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_any_by_email(self, email: str) -> Optional[User]:
        result = await self.db.execute(
            select(User)
            .where(func.lower(User.email) == email.lower())
            .order_by(User.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_role_by_id(self, role_id: UUID) -> Optional[Role]:
        result = await self.db.execute(select(Role).where(Role.id == role_id))
        return result.scalar_one_or_none()

    async def get_active_in_project(
        self, user_id: UUID, project_id: UUID
    ) -> Optional[User]:
        """
        Fetch a non-deleted user only if they belong to the given project.
        Used by AssignmentService to validate that an assigned manager is a
        member of the same project.
        """
        result = await self.db.execute(
            select(User).where(
                User.id == user_id,
                User.project_id == project_id,
                User.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self, project_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[User]:
        result = await self.db.execute(
            select(User)
            .where(User.project_id == project_id, User.is_deleted.is_(False))
            .order_by(User.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_project(self, project_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count(User.id)).where(
                User.project_id == project_id,
                User.is_deleted.is_(False),
            )
        )
        return result.scalar_one()
