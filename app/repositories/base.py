"""
Generic async repository providing basic CRUD operations.
Domain repositories inherit from this and add query-specific methods.
"""
from typing import Any, Generic, Optional, TypeVar
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, id: UUID) -> Optional[ModelT]:
        result = await self.db.execute(select(self.model).where(self.model.id == id))
        return result.scalar_one_or_none()

    async def create(self, **kwargs: Any) -> ModelT:
        instance = self.model(**kwargs)
        self.db.add(instance)
        await self.db.flush()
        await self.db.refresh(instance)
        return instance

    async def update_by_id(self, id: UUID, **kwargs: Any) -> Optional[ModelT]:
        await self.db.execute(
            update(self.model).where(self.model.id == id).values(**kwargs)
        )
        return await self.get_by_id(id)

    async def soft_delete(self, id: UUID) -> None:
        """Sets is_deleted = True. Data is never hard-deleted."""
        await self.db.execute(
            update(self.model)
            .where(self.model.id == id)
            .values(is_deleted=True)
        )
