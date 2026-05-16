"""
Tracking repository.

Tracking links are project-scoped attribution sources for Telegram /start
payloads. ref_code is kept for backward compatibility with the existing
webhook path; code is the v1 canonical field and is synchronized by service.
"""
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload

from app.models.chat import Chat
from app.models.lead import Lead
from app.models.tracking import TrackingEvent
from app.models.tracking import TrackingLink
from app.models.tracking import TrackingSpend
from app.repositories.base import BaseRepository


class TrackingLinkRepository(BaseRepository[TrackingLink]):
    model = TrackingLink

    async def create_link(self, **values) -> TrackingLink:
        return await self.create(**values)

    async def get_link_by_id(self, link_id: UUID) -> Optional[TrackingLink]:
        result = await self.db.execute(
            select(TrackingLink)
            .options(selectinload(TrackingLink.bot))
            .where(TrackingLink.id == link_id)
        )
        return result.scalar_one_or_none()

    async def get_link_by_code(self, code: str) -> Optional[TrackingLink]:
        result = await self.db.execute(
            select(TrackingLink)
            .options(selectinload(TrackingLink.bot))
            .where(TrackingLink.code == code)
        )
        return result.scalar_one_or_none()

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

    async def list_links(
        self,
        project_id: UUID,
        limit: int = 50,
        offset: int = 0,
        bot_id: UUID | None = None,
        is_active: bool | None = None,
    ) -> list[TrackingLink]:
        stmt = (
            select(TrackingLink)
            .options(selectinload(TrackingLink.bot))
            .where(TrackingLink.project_id == project_id)
        )
        if bot_id is not None:
            stmt = stmt.where(TrackingLink.bot_id == bot_id)
        if is_active is not None:
            stmt = stmt.where(TrackingLink.is_active.is_(is_active))

        result = await self.db.execute(
            stmt.order_by(TrackingLink.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def count_links(
        self,
        project_id: UUID,
        bot_id: UUID | None = None,
        is_active: bool | None = None,
    ) -> int:
        stmt = select(func.count(TrackingLink.id)).where(
            TrackingLink.project_id == project_id
        )
        if bot_id is not None:
            stmt = stmt.where(TrackingLink.bot_id == bot_id)
        if is_active is not None:
            stmt = stmt.where(TrackingLink.is_active.is_(is_active))

        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def update_link(self, link_id: UUID, **values) -> Optional[TrackingLink]:
        values["updated_at"] = func.now()
        result = await self.db.execute(
            update(TrackingLink).where(TrackingLink.id == link_id).values(**values)
        )
        if result.rowcount == 0:
            return None
        return await self.get_link_by_id(link_id)

    async def set_active(self, link_id: UUID, is_active: bool) -> Optional[TrackingLink]:
        return await self.update_link(link_id, is_active=is_active)

    async def list_by_project(
        self,
        project_id: UUID,
        limit: int = 50,
        offset: int = 0,
        bot_id: UUID | None = None,
    ) -> list[TrackingLink]:
        return await self.list_links(
            project_id=project_id,
            limit=limit,
            offset=offset,
            bot_id=bot_id,
        )

    async def count_by_project(
        self,
        project_id: UUID,
        bot_id: UUID | None = None,
    ) -> int:
        return await self.count_links(project_id=project_id, bot_id=bot_id)

    async def delete_from_project(
        self,
        tracking_link_id: UUID,
        project_id: UUID,
    ) -> bool:
        await self.db.execute(
            delete(TrackingSpend).where(TrackingSpend.tracking_link_id == tracking_link_id)
        )
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


class TrackingSpendRepository(BaseRepository[TrackingSpend]):
    model = TrackingSpend

    async def create_spend(self, **values) -> TrackingSpend:
        return await self.create(**values)

    async def get_spend_by_id(self, spend_id: UUID) -> Optional[TrackingSpend]:
        result = await self.db.execute(
            select(TrackingSpend).where(TrackingSpend.id == spend_id)
        )
        return result.scalar_one_or_none()

    async def list_spends(
        self,
        tracking_link_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[TrackingSpend]:
        stmt = select(TrackingSpend).where(
            TrackingSpend.tracking_link_id == tracking_link_id
        )
        if date_from is not None:
            stmt = stmt.where(TrackingSpend.spend_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(TrackingSpend.spend_date <= date_to)

        result = await self.db.execute(
            stmt.order_by(TrackingSpend.spend_date.desc(), TrackingSpend.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_spend(self, spend_id: UUID, **values) -> Optional[TrackingSpend]:
        values["updated_at"] = func.now()
        result = await self.db.execute(
            update(TrackingSpend).where(TrackingSpend.id == spend_id).values(**values)
        )
        if result.rowcount == 0:
            return None
        return await self.get_spend_by_id(spend_id)

    async def delete_spend(self, spend_id: UUID) -> bool:
        result = await self.db.execute(
            delete(TrackingSpend).where(TrackingSpend.id == spend_id)
        )
        return result.rowcount > 0

    async def sum_spend_by_link(self, tracking_link_id: UUID) -> Decimal:
        result = await self.db.execute(
            select(func.coalesce(func.sum(TrackingSpend.amount), 0)).where(
                TrackingSpend.tracking_link_id == tracking_link_id
            )
        )
        return result.scalar_one()

    async def sum_spend_by_project(self, project_id: UUID) -> Decimal:
        result = await self.db.execute(
            select(func.coalesce(func.sum(TrackingSpend.amount), 0))
            .join(TrackingLink, TrackingLink.id == TrackingSpend.tracking_link_id)
            .where(TrackingLink.project_id == project_id)
        )
        return result.scalar_one()


class TrackingRepository(TrackingLinkRepository):
    """Backward-compatible name used by existing analytics and Telegram code."""
