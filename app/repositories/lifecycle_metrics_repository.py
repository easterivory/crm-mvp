"""Canonical registration, first-deposit, and redeposit analytics."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat
from app.models.funnel import ChatFunnelState
from app.models.lead import Lead
from app.models.lead_event import LeadEvent
from app.models.tracking import TrackingLink


REGISTRATION_EVENT_TYPES = ("registration", "reg")
FIRST_DEPOSIT_EVENT_TYPES = ("deposit", "first_deposit", "first-deposit", "fd")
REDEPOSIT_EVENT_TYPES = ("redeposit", "re_deposit", "re-deposit", "rd")
LIFECYCLE_EVENT_TYPES = (
    *REGISTRATION_EVENT_TYPES,
    *FIRST_DEPOSIT_EVENT_TYPES,
    *REDEPOSIT_EVENT_TYPES,
)


class LifecycleMetricsRepository:
    """
    Aggregates lifecycle events independently of their source.

    Registration and first deposit are unique lead milestones. Only the first
    event of each kind is counted even if a tag, funnel action, and postback all
    report it. Redeposits are repeatable and every idempotent event is counted.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def aggregate_counts(
        self,
        *,
        project_id: UUID,
        date_from: date,
        date_to: date,
        bot_id: UUID | None = None,
        link_id: UUID | None = None,
        unattributed_only: bool = False,
        buyer_id: UUID | None = None,
        funnel_version_id: UUID | None = None,
    ) -> dict[str, int]:
        events = self._eligible_events(project_id)
        start_at, end_at = self._date_bounds(date_from, date_to)
        stmt = (
            select(
                func.count().filter(events.c.event_type == "registration").label(
                    "registrations"
                ),
                func.count().filter(events.c.event_type == "deposit").label(
                    "first_deposits"
                ),
                func.count().filter(events.c.event_type == "redeposit").label(
                    "redeposits"
                ),
            )
            .select_from(events)
            .where(events.c.occurred_at >= start_at, events.c.occurred_at < end_at)
        )
        stmt = self._apply_scope(
            stmt,
            events,
            bot_id=bot_id,
            link_id=link_id,
            unattributed_only=unattributed_only,
            buyer_id=buyer_id,
            funnel_version_id=funnel_version_id,
        )
        row = (await self.db.execute(stmt)).one()
        return self._count_row(row)

    async def aggregate_daily(
        self,
        *,
        project_id: UUID,
        date_from: date,
        date_to: date,
        bot_id: UUID | None = None,
        link_id: UUID | None = None,
        unattributed_only: bool = False,
        buyer_id: UUID | None = None,
        funnel_version_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        events = self._eligible_events(project_id)
        start_at, end_at = self._date_bounds(date_from, date_to)
        metric_date = func.date(events.c.occurred_at)
        stmt = (
            select(
                metric_date.label("date"),
                func.count().filter(events.c.event_type == "registration").label(
                    "registrations"
                ),
                func.count().filter(events.c.event_type == "deposit").label(
                    "first_deposits"
                ),
                func.count().filter(events.c.event_type == "redeposit").label(
                    "redeposits"
                ),
            )
            .select_from(events)
            .where(events.c.occurred_at >= start_at, events.c.occurred_at < end_at)
            .group_by(metric_date)
            .order_by(metric_date)
        )
        stmt = self._apply_scope(
            stmt,
            events,
            bot_id=bot_id,
            link_id=link_id,
            unattributed_only=unattributed_only,
            buyer_id=buyer_id,
            funnel_version_id=funnel_version_id,
        )
        result = await self.db.execute(stmt)
        return [
            {"date": row.date, **self._count_row(row)}
            for row in result.all()
        ]

    async def aggregate_by_link(
        self,
        *,
        project_id: UUID,
        date_from: date,
        date_to: date,
        bot_id: UUID | None = None,
        buyer_id: UUID | None = None,
    ) -> dict[UUID, dict[str, int]]:
        events = self._eligible_events(project_id)
        start_at, end_at = self._date_bounds(date_from, date_to)
        stmt = (
            select(
                events.c.tracking_link_id.label("link_id"),
                func.count().filter(events.c.event_type == "registration").label(
                    "registrations"
                ),
                func.count().filter(events.c.event_type == "deposit").label(
                    "first_deposits"
                ),
                func.count().filter(events.c.event_type == "redeposit").label(
                    "redeposits"
                ),
            )
            .select_from(events)
            .where(
                events.c.tracking_link_id.is_not(None),
                events.c.occurred_at >= start_at,
                events.c.occurred_at < end_at,
            )
            .group_by(events.c.tracking_link_id)
        )
        stmt = self._apply_scope(
            stmt,
            events,
            bot_id=bot_id,
            buyer_id=buyer_id,
        )
        result = await self.db.execute(stmt)
        return {
            row.link_id: self._count_row(row)
            for row in result.all()
        }

    async def aggregate_by_source(
        self,
        *,
        project_id: UUID,
        date_from: date,
        date_to: date,
        bot_id: UUID | None = None,
        link_id: UUID | None = None,
        buyer_id: UUID | None = None,
        funnel_version_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        events = self._eligible_events(project_id)
        start_at, end_at = self._date_bounds(date_from, date_to)
        stmt = (
            select(
                events.c.source,
                func.count().filter(events.c.event_type == "registration").label(
                    "registrations"
                ),
                func.count().filter(events.c.event_type == "deposit").label(
                    "first_deposits"
                ),
                func.count().filter(events.c.event_type == "redeposit").label(
                    "redeposits"
                ),
            )
            .select_from(events)
            .where(events.c.occurred_at >= start_at, events.c.occurred_at < end_at)
            .group_by(events.c.source)
            .order_by(events.c.source)
        )
        stmt = self._apply_scope(
            stmt,
            events,
            bot_id=bot_id,
            link_id=link_id,
            buyer_id=buyer_id,
            funnel_version_id=funnel_version_id,
        )
        result = await self.db.execute(stmt)
        return [
            {"source": row.source, **self._count_row(row)}
            for row in result.all()
        ]

    @staticmethod
    def _canonical_type():
        return case(
            (
                LeadEvent.event_type.in_(REGISTRATION_EVENT_TYPES),
                literal("registration"),
            ),
            (
                LeadEvent.event_type.in_(FIRST_DEPOSIT_EVENT_TYPES),
                literal("deposit"),
            ),
            (
                LeadEvent.event_type.in_(REDEPOSIT_EVENT_TYPES),
                literal("redeposit"),
            ),
            else_=None,
        )

    @classmethod
    def _eligible_events(cls, project_id: UUID):
        canonical_type = cls._canonical_type()
        tracking_link_id = func.coalesce(
            LeadEvent.tracking_link_id,
            Chat.tracking_link_id,
        )
        funnel_id = func.coalesce(LeadEvent.funnel_id, ChatFunnelState.funnel_id)
        funnel_version_id = func.coalesce(
            LeadEvent.funnel_version_id,
            ChatFunnelState.funnel_version_id,
        )
        ranked = (
            select(
                LeadEvent.id,
                LeadEvent.lead_id,
                LeadEvent.source,
                LeadEvent.occurred_at,
                LeadEvent.attributed_manager_id,
                Chat.bot_id,
                tracking_link_id.label("tracking_link_id"),
                funnel_id.label("funnel_id"),
                funnel_version_id.label("funnel_version_id"),
                canonical_type.label("event_type"),
                func.row_number()
                .over(
                    partition_by=(LeadEvent.lead_id, canonical_type),
                    order_by=(LeadEvent.occurred_at.asc(), LeadEvent.id.asc()),
                )
                .label("milestone_number"),
            )
            .select_from(LeadEvent)
            .join(Lead, Lead.id == LeadEvent.lead_id)
            .join(Chat, Chat.id == Lead.chat_id)
            .outerjoin(ChatFunnelState, ChatFunnelState.chat_id == Chat.id)
            .where(
                LeadEvent.project_id == project_id,
                LeadEvent.event_type.in_(LIFECYCLE_EVENT_TYPES),
            )
            .subquery("ranked_lifecycle_events")
        )
        return (
            select(ranked)
            .where(
                or_(
                    ranked.c.event_type == "redeposit",
                    ranked.c.milestone_number == 1,
                )
            )
            .subquery("eligible_lifecycle_events")
        )

    @staticmethod
    def _apply_scope(
        stmt,
        events,
        *,
        bot_id: UUID | None = None,
        link_id: UUID | None = None,
        unattributed_only: bool = False,
        buyer_id: UUID | None = None,
        funnel_version_id: UUID | None = None,
    ):
        if bot_id is not None:
            stmt = stmt.where(events.c.bot_id == bot_id)
        if link_id is not None:
            stmt = stmt.where(events.c.tracking_link_id == link_id)
        if unattributed_only:
            stmt = stmt.where(events.c.tracking_link_id.is_(None))
        if buyer_id is not None:
            stmt = stmt.join(
                TrackingLink,
                TrackingLink.id == events.c.tracking_link_id,
            ).where(TrackingLink.buyer_id == buyer_id)
        if funnel_version_id is not None:
            stmt = stmt.where(events.c.funnel_version_id == funnel_version_id)
        return stmt

    @staticmethod
    def _count_row(row) -> dict[str, int]:
        return {
            "registrations": int(row.registrations or 0),
            "first_deposits": int(row.first_deposits or 0),
            "redeposits": int(row.redeposits or 0),
        }

    @staticmethod
    def _date_bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
        start_at = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        end_at = datetime.combine(date_to, time.min, tzinfo=timezone.utc) + timedelta(days=1)
        return start_at, end_at
