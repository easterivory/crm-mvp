from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update

from app.models.scheduled_message import ScheduledMessage
from app.repositories.base import BaseRepository


class ScheduledMessageRepository(BaseRepository[ScheduledMessage]):
    model = ScheduledMessage

    async def create_scheduled_message(self, **values) -> ScheduledMessage:
        return await self.create(**values)

    async def list_due(self, now: datetime, limit: int = 100) -> list[ScheduledMessage]:
        result = await self.db.execute(
            select(ScheduledMessage)
            .where(ScheduledMessage.status == "pending", ScheduledMessage.scheduled_at <= now)
            .order_by(ScheduledMessage.scheduled_at.asc(), ScheduledMessage.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def list_for_chat(
        self,
        chat_id: UUID,
        project_id: UUID,
        *,
        active_only: bool = False,
    ) -> list[ScheduledMessage]:
        stmt = select(ScheduledMessage).where(
            ScheduledMessage.chat_id == chat_id,
            ScheduledMessage.project_id == project_id,
        )
        if active_only:
            stmt = stmt.where(
                ScheduledMessage.status.in_(("pending", "running", "failed"))
            )
        result = await self.db.execute(
            stmt.order_by(ScheduledMessage.scheduled_at.asc()).limit(200)
        )
        return list(result.scalars().all())

    async def get_in_project(self, message_id: UUID, project_id: UUID) -> ScheduledMessage | None:
        result = await self.db.execute(
            select(ScheduledMessage).where(
                ScheduledMessage.id == message_id,
                ScheduledMessage.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()

    async def mark_running(self, message_id: UUID) -> None:
        await self.db.execute(
            update(ScheduledMessage)
            .where(ScheduledMessage.id == message_id, ScheduledMessage.status == "pending")
            .values(status="running", attempts=ScheduledMessage.attempts + 1)
        )

    async def mark_sent(self, message_id: UUID, sent_message_id: UUID) -> None:
        await self.db.execute(
            update(ScheduledMessage)
            .where(ScheduledMessage.id == message_id)
            .values(status="sent", sent_message_id=sent_message_id, last_error=None)
        )

    async def mark_failed(self, message_id: UUID, error: str) -> None:
        await self.db.execute(
            update(ScheduledMessage)
            .where(ScheduledMessage.id == message_id)
            .values(status="failed", last_error=error[:2000])
        )

    async def cancel(self, message_id: UUID, project_id: UUID) -> bool:
        result = await self.db.execute(
            update(ScheduledMessage)
            .where(
                ScheduledMessage.id == message_id,
                ScheduledMessage.project_id == project_id,
                ScheduledMessage.status == "pending",
            )
            .values(status="cancelled")
        )
        return bool(result.rowcount)
