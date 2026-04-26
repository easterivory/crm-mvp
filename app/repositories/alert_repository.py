from uuid import UUID

from sqlalchemy import select

from app.models.alert import Alert
from app.repositories.base import BaseRepository


class AlertRepository(BaseRepository[Alert]):
    model = Alert

    async def has_unread(self, project_id: UUID, alert_type: str) -> bool:
        """Return True if an unread alert of this type already exists for the project."""
        result = await self.db.execute(
            select(Alert).where(
                Alert.project_id == project_id,
                Alert.type == alert_type,
                Alert.is_read.is_(False),
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def list_by_project(
        self,
        project_id: UUID,
        only_unread: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Alert]:
        stmt = select(Alert).where(Alert.project_id == project_id)
        if only_unread:
            stmt = stmt.where(Alert.is_read.is_(False))
        stmt = stmt.order_by(Alert.created_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
