"""Database aggregations for tracking metrics."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import distinct, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LeadStatusCode, MessageType, SenderType
from app.models.bot import BotStep, ChatBotState
from app.models.chat import Chat
from app.models.lead import Lead
from app.models.lead_status import LeadStatus
from app.models.message import Message
from app.models.tracking import TrackingEvent, TrackingLink, TrackingSpend


SUBMITTED_STATUS_CODES = LeadStatusCode.SUBMITTED_SET
DEFAULT_TRACKING_LEAD_STATUS_CODES = LeadStatusCode.TRACKING_LEAD_DEFAULT


class TrackingMetricsRepository:
    """
    Repository-only aggregation layer.

    Current source of truth:
    - clicks: TrackingEvent.clicks grouped by TrackingEvent.created_at.
    - starts: unique Chat rows with an incoming Telegram /start message.
    - leads/submitted: Lead rows filtered by configured project lead statuses.
    - deposits/age/country: absent in current schema, returned as zero/empty.
    - funnel: current ChatBotState.current_step_id snapshot, not step history.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def aggregate_spend_by_project(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        date_from: date,
        date_to: date,
    ) -> Decimal:
        stmt = (
            select(func.coalesce(func.sum(TrackingSpend.amount), 0))
            .join(TrackingLink, TrackingLink.id == TrackingSpend.tracking_link_id)
            .where(
                TrackingLink.project_id == project_id,
                TrackingSpend.spend_date >= date_from,
                TrackingSpend.spend_date <= date_to,
            )
        )
        if bot_id is not None:
            stmt = stmt.where(TrackingLink.bot_id == bot_id)

        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def aggregate_spend_by_link(
        self,
        link_id: UUID,
        date_from: date,
        date_to: date,
    ) -> Decimal:
        result = await self.db.execute(
            select(func.coalesce(func.sum(TrackingSpend.amount), 0)).where(
                TrackingSpend.tracking_link_id == link_id,
                TrackingSpend.spend_date >= date_from,
                TrackingSpend.spend_date <= date_to,
            )
        )
        return result.scalar_one()

    async def aggregate_starts_by_project(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        date_from: date,
        date_to: date,
    ) -> int:
        start_at, end_at = self._date_bounds(date_from, date_to)
        stmt = (
            select(func.count(distinct(Chat.id)))
            .join(Message, Message.chat_id == Chat.id)
            .where(
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                Message.sender_type == SenderType.USER,
                Message.message_type == MessageType.TEXT,
                self._is_start_message(),
                Message.created_at >= start_at,
                Message.created_at < end_at,
            )
        )
        if bot_id is not None:
            stmt = stmt.where(Chat.bot_id == bot_id)

        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def aggregate_starts_by_link(
        self,
        link_id: UUID,
        date_from: date,
        date_to: date,
    ) -> int:
        start_at, end_at = self._date_bounds(date_from, date_to)
        result = await self.db.execute(
            select(func.count(distinct(Chat.id)))
            .join(Message, Message.chat_id == Chat.id)
            .where(
                Chat.tracking_link_id == link_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                Message.sender_type == SenderType.USER,
                Message.message_type == MessageType.TEXT,
                self._is_start_message(),
                Message.created_at >= start_at,
                Message.created_at < end_at,
            )
        )
        return result.scalar_one()

    async def aggregate_leads_by_project(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        date_from: date,
        date_to: date,
        lead_status_codes: Sequence[str] | None = None,
    ) -> int:
        return await self._aggregate_leads_by_project(
            project_id=project_id,
            bot_id=bot_id,
            date_from=date_from,
            date_to=date_to,
            submitted_only=False,
            lead_status_codes=lead_status_codes,
        )

    async def aggregate_leads_by_link(
        self,
        link_id: UUID,
        date_from: date,
        date_to: date,
        lead_status_codes: Sequence[str] | None = None,
    ) -> int:
        return await self._aggregate_leads_by_link(
            link_id=link_id,
            date_from=date_from,
            date_to=date_to,
            submitted_only=False,
            lead_status_codes=lead_status_codes,
        )

    async def aggregate_submitted_by_project(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        date_from: date,
        date_to: date,
    ) -> int:
        return await self._aggregate_leads_by_project(
            project_id=project_id,
            bot_id=bot_id,
            date_from=date_from,
            date_to=date_to,
            submitted_only=True,
        )

    async def aggregate_submitted_by_link(
        self,
        link_id: UUID,
        date_from: date,
        date_to: date,
    ) -> int:
        return await self._aggregate_leads_by_link(
            link_id=link_id,
            date_from=date_from,
            date_to=date_to,
            submitted_only=True,
        )

    async def aggregate_daily_by_project(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        date_from: date,
        date_to: date,
        lead_status_codes: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        daily = self._empty_daily_map()
        await self._merge_daily_clicks(daily, project_id, bot_id, None, date_from, date_to)
        await self._merge_daily_starts(daily, project_id, bot_id, None, date_from, date_to)
        await self._merge_daily_leads(
            daily,
            project_id,
            bot_id,
            None,
            date_from,
            date_to,
            submitted_only=False,
            lead_status_codes=lead_status_codes,
        )
        await self._merge_daily_leads(
            daily, project_id, bot_id, None, date_from, date_to, submitted_only=True
        )
        await self._merge_daily_spend(daily, project_id, bot_id, None, date_from, date_to)
        return self._daily_rows(daily)

    async def aggregate_daily_by_link(
        self,
        link_id: UUID,
        date_from: date,
        date_to: date,
        lead_status_codes: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        daily = self._empty_daily_map()
        await self._merge_daily_clicks(daily, None, None, link_id, date_from, date_to)
        await self._merge_daily_starts(daily, None, None, link_id, date_from, date_to)
        await self._merge_daily_leads(
            daily,
            None,
            None,
            link_id,
            date_from,
            date_to,
            submitted_only=False,
            lead_status_codes=lead_status_codes,
        )
        await self._merge_daily_leads(
            daily, None, None, link_id, date_from, date_to, submitted_only=True
        )
        await self._merge_daily_spend(daily, None, None, link_id, date_from, date_to)
        return self._daily_rows(daily)

    async def get_link_metrics_rows(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        date_from: date,
        date_to: date,
        lead_status_codes: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        link_rows = await self._get_base_link_rows(project_id, bot_id)
        if not link_rows:
            return []

        rows_by_id = {
            row["link_id"]: {
                **row,
                "clicks": 0,
                "starts": 0,
                "leads": 0,
                "submitted_leads": 0,
                "deposits": 0,
                "spend": Decimal("0"),
            }
            for row in link_rows
        }

        await self._merge_link_clicks(rows_by_id, project_id, bot_id, date_from, date_to)
        await self._merge_link_starts(rows_by_id, project_id, bot_id, date_from, date_to)
        await self._merge_link_leads(
            rows_by_id,
            project_id,
            bot_id,
            date_from,
            date_to,
            submitted_only=False,
            lead_status_codes=lead_status_codes,
        )
        await self._merge_link_leads(
            rows_by_id, project_id, bot_id, date_from, date_to, submitted_only=True
        )
        await self._merge_link_spend(rows_by_id, project_id, bot_id, date_from, date_to)

        return list(rows_by_id.values())

    async def get_age_breakdown_by_link(
        self,
        link_id: UUID,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        return []

    async def get_country_breakdown_by_link(
        self,
        link_id: UUID,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        return []

    async def get_funnel_breakdown_by_link(
        self,
        link_id: UUID,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        start_at, end_at = self._date_bounds(date_from, date_to)
        lifecycle_at = self._chat_lifecycle_at()
        result = await self.db.execute(
            select(
                BotStep.id.label("step_id"),
                BotStep.step_type.label("step_type"),
                BotStep.config.label("config"),
                BotStep.created_at.label("created_at"),
                func.count(distinct(Chat.id)).label("count"),
            )
            .join(ChatBotState, ChatBotState.current_step_id == BotStep.id)
            .join(Chat, Chat.id == ChatBotState.chat_id)
            .where(
                Chat.tracking_link_id == link_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                lifecycle_at >= start_at,
                lifecycle_at < end_at,
            )
            .group_by(BotStep.id)
            .order_by(BotStep.created_at.asc())
        )
        return [
            {
                "step_key": str(row.step_id),
                "label": self._step_label(row.step_type, row.config),
                "count": row.count or 0,
            }
            for row in result.all()
        ]

    async def _aggregate_leads_by_project(
        self,
        *,
        project_id: UUID,
        bot_id: UUID | None,
        date_from: date,
        date_to: date,
        submitted_only: bool,
        lead_status_codes: Sequence[str] | None = None,
    ) -> int:
        start_at, end_at = self._date_bounds(date_from, date_to)
        lifecycle_at = self._lead_lifecycle_at()
        stmt = (
            select(func.count(distinct(Lead.id)))
            .join(Chat, Chat.id == Lead.chat_id)
            .where(
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                lifecycle_at >= start_at,
                lifecycle_at < end_at,
            )
        )
        if bot_id is not None:
            stmt = stmt.where(Chat.bot_id == bot_id)
        stmt = self._apply_lead_status_filter(
            stmt,
            submitted_only=submitted_only,
            lead_status_codes=lead_status_codes,
        )

        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def _aggregate_leads_by_link(
        self,
        *,
        link_id: UUID,
        date_from: date,
        date_to: date,
        submitted_only: bool,
        lead_status_codes: Sequence[str] | None = None,
    ) -> int:
        start_at, end_at = self._date_bounds(date_from, date_to)
        lifecycle_at = self._lead_lifecycle_at()
        stmt = (
            select(func.count(distinct(Lead.id)))
            .join(Chat, Chat.id == Lead.chat_id)
            .where(
                Chat.tracking_link_id == link_id,
                Lead.is_deleted.is_(False),
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                lifecycle_at >= start_at,
                lifecycle_at < end_at,
            )
        )
        stmt = self._apply_lead_status_filter(
            stmt,
            submitted_only=submitted_only,
            lead_status_codes=lead_status_codes,
        )

        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def _get_base_link_rows(
        self,
        project_id: UUID,
        bot_id: UUID | None,
    ) -> list[dict[str, Any]]:
        stmt = select(
            TrackingLink.id.label("link_id"),
            TrackingLink.code,
            TrackingLink.title,
            TrackingLink.buyer_name,
            TrackingLink.ad_type,
            TrackingLink.payment_type,
            TrackingLink.is_active,
            TrackingLink.base_conversion_rate,
            TrackingLink.min_sample_size,
        ).where(TrackingLink.project_id == project_id)
        if bot_id is not None:
            stmt = stmt.where(TrackingLink.bot_id == bot_id)

        result = await self.db.execute(stmt.order_by(TrackingLink.created_at.desc()))
        return [dict(row._mapping) for row in result.all()]

    async def _merge_link_clicks(
        self,
        rows_by_id: dict[UUID, dict[str, Any]],
        project_id: UUID,
        bot_id: UUID | None,
        date_from: date,
        date_to: date,
    ) -> None:
        start_at, end_at = self._date_bounds(date_from, date_to)
        stmt = (
            select(
                TrackingEvent.tracking_link_id.label("link_id"),
                func.coalesce(func.sum(TrackingEvent.clicks), 0).label("clicks"),
            )
            .join(TrackingLink, TrackingLink.id == TrackingEvent.tracking_link_id)
            .where(
                TrackingLink.project_id == project_id,
                TrackingEvent.created_at >= start_at,
                TrackingEvent.created_at < end_at,
            )
            .group_by(TrackingEvent.tracking_link_id)
        )
        if bot_id is not None:
            stmt = stmt.where(TrackingLink.bot_id == bot_id)

        result = await self.db.execute(stmt)
        for row in result.all():
            if row.link_id in rows_by_id:
                rows_by_id[row.link_id]["clicks"] = row.clicks or 0

    async def _merge_link_starts(
        self,
        rows_by_id: dict[UUID, dict[str, Any]],
        project_id: UUID,
        bot_id: UUID | None,
        date_from: date,
        date_to: date,
    ) -> None:
        start_at, end_at = self._date_bounds(date_from, date_to)
        stmt = (
            select(
                Chat.tracking_link_id.label("link_id"),
                func.count(distinct(Chat.id)).label("starts"),
            )
            .join(Message, Message.chat_id == Chat.id)
            .where(
                Chat.project_id == project_id,
                Chat.tracking_link_id.is_not(None),
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                Message.sender_type == SenderType.USER,
                Message.message_type == MessageType.TEXT,
                self._is_start_message(),
                Message.created_at >= start_at,
                Message.created_at < end_at,
            )
            .group_by(Chat.tracking_link_id)
        )
        if bot_id is not None:
            stmt = stmt.where(Chat.bot_id == bot_id)

        result = await self.db.execute(stmt)
        for row in result.all():
            if row.link_id in rows_by_id:
                rows_by_id[row.link_id]["starts"] = row.starts or 0

    async def _merge_link_leads(
        self,
        rows_by_id: dict[UUID, dict[str, Any]],
        project_id: UUID,
        bot_id: UUID | None,
        date_from: date,
        date_to: date,
        *,
        submitted_only: bool,
        lead_status_codes: Sequence[str] | None = None,
    ) -> None:
        start_at, end_at = self._date_bounds(date_from, date_to)
        lifecycle_at = self._lead_lifecycle_at()
        stmt = (
            select(
                Chat.tracking_link_id.label("link_id"),
                func.count(distinct(Lead.id)).label("lead_count"),
            )
            .join(Chat, Chat.id == Lead.chat_id)
            .where(
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                Chat.tracking_link_id.is_not(None),
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                lifecycle_at >= start_at,
                lifecycle_at < end_at,
            )
            .group_by(Chat.tracking_link_id)
        )
        if bot_id is not None:
            stmt = stmt.where(Chat.bot_id == bot_id)
        stmt = self._apply_lead_status_filter(
            stmt,
            submitted_only=submitted_only,
            lead_status_codes=lead_status_codes,
        )

        result = await self.db.execute(stmt)
        target_field = "submitted_leads" if submitted_only else "leads"
        for row in result.all():
            if row.link_id in rows_by_id:
                rows_by_id[row.link_id][target_field] = row.lead_count or 0

    async def _merge_link_spend(
        self,
        rows_by_id: dict[UUID, dict[str, Any]],
        project_id: UUID,
        bot_id: UUID | None,
        date_from: date,
        date_to: date,
    ) -> None:
        stmt = (
            select(
                TrackingSpend.tracking_link_id.label("link_id"),
                func.coalesce(func.sum(TrackingSpend.amount), 0).label("spend"),
            )
            .join(TrackingLink, TrackingLink.id == TrackingSpend.tracking_link_id)
            .where(
                TrackingLink.project_id == project_id,
                TrackingSpend.spend_date >= date_from,
                TrackingSpend.spend_date <= date_to,
            )
            .group_by(TrackingSpend.tracking_link_id)
        )
        if bot_id is not None:
            stmt = stmt.where(TrackingLink.bot_id == bot_id)

        result = await self.db.execute(stmt)
        for row in result.all():
            if row.link_id in rows_by_id:
                rows_by_id[row.link_id]["spend"] = row.spend or Decimal("0")

    async def _merge_daily_clicks(
        self,
        daily: dict[date, dict[str, Any]],
        project_id: UUID | None,
        bot_id: UUID | None,
        link_id: UUID | None,
        date_from: date,
        date_to: date,
    ) -> None:
        start_at, end_at = self._date_bounds(date_from, date_to)
        metric_date = func.date(TrackingEvent.created_at)
        stmt = (
            select(
                metric_date.label("metric_date"),
                func.coalesce(func.sum(TrackingEvent.clicks), 0).label("clicks"),
            )
            .join(TrackingLink, TrackingLink.id == TrackingEvent.tracking_link_id)
            .where(TrackingEvent.created_at >= start_at, TrackingEvent.created_at < end_at)
            .group_by(metric_date)
        )
        stmt = self._apply_link_scope(stmt, project_id, bot_id, link_id)

        result = await self.db.execute(stmt)
        for row in result.all():
            self._ensure_daily(daily, row.metric_date)["clicks"] = row.clicks or 0

    async def _merge_daily_starts(
        self,
        daily: dict[date, dict[str, Any]],
        project_id: UUID | None,
        bot_id: UUID | None,
        link_id: UUID | None,
        date_from: date,
        date_to: date,
    ) -> None:
        start_at, end_at = self._date_bounds(date_from, date_to)
        metric_date = func.date(Message.created_at)
        stmt = (
            select(
                metric_date.label("metric_date"),
                func.count(distinct(Chat.id)).label("starts"),
            )
            .join(Message, Message.chat_id == Chat.id)
            .where(
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                Message.sender_type == SenderType.USER,
                Message.message_type == MessageType.TEXT,
                self._is_start_message(),
                Message.created_at >= start_at,
                Message.created_at < end_at,
            )
            .group_by(metric_date)
        )
        if project_id is not None:
            stmt = stmt.where(Chat.project_id == project_id)
        if bot_id is not None:
            stmt = stmt.where(Chat.bot_id == bot_id)
        if link_id is not None:
            stmt = stmt.where(Chat.tracking_link_id == link_id)

        result = await self.db.execute(stmt)
        for row in result.all():
            self._ensure_daily(daily, row.metric_date)["starts"] = row.starts or 0

    async def _merge_daily_leads(
        self,
        daily: dict[date, dict[str, Any]],
        project_id: UUID | None,
        bot_id: UUID | None,
        link_id: UUID | None,
        date_from: date,
        date_to: date,
        *,
        submitted_only: bool,
        lead_status_codes: Sequence[str] | None = None,
    ) -> None:
        start_at, end_at = self._date_bounds(date_from, date_to)
        lifecycle_at = self._lead_lifecycle_at()
        metric_date = func.date(lifecycle_at)
        stmt = (
            select(
                metric_date.label("metric_date"),
                func.count(distinct(Lead.id)).label("lead_count"),
            )
            .join(Chat, Chat.id == Lead.chat_id)
            .where(
                Lead.is_deleted.is_(False),
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                lifecycle_at >= start_at,
                lifecycle_at < end_at,
            )
            .group_by(metric_date)
        )
        if project_id is not None:
            stmt = stmt.where(Lead.project_id == project_id)
        if bot_id is not None:
            stmt = stmt.where(Chat.bot_id == bot_id)
        if link_id is not None:
            stmt = stmt.where(Chat.tracking_link_id == link_id)
        stmt = self._apply_lead_status_filter(
            stmt,
            submitted_only=submitted_only,
            lead_status_codes=lead_status_codes,
        )

        result = await self.db.execute(stmt)
        target_field = "submitted_leads" if submitted_only else "leads"
        for row in result.all():
            self._ensure_daily(daily, row.metric_date)[target_field] = (
                row.lead_count or 0
            )

    async def _merge_daily_spend(
        self,
        daily: dict[date, dict[str, Any]],
        project_id: UUID | None,
        bot_id: UUID | None,
        link_id: UUID | None,
        date_from: date,
        date_to: date,
    ) -> None:
        stmt = (
            select(
                TrackingSpend.spend_date.label("metric_date"),
                func.coalesce(func.sum(TrackingSpend.amount), 0).label("spend"),
            )
            .join(TrackingLink, TrackingLink.id == TrackingSpend.tracking_link_id)
            .where(
                TrackingSpend.spend_date >= date_from,
                TrackingSpend.spend_date <= date_to,
            )
            .group_by(TrackingSpend.spend_date)
        )
        stmt = self._apply_link_scope(stmt, project_id, bot_id, link_id)

        result = await self.db.execute(stmt)
        for row in result.all():
            self._ensure_daily(daily, row.metric_date)["spend"] = (
                row.spend or Decimal("0")
            )

    @staticmethod
    def _apply_link_scope(
        stmt,
        project_id: UUID | None,
        bot_id: UUID | None,
        link_id: UUID | None,
    ):
        if project_id is not None:
            stmt = stmt.where(TrackingLink.project_id == project_id)
        if bot_id is not None:
            stmt = stmt.where(TrackingLink.bot_id == bot_id)
        if link_id is not None:
            stmt = stmt.where(TrackingLink.id == link_id)
        return stmt

    @classmethod
    def _apply_lead_status_filter(
        cls,
        stmt,
        *,
        submitted_only: bool,
        lead_status_codes: Sequence[str] | None,
    ):
        status_codes = (
            tuple(SUBMITTED_STATUS_CODES)
            if submitted_only
            else cls._normalize_lead_status_codes(lead_status_codes)
        )
        stmt = stmt.join(LeadStatus, LeadStatus.id == Lead.status_id)
        if not status_codes:
            return stmt.where(false())
        return stmt.where(LeadStatus.code.in_(status_codes))

    @staticmethod
    def _normalize_lead_status_codes(
        lead_status_codes: Sequence[str] | None,
    ) -> tuple[str, ...]:
        source = (
            DEFAULT_TRACKING_LEAD_STATUS_CODES
            if lead_status_codes is None
            else lead_status_codes
        )
        normalized: list[str] = []
        for raw_code in source:
            code = raw_code.strip().lower()
            if code and code not in normalized:
                normalized.append(code)
        return tuple(normalized)

    @staticmethod
    def _empty_daily_map() -> dict[date, dict[str, Any]]:
        return {}

    @staticmethod
    def _ensure_daily(daily: dict[date, dict[str, Any]], metric_date) -> dict[str, Any]:
        if isinstance(metric_date, datetime):
            metric_date = metric_date.date()
        if metric_date not in daily:
            daily[metric_date] = {
                "date": metric_date,
                "clicks": 0,
                "starts": 0,
                "leads": 0,
                "submitted_leads": 0,
                "deposits": 0,
                "spend": Decimal("0"),
            }
        return daily[metric_date]

    @staticmethod
    def _daily_rows(daily: dict[date, dict[str, Any]]) -> list[dict[str, Any]]:
        return [daily[key] for key in sorted(daily.keys())]

    @staticmethod
    def _date_bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
        start_at = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        end_at = datetime.combine(date_to, time.min, tzinfo=timezone.utc) + timedelta(days=1)
        return start_at, end_at

    @staticmethod
    def _chat_lifecycle_at():
        return func.coalesce(Chat.current_cycle_started_at, Chat.created_at)

    @staticmethod
    def _lead_lifecycle_at():
        return func.coalesce(Chat.current_cycle_started_at, Lead.created_at)

    @staticmethod
    def _is_start_message():
        command = func.split_part(func.lower(func.trim(Message.body)), " ", 1)
        return or_(command == "/start", command.like("/start@%"))

    @staticmethod
    def _step_label(step_type: str, config: dict[str, Any] | None) -> str:
        if config:
            for key in ("label", "title", "name", "text"):
                value = config.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return step_type
