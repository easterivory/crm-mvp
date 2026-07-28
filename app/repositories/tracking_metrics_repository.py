"""Database aggregations for tracking metrics."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import case, distinct, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LeadStatusCode, MessageType, SenderType, TrackingCostModel
from app.models.bot import BotStep, ChatBotState
from app.models.chat import Chat
from app.models.lead import Lead
from app.models.lead_status import LeadStatus
from app.models.message import Message
from app.models.partner import LeadSubmission
from app.models.tracking import TrackingEvent, TrackingLink, TrackingSpend
from app.services.tracking_cost_service import calculate_tracking_spend


SUCCESSFUL_SUBMISSION_STATUSES = ("success", "completed")
DEFAULT_TRACKING_LEAD_STATUS_CODES = LeadStatusCode.TRACKING_LEAD_DEFAULT


class TrackingMetricsRepository:
    """
    Repository-only aggregation layer.

    Sources of truth:
    - clicks: TrackingEvent.clicks grouped by TrackingEvent.created_at.
    - starts: unique Chat rows with an incoming Telegram /start message.
    - leads: Lead rows filtered by configured project lead statuses.
    - submitted: the first successful LeadSubmission for each lead.
    - demographic breakdowns: active leads grouped by fields stored on Lead.
    - funnel: current ChatBotState.current_step_id snapshot, not step history.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def aggregate_clicks_by_project(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        date_from: date,
        date_to: date,
        *,
        buyer_id: UUID | None = None,
    ) -> int:
        start_at, end_at = self._date_bounds(date_from, date_to)
        stmt = (
            select(func.coalesce(func.sum(TrackingEvent.clicks), 0))
            .join(TrackingLink, TrackingLink.id == TrackingEvent.tracking_link_id)
            .where(
                TrackingLink.project_id == project_id,
                TrackingEvent.created_at >= start_at,
                TrackingEvent.created_at < end_at,
            )
        )
        if bot_id is not None:
            stmt = stmt.where(TrackingLink.bot_id == bot_id)
        if buyer_id is not None:
            stmt = stmt.where(TrackingLink.buyer_id == buyer_id)
        return int((await self.db.execute(stmt)).scalar_one() or 0)

    async def aggregate_clicks_by_link(
        self,
        link_id: UUID,
        date_from: date,
        date_to: date,
    ) -> int:
        start_at, end_at = self._date_bounds(date_from, date_to)
        result = await self.db.execute(
            select(func.coalesce(func.sum(TrackingEvent.clicks), 0)).where(
                TrackingEvent.tracking_link_id == link_id,
                TrackingEvent.created_at >= start_at,
                TrackingEvent.created_at < end_at,
            )
        )
        return int(result.scalar_one() or 0)

    async def aggregate_spend_by_project(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        date_from: date,
        date_to: date,
    ) -> Decimal:
        daily: dict[date, dict[str, Any]] = {}
        await self._merge_daily_modeled_spend(
            daily,
            project_id=project_id,
            bot_id=bot_id,
            date_from=date_from,
            date_to=date_to,
        )
        return sum(
            (Decimal(item["spend"] or 0) for item in daily.values()),
            Decimal("0"),
        )

    async def aggregate_spend_by_link(
        self,
        link_id: UUID,
        date_from: date,
        date_to: date,
    ) -> Decimal:
        link_result = await self.db.execute(
            select(
                TrackingLink.cost_model,
                TrackingLink.price_per_unit,
            ).where(TrackingLink.id == link_id)
        )
        link_row = link_result.one_or_none()
        if link_row is None:
            return Decimal("0")

        result = await self.db.execute(
            select(func.coalesce(func.sum(TrackingSpend.amount), 0)).where(
                TrackingSpend.tracking_link_id == link_id,
                TrackingSpend.spend_date >= date_from,
                TrackingSpend.spend_date <= date_to,
            )
        )
        manual_spend = Decimal(result.scalar_one() or 0)
        starts = await self.aggregate_starts_by_link(link_id, date_from, date_to)
        submitted = await self.aggregate_submitted_by_link(link_id, date_from, date_to)
        return calculate_tracking_spend(
            cost_model=link_row.cost_model,
            price_per_unit=Decimal(link_row.price_per_unit or 0),
            manual_spend=manual_spend,
            starts=int(starts or 0),
            submitted_leads=int(submitted or 0),
        )

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

    async def aggregate_starts_unattributed_by_project(
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
                Chat.tracking_link_id.is_(None),
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
        return int((await self.db.execute(stmt)).scalar_one() or 0)

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

    async def aggregate_leads_unattributed_by_project(
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
            unattributed_only=True,
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

    async def aggregate_submitted_unattributed_by_project(
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
            unattributed_only=True,
        )

    async def aggregate_daily_by_project(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        date_from: date,
        date_to: date,
        lead_status_codes: Sequence[str] | None = None,
        buyer_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        daily = self._empty_daily_map()
        await self._merge_daily_clicks(
            daily, project_id, bot_id, None, date_from, date_to, buyer_id=buyer_id
        )
        await self._merge_daily_starts(
            daily, project_id, bot_id, None, date_from, date_to, buyer_id=buyer_id
        )
        await self._merge_daily_leads(
            daily,
            project_id,
            bot_id,
            None,
            date_from,
            date_to,
            submitted_only=False,
            lead_status_codes=lead_status_codes,
            buyer_id=buyer_id,
        )
        await self._merge_daily_leads(
            daily,
            project_id,
            bot_id,
            None,
            date_from,
            date_to,
            submitted_only=True,
            buyer_id=buyer_id,
        )
        await self._merge_daily_modeled_spend(
            daily,
            project_id=project_id,
            bot_id=bot_id,
            date_from=date_from,
            date_to=date_to,
            buyer_id=buyer_id,
        )
        return self._daily_rows(daily)

    async def aggregate_daily_unattributed_by_project(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        date_from: date,
        date_to: date,
        lead_status_codes: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Daily metrics for Telegram starts/leads that have no tracking_link_id.

        Clicks and spend belong to tracking links, so direct traffic returns
        zero for those fields while preserving starts/leads/submitted by day.
        """
        daily = self._empty_daily_map()
        await self._merge_daily_starts(
            daily,
            project_id,
            bot_id,
            None,
            date_from,
            date_to,
            unattributed_only=True,
        )
        await self._merge_daily_leads(
            daily,
            project_id,
            bot_id,
            None,
            date_from,
            date_to,
            submitted_only=False,
            lead_status_codes=lead_status_codes,
            unattributed_only=True,
        )
        await self._merge_daily_leads(
            daily,
            project_id,
            bot_id,
            None,
            date_from,
            date_to,
            submitted_only=True,
            unattributed_only=True,
        )
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
        await self._apply_link_daily_cost_model(daily, link_id)
        return self._daily_rows(daily)

    async def get_link_metrics_rows(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        date_from: date,
        date_to: date,
        lead_status_codes: Sequence[str] | None = None,
        buyer_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        link_rows = await self._get_base_link_rows(project_id, bot_id, buyer_id)
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
                "registrations": 0,
                "first_deposits": 0,
                "redeposits": 0,
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
        for row in rows_by_id.values():
            row["spend"] = calculate_tracking_spend(
                cost_model=row["cost_model"],
                price_per_unit=Decimal(row["price_per_unit"] or 0),
                manual_spend=Decimal(row["spend"] or 0),
                starts=int(row["starts"] or 0),
                submitted_leads=int(row["submitted_leads"] or 0),
            )

        return list(rows_by_id.values())

    async def get_age_breakdown_by_link(
        self,
        link_id: UUID,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        age_key = case(
            (Lead.age.is_(None), "unknown"),
            (Lead.age < 18, "under_18"),
            (Lead.age <= 24, "18_24"),
            (Lead.age <= 34, "25_34"),
            (Lead.age <= 44, "35_44"),
            (Lead.age <= 54, "45_54"),
            else_="55_plus",
        )
        age_label = case(
            (Lead.age.is_(None), "Не указан"),
            (Lead.age < 18, "До 18"),
            (Lead.age <= 24, "18–24"),
            (Lead.age <= 34, "25–34"),
            (Lead.age <= 44, "35–44"),
            (Lead.age <= 54, "45–54"),
            else_="55+",
        )
        return await self._get_lead_breakdown_by_link(
            link_id=link_id,
            date_from=date_from,
            date_to=date_to,
            key_expression=age_key,
            label_expression=age_label,
        )

    async def get_country_breakdown_by_link(
        self,
        link_id: UUID,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        country = func.nullif(func.btrim(Lead.country), "")
        return await self._get_lead_breakdown_by_link(
            link_id=link_id,
            date_from=date_from,
            date_to=date_to,
            key_expression=func.coalesce(func.lower(country), "unknown"),
            label_expression=func.coalesce(func.initcap(func.lower(country)), "Не указана"),
        )

    async def get_city_breakdown_by_link(
        self,
        link_id: UUID,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        city = func.nullif(func.btrim(Lead.custom_fields["city"].astext), "")
        return await self._get_lead_breakdown_by_link(
            link_id=link_id,
            date_from=date_from,
            date_to=date_to,
            key_expression=func.coalesce(func.lower(city), "unknown"),
            label_expression=func.coalesce(func.initcap(func.lower(city)), "Не указан"),
        )

    async def get_status_breakdown_by_link(
        self,
        link_id: UUID,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        return await self._get_lead_breakdown_by_link(
            link_id=link_id,
            date_from=date_from,
            date_to=date_to,
            key_expression=LeadStatus.code,
            label_expression=LeadStatus.name,
            join_status=True,
        )

    async def get_card_breakdown_by_link(
        self,
        link_id: UUID,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        card_key = case(
            (Lead.has_card.is_(True), "yes"),
            (Lead.has_card.is_(False), "no"),
            else_="unknown",
        )
        card_label = case(
            (Lead.has_card.is_(True), "Есть карта"),
            (Lead.has_card.is_(False), "Нет карты"),
            else_="Не указано",
        )
        return await self._get_lead_breakdown_by_link(
            link_id=link_id,
            date_from=date_from,
            date_to=date_to,
            key_expression=card_key,
            label_expression=card_label,
        )

    async def _get_lead_breakdown_by_link(
        self,
        *,
        link_id: UUID,
        date_from: date,
        date_to: date,
        key_expression,
        label_expression,
        join_status: bool = False,
    ) -> list[dict[str, Any]]:
        start_at, end_at = self._date_bounds(date_from, date_to)
        lifecycle_at = self._lead_lifecycle_at()
        stmt = (
            select(
                key_expression.label("key"),
                label_expression.label("label"),
                func.count(distinct(Lead.id)).label("count"),
            )
            .select_from(Lead)
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
        if join_status:
            stmt = stmt.join(LeadStatus, LeadStatus.id == Lead.status_id)
        result = await self.db.execute(
            stmt.group_by(key_expression, label_expression).order_by(
                func.count(distinct(Lead.id)).desc(),
                label_expression.asc(),
            )
        )
        return [
            {
                "key": str(row.key),
                "label": str(row.label),
                "count": int(row.count or 0),
            }
            for row in result.all()
        ]

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
        unattributed_only: bool = False,
    ) -> int:
        if submitted_only:
            return await self._aggregate_successful_submissions(
                project_id=project_id,
                bot_id=bot_id,
                link_id=None,
                date_from=date_from,
                date_to=date_to,
                unattributed_only=unattributed_only,
            )
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
        if unattributed_only:
            stmt = stmt.where(Chat.tracking_link_id.is_(None))
        stmt = self._apply_lead_status_filter(
            stmt,
            submitted_only=False,
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
        if submitted_only:
            return await self._aggregate_successful_submissions(
                project_id=None,
                bot_id=None,
                link_id=link_id,
                date_from=date_from,
                date_to=date_to,
            )
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
            submitted_only=False,
            lead_status_codes=lead_status_codes,
        )

        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def _get_base_link_rows(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        buyer_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(
            TrackingLink.id.label("link_id"),
            TrackingLink.code,
            TrackingLink.title,
            TrackingLink.buyer_id,
            TrackingLink.buyer_name,
            TrackingLink.ad_type,
            TrackingLink.payment_type,
            TrackingLink.is_active,
            TrackingLink.cost_model,
            TrackingLink.price_per_unit,
            TrackingLink.base_conversion_rate,
            TrackingLink.min_sample_size,
        ).where(TrackingLink.project_id == project_id)
        if bot_id is not None:
            stmt = stmt.where(TrackingLink.bot_id == bot_id)
        if buyer_id is not None:
            stmt = stmt.where(TrackingLink.buyer_id == buyer_id)

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
        if submitted_only:
            await self._merge_link_successful_submissions(
                rows_by_id=rows_by_id,
                project_id=project_id,
                bot_id=bot_id,
                date_from=date_from,
                date_to=date_to,
            )
            return
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
            submitted_only=False,
            lead_status_codes=lead_status_codes,
        )

        result = await self.db.execute(stmt)
        for row in result.all():
            if row.link_id in rows_by_id:
                rows_by_id[row.link_id]["leads"] = row.lead_count or 0

    async def _aggregate_successful_submissions(
        self,
        *,
        project_id: UUID | None,
        bot_id: UUID | None,
        link_id: UUID | None,
        date_from: date,
        date_to: date,
        unattributed_only: bool = False,
        buyer_id: UUID | None = None,
    ) -> int:
        submissions = self._first_successful_submissions()
        start_at, end_at = self._date_bounds(date_from, date_to)
        stmt = select(func.count()).select_from(submissions).where(
            submissions.c.success_number == 1,
            submissions.c.occurred_at >= start_at,
            submissions.c.occurred_at < end_at,
        )
        stmt = self._apply_submission_scope(
            stmt,
            submissions,
            project_id=project_id,
            bot_id=bot_id,
            link_id=link_id,
            unattributed_only=unattributed_only,
            buyer_id=buyer_id,
        )
        return int((await self.db.execute(stmt)).scalar_one() or 0)

    async def _merge_link_successful_submissions(
        self,
        *,
        rows_by_id: dict[UUID, dict[str, Any]],
        project_id: UUID,
        bot_id: UUID | None,
        date_from: date,
        date_to: date,
    ) -> None:
        submissions = self._first_successful_submissions()
        start_at, end_at = self._date_bounds(date_from, date_to)
        stmt = (
            select(
                submissions.c.tracking_link_id.label("link_id"),
                func.count().label("submitted_leads"),
            )
            .select_from(submissions)
            .where(
                submissions.c.success_number == 1,
                submissions.c.tracking_link_id.is_not(None),
                submissions.c.occurred_at >= start_at,
                submissions.c.occurred_at < end_at,
            )
            .group_by(submissions.c.tracking_link_id)
        )
        stmt = self._apply_submission_scope(
            stmt,
            submissions,
            project_id=project_id,
            bot_id=bot_id,
        )
        result = await self.db.execute(stmt)
        for row in result.all():
            if row.link_id in rows_by_id:
                rows_by_id[row.link_id]["submitted_leads"] = int(
                    row.submitted_leads or 0
                )

    async def _merge_daily_successful_submissions(
        self,
        *,
        daily: dict[date, dict[str, Any]],
        project_id: UUID | None,
        bot_id: UUID | None,
        link_id: UUID | None,
        date_from: date,
        date_to: date,
        unattributed_only: bool,
        buyer_id: UUID | None,
    ) -> None:
        submissions = self._first_successful_submissions()
        start_at, end_at = self._date_bounds(date_from, date_to)
        metric_date = func.date(submissions.c.occurred_at)
        stmt = (
            select(
                metric_date.label("metric_date"),
                func.count().label("submitted_leads"),
            )
            .select_from(submissions)
            .where(
                submissions.c.success_number == 1,
                submissions.c.occurred_at >= start_at,
                submissions.c.occurred_at < end_at,
            )
            .group_by(metric_date)
        )
        stmt = self._apply_submission_scope(
            stmt,
            submissions,
            project_id=project_id,
            bot_id=bot_id,
            link_id=link_id,
            unattributed_only=unattributed_only,
            buyer_id=buyer_id,
        )
        result = await self.db.execute(stmt)
        for row in result.all():
            self._ensure_daily(daily, row.metric_date)["submitted_leads"] = int(
                row.submitted_leads or 0
            )

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
        *,
        buyer_id: UUID | None = None,
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
        if buyer_id is not None:
            stmt = stmt.where(TrackingLink.buyer_id == buyer_id)

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
        *,
        unattributed_only: bool = False,
        buyer_id: UUID | None = None,
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
        if unattributed_only:
            stmt = stmt.where(Chat.tracking_link_id.is_(None))
        if buyer_id is not None:
            stmt = stmt.join(TrackingLink, TrackingLink.id == Chat.tracking_link_id).where(
                TrackingLink.buyer_id == buyer_id
            )

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
        unattributed_only: bool = False,
        buyer_id: UUID | None = None,
    ) -> None:
        if submitted_only:
            await self._merge_daily_successful_submissions(
                daily=daily,
                project_id=project_id,
                bot_id=bot_id,
                link_id=link_id,
                date_from=date_from,
                date_to=date_to,
                unattributed_only=unattributed_only,
                buyer_id=buyer_id,
            )
            return
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
        if unattributed_only:
            stmt = stmt.where(Chat.tracking_link_id.is_(None))
        if buyer_id is not None:
            stmt = stmt.join(TrackingLink, TrackingLink.id == Chat.tracking_link_id).where(
                TrackingLink.buyer_id == buyer_id
            )
        stmt = self._apply_lead_status_filter(
            stmt,
            submitted_only=False,
            lead_status_codes=lead_status_codes,
        )

        result = await self.db.execute(stmt)
        for row in result.all():
            self._ensure_daily(daily, row.metric_date)["leads"] = (
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

    async def _apply_link_daily_cost_model(
        self,
        daily: dict[date, dict[str, Any]],
        link_id: UUID,
    ) -> None:
        result = await self.db.execute(
            select(TrackingLink.cost_model, TrackingLink.price_per_unit).where(
                TrackingLink.id == link_id
            )
        )
        row = result.one_or_none()
        if row is None:
            return
        for item in daily.values():
            item["spend"] = calculate_tracking_spend(
                cost_model=row.cost_model,
                price_per_unit=Decimal(row.price_per_unit or 0),
                manual_spend=Decimal(item["spend"] or 0),
                starts=int(item["starts"] or 0),
                submitted_leads=int(item["submitted_leads"] or 0),
            )

    async def _merge_daily_modeled_spend(
        self,
        daily: dict[date, dict[str, Any]],
        *,
        project_id: UUID,
        bot_id: UUID | None,
        date_from: date,
        date_to: date,
        buyer_id: UUID | None = None,
    ) -> None:
        manual_stmt = (
            select(
                TrackingSpend.spend_date.label("metric_date"),
                func.coalesce(func.sum(TrackingSpend.amount), 0).label("spend"),
            )
            .join(TrackingLink, TrackingLink.id == TrackingSpend.tracking_link_id)
            .where(
                TrackingLink.project_id == project_id,
                TrackingLink.cost_model == TrackingCostModel.CPM,
                TrackingSpend.spend_date >= date_from,
                TrackingSpend.spend_date <= date_to,
            )
            .group_by(TrackingSpend.spend_date)
        )
        if bot_id is not None:
            manual_stmt = manual_stmt.where(TrackingLink.bot_id == bot_id)
        if buyer_id is not None:
            manual_stmt = manual_stmt.where(TrackingLink.buyer_id == buyer_id)
        manual_result = await self.db.execute(manual_stmt)
        for row in manual_result.all():
            self._ensure_daily(daily, row.metric_date)["spend"] += Decimal(row.spend or 0)

        start_at, end_at = self._date_bounds(date_from, date_to)
        start_date = func.date(Message.created_at)
        fixed_stmt = (
            select(
                start_date.label("metric_date"),
                TrackingLink.id.label("link_id"),
                TrackingLink.price_per_unit,
                func.count(distinct(Chat.id)).label("units"),
            )
            .select_from(Chat)
            .join(Message, Message.chat_id == Chat.id)
            .join(TrackingLink, TrackingLink.id == Chat.tracking_link_id)
            .where(
                TrackingLink.project_id == project_id,
                TrackingLink.cost_model == TrackingCostModel.FIX_PDP,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                Message.sender_type == SenderType.USER,
                Message.message_type == MessageType.TEXT,
                self._is_start_message(),
                Message.created_at >= start_at,
                Message.created_at < end_at,
            )
            .group_by(start_date, TrackingLink.id, TrackingLink.price_per_unit)
        )
        if bot_id is not None:
            fixed_stmt = fixed_stmt.where(TrackingLink.bot_id == bot_id)
        if buyer_id is not None:
            fixed_stmt = fixed_stmt.where(TrackingLink.buyer_id == buyer_id)
        fixed_result = await self.db.execute(fixed_stmt)
        for row in fixed_result.all():
            amount = Decimal(row.units or 0) * Decimal(row.price_per_unit or 0)
            self._ensure_daily(daily, row.metric_date)["spend"] += amount

        submissions = self._first_successful_submissions()
        submitted_date = func.date(submissions.c.occurred_at)
        submitted_stmt = (
            select(
                submitted_date.label("metric_date"),
                TrackingLink.id.label("link_id"),
                TrackingLink.price_per_unit,
                func.count().label("units"),
            )
            .select_from(submissions)
            .join(
                TrackingLink,
                TrackingLink.id == submissions.c.tracking_link_id,
            )
            .where(
                TrackingLink.project_id == project_id,
                TrackingLink.cost_model == TrackingCostModel.CPA,
                submissions.c.success_number == 1,
                submissions.c.occurred_at >= start_at,
                submissions.c.occurred_at < end_at,
            )
            .group_by(submitted_date, TrackingLink.id, TrackingLink.price_per_unit)
        )
        if bot_id is not None:
            submitted_stmt = submitted_stmt.where(TrackingLink.bot_id == bot_id)
        if buyer_id is not None:
            submitted_stmt = submitted_stmt.where(TrackingLink.buyer_id == buyer_id)
        submitted_result = await self.db.execute(submitted_stmt)
        for row in submitted_result.all():
            amount = Decimal(row.units or 0) * Decimal(row.price_per_unit or 0)
            self._ensure_daily(daily, row.metric_date)["spend"] += amount

    @staticmethod
    def _first_successful_submissions():
        occurred_at = func.coalesce(
            LeadSubmission.completed_at,
            LeadSubmission.submitted_at,
        )
        tracking_link_id = func.coalesce(
            LeadSubmission.tracking_link_id,
            Chat.tracking_link_id,
        )
        return (
            select(
                LeadSubmission.id,
                LeadSubmission.lead_id,
                Lead.project_id,
                Chat.bot_id,
                tracking_link_id.label("tracking_link_id"),
                occurred_at.label("occurred_at"),
                func.row_number()
                .over(
                    partition_by=LeadSubmission.lead_id,
                    order_by=(occurred_at.asc(), LeadSubmission.id.asc()),
                )
                .label("success_number"),
            )
            .select_from(LeadSubmission)
            .join(Lead, Lead.id == LeadSubmission.lead_id)
            .join(Chat, Chat.id == Lead.chat_id)
            .where(
                func.lower(LeadSubmission.status).in_(
                    SUCCESSFUL_SUBMISSION_STATUSES
                )
            )
            .subquery("first_successful_submissions")
        )

    @staticmethod
    def _apply_submission_scope(
        stmt,
        submissions,
        *,
        project_id: UUID | None = None,
        bot_id: UUID | None = None,
        link_id: UUID | None = None,
        unattributed_only: bool = False,
        buyer_id: UUID | None = None,
    ):
        if project_id is not None:
            stmt = stmt.where(submissions.c.project_id == project_id)
        if bot_id is not None:
            stmt = stmt.where(submissions.c.bot_id == bot_id)
        if link_id is not None:
            stmt = stmt.where(submissions.c.tracking_link_id == link_id)
        if unattributed_only:
            stmt = stmt.where(submissions.c.tracking_link_id.is_(None))
        if buyer_id is not None:
            stmt = stmt.join(
                TrackingLink,
                TrackingLink.id == submissions.c.tracking_link_id,
            ).where(TrackingLink.buyer_id == buyer_id)
        return stmt

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
        if submitted_only:
            raise ValueError("Submission metrics must use lead_submissions")
        status_codes = cls._normalize_lead_status_codes(lead_status_codes)
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
