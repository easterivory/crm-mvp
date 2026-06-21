from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import case, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LeadStatusCode
from app.models.chat import Chat
from app.models.funnel import FunnelStep, FunnelStepLog
from app.models.lead import Lead
from app.models.lead_status import LeadStatus
from app.models.role import Role
from app.models.tracking import TrackingEvent, TrackingLink, TrackingSpend
from app.models.user import User, UserProjectAccess
from app.schemas.buyer import BuyerFunnelDropOffStepOut, BuyerPerformanceOut


class BuyerAnalyticsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_funnel_dropoff_by_telegram_id(
        self,
        buyer_telegram_id: int,
    ) -> list[BuyerFunnelDropOffStepOut]:
        buyer = await self._get_buyer_by_telegram_id(buyer_telegram_id)
        rows = await self._get_funnel_rows_for_buyer(buyer.id)
        return self._build_dropoff_rows(rows)

    async def get_project_performance(
        self,
        project_id: UUID,
    ) -> list[BuyerPerformanceOut]:
        link_counts = (
            select(
                TrackingLink.buyer_id.label("buyer_id"),
                func.count(distinct(TrackingLink.id)).label("links_count"),
            )
            .where(
                TrackingLink.project_id == project_id,
                TrackingLink.buyer_id.is_not(None),
            )
            .group_by(TrackingLink.buyer_id)
            .subquery()
        )
        spend_totals = (
            select(
                TrackingLink.buyer_id.label("buyer_id"),
                func.coalesce(func.sum(TrackingSpend.amount), 0).label("total_spend"),
            )
            .join(TrackingLink, TrackingLink.id == TrackingSpend.tracking_link_id)
            .where(
                TrackingLink.project_id == project_id,
                TrackingLink.buyer_id.is_not(None),
            )
            .group_by(TrackingLink.buyer_id)
            .subquery()
        )
        click_totals = (
            select(
                TrackingLink.buyer_id.label("buyer_id"),
                func.coalesce(func.sum(TrackingEvent.clicks), 0).label("clicks"),
            )
            .join(TrackingLink, TrackingLink.id == TrackingEvent.tracking_link_id)
            .where(
                TrackingLink.project_id == project_id,
                TrackingLink.buyer_id.is_not(None),
            )
            .group_by(TrackingLink.buyer_id)
            .subquery()
        )
        lead_totals = (
            select(
                TrackingLink.buyer_id.label("buyer_id"),
                func.count(distinct(Lead.id)).label("leads"),
            )
            .join(Chat, Chat.id == Lead.chat_id)
            .join(TrackingLink, TrackingLink.id == Chat.tracking_link_id)
            .where(
                TrackingLink.project_id == project_id,
                TrackingLink.buyer_id.is_not(None),
                Lead.is_deleted.is_(False),
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
            )
            .group_by(TrackingLink.buyer_id)
            .subquery()
        )
        submitted_totals = (
            select(
                TrackingLink.buyer_id.label("buyer_id"),
                func.count(distinct(Lead.id)).label("submitted_leads"),
            )
            .join(Chat, Chat.id == Lead.chat_id)
            .join(TrackingLink, TrackingLink.id == Chat.tracking_link_id)
            .join(LeadStatus, LeadStatus.id == Lead.status_id)
            .where(
                TrackingLink.project_id == project_id,
                TrackingLink.buyer_id.is_not(None),
                Lead.is_deleted.is_(False),
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                LeadStatus.code.in_(LeadStatusCode.SUBMITTED_SET),
            )
            .group_by(TrackingLink.buyer_id)
            .subquery()
        )

        result = await self.db.execute(
            select(
                User.id.label("buyer_id"),
                User.name,
                User.email,
                User.buyer_telegram_id,
                func.coalesce(link_counts.c.links_count, 0).label("links_count"),
                func.coalesce(spend_totals.c.total_spend, 0).label("total_spend"),
                func.coalesce(click_totals.c.clicks, 0).label("clicks"),
                func.coalesce(lead_totals.c.leads, 0).label("leads"),
                func.coalesce(submitted_totals.c.submitted_leads, 0).label("submitted_leads"),
            )
            .join(Role, Role.id == User.role_id)
            .outerjoin(link_counts, link_counts.c.buyer_id == User.id)
            .outerjoin(spend_totals, spend_totals.c.buyer_id == User.id)
            .outerjoin(click_totals, click_totals.c.buyer_id == User.id)
            .outerjoin(lead_totals, lead_totals.c.buyer_id == User.id)
            .outerjoin(submitted_totals, submitted_totals.c.buyer_id == User.id)
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
                Role.name.in_(("manager", "buyer")),
            )
            .order_by(User.name.asc(), User.created_at.desc())
        )

        items: list[BuyerPerformanceOut] = []
        for row in result.mappings().all():
            spend = money(Decimal(row["total_spend"] or 0))
            clicks = int(row["clicks"] or 0)
            leads = int(row["leads"] or 0)
            submitted = int(row["submitted_leads"] or 0)
            items.append(
                BuyerPerformanceOut(
                    buyer_id=row["buyer_id"],
                    name=row["name"],
                    email=row["email"],
                    buyer_telegram_id=row["buyer_telegram_id"],
                    links_count=int(row["links_count"] or 0),
                    total_spend=spend,
                    clicks=clicks,
                    leads=leads,
                    lead_conversion_percent=ratio_percent(leads, clicks),
                    cpl=money(spend / Decimal(leads)) if leads > 0 else Decimal("0.00"),
                    submitted_leads=submitted,
                    submitted_conversion_percent=ratio_percent(submitted, leads),
                )
            )
        return items

    async def _get_buyer_by_telegram_id(self, buyer_telegram_id: int) -> User:
        result = await self.db.execute(
            select(User).where(
                User.buyer_telegram_id == buyer_telegram_id,
                User.is_deleted.is_(False),
            )
        )
        buyer = result.scalar_one_or_none()
        if buyer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Buyer was not found by Telegram ID",
            )
        return buyer

    async def _get_funnel_rows_for_buyer(self, buyer_id: UUID) -> list[dict]:
        entered_lead = case(
            (FunnelStepLog.event_type == "entered", FunnelStepLog.lead_id),
            else_=None,
        )
        completed_lead = case(
            (FunnelStepLog.event_type != "entered", FunnelStepLog.lead_id),
            else_=None,
        )
        first_seen = func.min(FunnelStepLog.created_at)
        result = await self.db.execute(
            select(
                FunnelStepLog.step_id.label("step_id"),
                func.coalesce(FunnelStep.title, FunnelStepLog.step_name).label("step_title"),
                FunnelStep.position_x.label("position_x"),
                FunnelStep.position_y.label("position_y"),
                first_seen.label("first_seen_at"),
                func.count(distinct(entered_lead)).label("entered_count"),
                func.count(distinct(completed_lead)).label("completed_count"),
            )
            .join(Lead, Lead.id == FunnelStepLog.lead_id)
            .join(Chat, Chat.id == Lead.chat_id)
            .join(TrackingLink, TrackingLink.id == Chat.tracking_link_id)
            .outerjoin(FunnelStep, FunnelStep.id == FunnelStepLog.step_id)
            .where(
                TrackingLink.buyer_id == buyer_id,
                Lead.is_deleted.is_(False),
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
            )
            .group_by(
                FunnelStepLog.step_id,
                FunnelStep.title,
                FunnelStepLog.step_name,
                FunnelStep.position_x,
                FunnelStep.position_y,
            )
            .order_by(
                FunnelStep.position_x.asc().nullslast(),
                FunnelStep.position_y.asc().nullslast(),
                first_seen.asc(),
            )
        )
        return [dict(row) for row in result.mappings().all()]

    @staticmethod
    def _build_dropoff_rows(rows: list[dict]) -> list[BuyerFunnelDropOffStepOut]:
        if not rows:
            return []

        first_count = int(rows[0].get("entered_count") or 0)
        previous_entered = first_count
        output: list[BuyerFunnelDropOffStepOut] = []
        for index, row in enumerate(rows):
            entered_count = int(row.get("entered_count") or 0)
            completed_count = int(row.get("completed_count") or 0)
            dropoff_count = 0 if index == 0 else max(previous_entered - entered_count, 0)
            output.append(
                BuyerFunnelDropOffStepOut(
                    step_id=row.get("step_id"),
                    step_title=str(row.get("step_title") or row.get("step_id")),
                    entered_count=entered_count,
                    completed_count=completed_count,
                    dropoff_count=dropoff_count,
                    reached_percent=ratio_percent(entered_count, first_count),
                    dropoff_percent=ratio_percent(dropoff_count, previous_entered),
                )
            )
            previous_entered = entered_count
        return output


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ratio_percent(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return Decimal("0.0")
    return (Decimal(numerator) / Decimal(denominator) * Decimal("100")).quantize(
        Decimal("0.1"),
        rounding=ROUND_HALF_UP,
    )
