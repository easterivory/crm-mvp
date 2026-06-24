"""
User repository.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import selectinload

from app.models.role import Role
from app.models.user import User, UserProjectAccess
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    def _with_role(self):
        return selectinload(User.role)

    def _with_project_accesses(self):
        return selectinload(User.project_accesses)

    def _load_options(self):
        return (self._with_role(), self._with_project_accesses())

    async def get_by_id(self, id: UUID) -> Optional[User]:
        result = await self.db.execute(
            select(User).options(*self._load_options()).where(User.id == id)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.db.execute(
            select(User)
            .options(*self._load_options())
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
            .options(*self._load_options())
            .where(func.lower(User.email) == email.lower())
            .order_by(User.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        result = await self.db.execute(
            select(User)
            .options(*self._load_options())
            .where(
                User.telegram_id == telegram_id,
                User.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_handler_code(
        self,
        *,
        handler_code: str,
        exclude_user_id: UUID | None = None,
    ) -> Optional[User]:
        stmt = select(User).where(
            User.handler_code == handler_code,
            User.is_deleted.is_(False),
        )
        if exclude_user_id is not None:
            stmt = stmt.where(User.id != exclude_user_id)
        result = await self.db.execute(stmt.limit(1))
        return result.scalar_one_or_none()

    async def get_role_by_id(self, role_id: UUID) -> Optional[Role]:
        result = await self.db.execute(select(Role).where(Role.id == role_id))
        return result.scalar_one_or_none()

    async def list_roles(self) -> list[Role]:
        result = await self.db.execute(select(Role).order_by(Role.name.asc()))
        return list(result.scalars().all())

    async def get_active_in_project(
        self, user_id: UUID, project_id: UUID
    ) -> Optional[User]:
        """
        Fetch a non-deleted user only if they belong to the given project.
        Used by AssignmentService to validate that an assigned manager is a
        member of the same project.
        """
        result = await self.db.execute(
            select(User).options(*self._load_options()).where(
                User.id == user_id,
                or_(
                    User.project_id == project_id,
                    User.id.in_(
                        select(UserProjectAccess.user_id).where(
                            UserProjectAccess.project_id == project_id
                        )
                    ),
                ),
                User.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self, project_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[User]:
        result = await self.db.execute(
            select(User)
            .options(*self._load_options())
            .where(
                or_(
                    User.project_id == project_id,
                    User.id.in_(
                        select(UserProjectAccess.user_id).where(
                            UserProjectAccess.project_id == project_id
                        )
                    ),
                ),
                User.is_deleted.is_(False),
            )
            .order_by(User.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_project(self, project_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count(User.id)).where(
                or_(
                    User.project_id == project_id,
                    User.id.in_(
                        select(UserProjectAccess.user_id).where(
                            UserProjectAccess.project_id == project_id
                        )
                    ),
                ),
                User.is_deleted.is_(False),
            )
        )
        return result.scalar_one()

    async def list_active(
        self,
        limit: int = 50,
        offset: int = 0,
        project_id: Optional[UUID] = None,
    ) -> list[User]:
        stmt = (
            select(User)
            .options(*self._load_options())
            .where(User.is_deleted.is_(False))
        )
        if project_id is not None:
            stmt = stmt.where(
                or_(
                    User.project_id == project_id,
                    User.id.in_(
                        select(UserProjectAccess.user_id).where(
                            UserProjectAccess.project_id == project_id
                        )
                    ),
                )
            )
        stmt = stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_active(self, project_id: Optional[UUID] = None) -> int:
        stmt = select(func.count(User.id)).where(User.is_deleted.is_(False))
        if project_id is not None:
            stmt = stmt.where(
                or_(
                    User.project_id == project_id,
                    User.id.in_(
                        select(UserProjectAccess.user_id).where(
                            UserProjectAccess.project_id == project_id
                        )
                    ),
                )
            )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def soft_delete_by_id(self, user_id: UUID) -> bool:
        result = await self.db.execute(
            update(User)
            .where(
                User.id == user_id,
                User.is_deleted.is_(False),
            )
            .values(is_deleted=True)
        )
        return result.rowcount > 0

    async def soft_delete_from_project(self, user_id: UUID, project_id: UUID) -> bool:
        result = await self.db.execute(
            update(User)
            .where(
                User.id == user_id,
                or_(
                    User.project_id == project_id,
                    User.id.in_(
                        select(UserProjectAccess.user_id).where(
                            UserProjectAccess.project_id == project_id
                        )
                    ),
                ),
                User.is_deleted.is_(False),
            )
            .values(is_deleted=True)
        )
        return result.rowcount > 0

    async def update_user(self, user_id: UUID, **values) -> Optional[User]:
        result = await self.db.execute(
            update(User)
            .where(User.id == user_id, User.is_deleted.is_(False))
            .values(**values)
        )
        if result.rowcount == 0:
            return None
        return await self.get_by_id(user_id)

    async def replace_project_accesses(self, user_id: UUID, project_ids: list[UUID]) -> None:
        await self.db.execute(delete(UserProjectAccess).where(UserProjectAccess.user_id == user_id))
        seen: set[UUID] = set()
        for project_id in project_ids:
            if project_id in seen:
                continue
            seen.add(project_id)
            self.db.add(UserProjectAccess(user_id=user_id, project_id=project_id))
        await self.db.flush()

    async def list_access_project_ids(self, user_id: UUID) -> list[UUID]:
        result = await self.db.execute(
            select(UserProjectAccess.project_id)
            .where(UserProjectAccess.user_id == user_id)
            .order_by(UserProjectAccess.created_at.asc())
        )
        return list(result.scalars().all())

    async def update_password_hash(self, user_id: UUID, password_hash: str) -> bool:
        result = await self.db.execute(
            update(User)
            .where(User.id == user_id, User.is_deleted.is_(False))
            .values(password_hash=password_hash)
        )
        return result.rowcount > 0
