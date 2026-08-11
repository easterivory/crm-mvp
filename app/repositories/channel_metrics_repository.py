from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel_tracking import (
    TelegramChannelSubscription,
    TelegramChannelSubscriptionEvent,
)
from app.models.tracking import TrackingLink


class ChannelMetricsRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def aggregate_by_link_ids(
        self,
        *,
        project_id: UUID,
        date_from: date,
        date_to: date,
        bot_id: UUID | None = None,
        buyer_id: UUID | None = None,
    ) -> dict[UUID, dict[str, int]]:
        start_at, end_at = self._date_bounds(date_from, date_to)
        statement = (
            select(
                TelegramChannelSubscriptionEvent.tracking_link_id.label("link_id"),
                func.count(
                    distinct(
                        case(
                            (
                                TelegramChannelSubscriptionEvent.event_type
                                == "join_request",
                                TelegramChannelSubscriptionEvent.telegram_user_id,
                            )
                        )
                    )
                ).label("channel_join_requests"),
                func.count(
                    distinct(
                        case(
                            (
                                TelegramChannelSubscriptionEvent.event_type == "join",
                                TelegramChannelSubscriptionEvent.telegram_user_id,
                            )
                        )
                    )
                ).label("channel_joins"),
                func.count(
                    distinct(
                        case(
                            (
                                TelegramChannelSubscriptionEvent.event_type.in_(
                                    ("leave", "kick")
                                ),
                                TelegramChannelSubscriptionEvent.telegram_user_id,
                            )
                        )
                    )
                ).label("channel_leaves"),
            )
            .join(
                TrackingLink,
                TrackingLink.id
                == TelegramChannelSubscriptionEvent.tracking_link_id,
            )
            .where(
                TelegramChannelSubscriptionEvent.project_id == project_id,
                TelegramChannelSubscriptionEvent.tracking_link_id.is_not(None),
                TelegramChannelSubscriptionEvent.occurred_at >= start_at,
                TelegramChannelSubscriptionEvent.occurred_at < end_at,
            )
            .group_by(TelegramChannelSubscriptionEvent.tracking_link_id)
        )
        if bot_id is not None:
            statement = statement.where(TrackingLink.bot_id == bot_id)
        if buyer_id is not None:
            statement = statement.where(TrackingLink.buyer_id == buyer_id)
        rows = (await self.db.execute(statement)).all()
        values = {
            row.link_id: {
                "channel_join_requests": int(row.channel_join_requests or 0),
                "channel_joins": int(row.channel_joins or 0),
                "channel_leaves": int(row.channel_leaves or 0),
                "channel_active_subscribers": 0,
            }
            for row in rows
        }

        active_statement = (
            select(
                TelegramChannelSubscription.tracking_link_id.label("link_id"),
                func.count(distinct(TelegramChannelSubscription.telegram_user_id)).label(
                    "active_subscribers"
                ),
            )
            .join(
                TrackingLink,
                TrackingLink.id == TelegramChannelSubscription.tracking_link_id,
            )
            .where(
                TelegramChannelSubscription.project_id == project_id,
                TelegramChannelSubscription.status == "member",
                TelegramChannelSubscription.tracking_link_id.is_not(None),
            )
            .group_by(TelegramChannelSubscription.tracking_link_id)
        )
        if bot_id is not None:
            active_statement = active_statement.where(TrackingLink.bot_id == bot_id)
        if buyer_id is not None:
            active_statement = active_statement.where(TrackingLink.buyer_id == buyer_id)
        for row in (await self.db.execute(active_statement)).all():
            values.setdefault(
                row.link_id,
                {
                    "channel_join_requests": 0,
                    "channel_joins": 0,
                    "channel_leaves": 0,
                    "channel_active_subscribers": 0,
                },
            )["channel_active_subscribers"] = int(row.active_subscribers or 0)
        return values

    async def aggregate_by_link(
        self,
        *,
        link_id: UUID,
        project_id: UUID,
        date_from: date,
        date_to: date,
    ) -> dict[str, int]:
        return (
            await self.aggregate_by_link_ids(
                project_id=project_id,
                date_from=date_from,
                date_to=date_to,
            )
        ).get(
            link_id,
            {
                "channel_join_requests": 0,
                "channel_joins": 0,
                "channel_leaves": 0,
                "channel_active_subscribers": 0,
            },
        )

    async def aggregate_daily(
        self,
        *,
        project_id: UUID,
        date_from: date,
        date_to: date,
        link_id: UUID | None = None,
        bot_id: UUID | None = None,
        buyer_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        start_at, end_at = self._date_bounds(date_from, date_to)
        metric_date = func.date(TelegramChannelSubscriptionEvent.occurred_at)
        statement = (
            select(
                metric_date.label("date"),
                TelegramChannelSubscriptionEvent.tracking_link_id.label("link_id"),
                TrackingLink.cost_model,
                TrackingLink.price_per_unit,
                func.count(
                    distinct(
                        case(
                            (
                                TelegramChannelSubscriptionEvent.event_type
                                == "join_request",
                                TelegramChannelSubscriptionEvent.telegram_user_id,
                            )
                        )
                    )
                ).label("channel_join_requests"),
                func.count(
                    distinct(
                        case(
                            (
                                TelegramChannelSubscriptionEvent.event_type == "join",
                                TelegramChannelSubscriptionEvent.telegram_user_id,
                            )
                        )
                    )
                ).label("channel_joins"),
                func.count(
                    distinct(
                        case(
                            (
                                TelegramChannelSubscriptionEvent.event_type.in_(
                                    ("leave", "kick")
                                ),
                                TelegramChannelSubscriptionEvent.telegram_user_id,
                            )
                        )
                    )
                ).label("channel_leaves"),
            )
            .join(
                TrackingLink,
                TrackingLink.id
                == TelegramChannelSubscriptionEvent.tracking_link_id,
            )
            .where(
                TelegramChannelSubscriptionEvent.project_id == project_id,
                TelegramChannelSubscriptionEvent.tracking_link_id.is_not(None),
                TelegramChannelSubscriptionEvent.occurred_at >= start_at,
                TelegramChannelSubscriptionEvent.occurred_at < end_at,
            )
            .group_by(
                metric_date,
                TelegramChannelSubscriptionEvent.tracking_link_id,
                TrackingLink.cost_model,
                TrackingLink.price_per_unit,
            )
            .order_by(metric_date)
        )
        if link_id is not None:
            statement = statement.where(
                TelegramChannelSubscriptionEvent.tracking_link_id == link_id
            )
        if bot_id is not None:
            statement = statement.where(TrackingLink.bot_id == bot_id)
        if buyer_id is not None:
            statement = statement.where(TrackingLink.buyer_id == buyer_id)
        daily: dict[date, dict[str, Any]] = {}
        for result_row in (await self.db.execute(statement)).all():
            metric_date_value = result_row.date
            row = daily.setdefault(
                metric_date_value,
                {
                    "date": metric_date_value,
                    "channel_join_requests": 0,
                    "channel_joins": 0,
                    "channel_leaves": 0,
                    "channel_fixed_spend": Decimal("0"),
                },
            )
            joins = int(result_row.channel_joins or 0)
            row["channel_join_requests"] += int(
                result_row.channel_join_requests or 0
            )
            row["channel_joins"] += joins
            row["channel_leaves"] += int(result_row.channel_leaves or 0)
            if str(result_row.cost_model) == "fix_pdp":
                row["channel_fixed_spend"] += Decimal(
                    result_row.price_per_unit or 0
                ) * Decimal(joins)
        return [daily[key] for key in sorted(daily)]

    @staticmethod
    def _date_bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
        return (
            datetime.combine(date_from, time.min, tzinfo=timezone.utc),
            datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc),
        )
