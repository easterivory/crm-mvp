"""
Tracking repository.

Tracking links are project-scoped attribution sources for Telegram /start
payloads. The ref_code is globally unique so inbound webhook lookup stays
simple and fast.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from app.models.chat import Chat
from app.models.lead import Lead
from app.models.tracking import TrackingEvent
from app.models.tracking import TrackingLink
from app.repositories.base import BaseRepository


class TrackingRepository(BaseRepository[TrackingLink]):
    model = TrackingLink

    async def get_by_ref_code(
        self,
        ref_code: str,
        project_id: UUID | None = None,
    ) -> Optional[TrackingLink]:
        stmt = (
            select(TrackingLink)
            .options(selectinload(TrackingLink.bot))
            .where(TrackingLink.ref_code == ref_code)
        )
        if project_id is not None:
            stmt = stmt.where(TrackingLink.project_id == project_id)

        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_in_project(
        self,
        tracking_link_id: UUID,
        project_id: UUID,
    ) -> Optional[TrackingLink]:
        result = await self.db.execute(
            select(TrackingLink)
            .options(selectinload(TrackingLink.bot))
            .where(
                TrackingLink.id == tracking_link_id,
                TrackingLink.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self,
        project_id: UUID,
        limit: int = 50,
        offset: int = 0,
        bot_id: UUID | None = None,
    ) -> list[TrackingLink]:
        stmt = (
            select(TrackingLink)
            .options(selectinload(TrackingLink.bot))
            .where(TrackingLink.project_id == project_id)
        )
        if bot_id is not None:
            stmt = stmt.where(TrackingLink.bot_id == bot_id)

        result = await self.db.execute(
            stmt.order_by(TrackingLink.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_project(
        self,
        project_id: UUID,
        bot_id: UUID | None = None,
    ) -> int:
        stmt = select(func.count(TrackingLink.id)).where(
            TrackingLink.project_id == project_id
        )
        if bot_id is not None:
            stmt = stmt.where(TrackingLink.bot_id == bot_id)

        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def delete_from_project(
        self,
        tracking_link_id: UUID,
        project_id: UUID,
    ) -> bool:
        result = await self.db.execute(
            delete(TrackingLink).where(
                TrackingLink.id == tracking_link_id,
                TrackingLink.project_id == project_id,
            )
        )
        return result.rowcount > 0

    async def get_traffic_stats(self, project_id: UUID):
        chat_counts = (
            select(
                Chat.tracking_link_id.label("tracking_link_id"),
                func.count(Chat.id).label("chat_clicks"),
            )
            .where(
                Chat.project_id == project_id,
                Chat.tracking_link_id.is_not(None),
                Chat.is_deleted.is_(False),
            )
            .group_by(Chat.tracking_link_id)
            .subquery()
        )
        lead_counts = (
            select(
                Chat.tracking_link_id.label("tracking_link_id"),
                func.count(Lead.id).label("leads"),
            )
            .join(Chat, Chat.id == Lead.chat_id)
            .where(
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                Chat.tracking_link_id.is_not(None),
                Chat.is_deleted.is_(False),
            )
            .group_by(Chat.tracking_link_id)
            .subquery()
        )
        event_counts = (
            select(
                TrackingEvent.tracking_link_id.label("tracking_link_id"),
                func.coalesce(func.sum(TrackingEvent.clicks), 0).label("event_clicks"),
                func.coalesce(func.sum(TrackingEvent.impressions), 0).label("impressions"),
            )
            .where(TrackingEvent.project_id == project_id)
            .group_by(TrackingEvent.tracking_link_id)
            .subquery()
        )

        result = await self.db.execute(
            select(
                TrackingLink,
                func.coalesce(chat_counts.c.chat_clicks, 0).label("chat_clicks"),
                func.coalesce(event_counts.c.event_clicks, 0).label("event_clicks"),
                func.coalesce(event_counts.c.impressions, 0).label("impressions"),
                func.coalesce(lead_counts.c.leads, 0).label("leads"),
            )
            .outerjoin(
                chat_counts,
                chat_counts.c.tracking_link_id == TrackingLink.id,
            )
            .outerjoin(
                event_counts,
                event_counts.c.tracking_link_id == TrackingLink.id,
            )
            .outerjoin(
                lead_counts,
                lead_counts.c.tracking_link_id == TrackingLink.id,
            )
            .where(TrackingLink.project_id == project_id)
            .order_by(TrackingLink.created_at.desc())
        )
        return result.all()
