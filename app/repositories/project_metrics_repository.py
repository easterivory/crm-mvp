from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat
from app.models.lead import Lead
from app.models.partner import LeadSubmission
from app.models.tracking import TrackingLink, TrackingSpend


class ProjectMetricsRepository:
    """Small project-scoped aggregates for the admin header."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def header_metrics(self, project_id: UUID, day: date) -> dict:
        start_at = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end_at = start_at + timedelta(days=1)

        leads_result = await self.db.execute(
            select(func.count(distinct(Lead.id))).where(
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                Lead.created_at >= start_at,
                Lead.created_at < end_at,
            )
        )
        chats_result = await self.db.execute(
            select(func.count(distinct(Chat.id))).where(
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                Chat.created_at >= start_at,
                Chat.created_at < end_at,
            )
        )
        submitted_result = await self.db.execute(
            select(func.count(distinct(LeadSubmission.lead_id)))
            .join(Lead, Lead.id == LeadSubmission.lead_id)
            .where(
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                LeadSubmission.status.in_(("success", "completed")),
                LeadSubmission.completed_at >= start_at,
                LeadSubmission.completed_at < end_at,
            )
        )
        spend_result = await self.db.execute(
            select(func.coalesce(func.sum(TrackingSpend.amount), 0))
            .join(TrackingLink, TrackingLink.id == TrackingSpend.tracking_link_id)
            .where(
                TrackingLink.project_id == project_id,
                TrackingSpend.spend_date == day,
            )
        )
        leads = int(leads_result.scalar_one() or 0)
        chats = int(chats_result.scalar_one() or 0)
        submitted = int(submitted_result.scalar_one() or 0)
        spend = Decimal(spend_result.scalar_one() or 0)
        cpl = spend / Decimal(leads) if leads > 0 else Decimal("0")
        conversion = (
            Decimal(leads) / Decimal(chats) * Decimal("100")
            if chats > 0
            else Decimal("0")
        )
        submitted_percent = (
            Decimal(submitted) / Decimal(leads) * Decimal("100")
            if leads > 0
            else Decimal("0")
        )
        cost_per_submitted = spend / Decimal(submitted) if submitted > 0 else Decimal("0")
        return {
            "date": day,
            "subscribers_today": chats,
            "conversion_today": conversion,
            "leads_today": leads,
            "chats_today": chats,
            "submitted_today": submitted,
            "submitted_percent_today": submitted_percent,
            "spend_today": spend,
            "cpl_today": cpl,
            "cost_per_submitted_today": cost_per_submitted,
        }
