"""Read-only tracking reports, using CRM aggregations with Moscow day bounds."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from uuid import UUID

from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.tracking import TrackingLink
from app.repositories.tracking_metrics_repository import TrackingMetricsRepository
from app.repositories.channel_metrics_repository import ChannelMetricsRepository
from app.repositories.lifecycle_metrics_repository import LifecycleMetricsRepository
from app.services.tracking_metrics_service import TrackingMetricsService

MOSCOW = ZoneInfo("Europe/Moscow")


def today_moscow() -> date:
    return datetime.now(MOSCOW).date()


def period_bounds(kind: str, offset: int = 0, today: date | None = None) -> tuple[date, date]:
    today = today or today_moscow()
    if kind == "week":
        start = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
        return start, start + timedelta(days=6)
    if kind == "month":
        month = today.year * 12 + today.month - 1 + offset
        start = date(month // 12, month % 12 + 1, 1)
        next_month = month + 1
        return start, date(next_month // 12, next_month % 12 + 1, 1) - timedelta(days=1)
    if kind == "all":
        return date(1970, 1, 1), today
    raise ValueError("Unknown report period")


def parse_custom_period(value: str) -> tuple[date, date]:
    parts = value.split()
    if len(parts) != 2:
        raise ValueError("Введите две даты: 01.10.2026 11.10.2026")
    try:
        start, end = (datetime.strptime(part, "%d.%m.%Y").date() for part in parts)
    except ValueError as exc:
        raise ValueError("Формат дат: ДД.ММ.ГГГГ ДД.ММ.ГГГГ") from exc
    if start > end or start < date(1970, 1, 1) or end > today_moscow():
        raise ValueError("Начало должно быть не позже конца, даты - не позже сегодня.")
    return start, end


class MoscowDayBounds:
    @staticmethod
    def _date_bounds(date_from: date, date_to: date):
        return (
            datetime.combine(date_from, time.min, tzinfo=MOSCOW),
            datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=MOSCOW),
        )


class InfoTrackingMetricsRepository(MoscowDayBounds, TrackingMetricsRepository):
    pass


class InfoChannelMetricsRepository(MoscowDayBounds, ChannelMetricsRepository):
    pass


class InfoLifecycleMetricsRepository(MoscowDayBounds, LifecycleMetricsRepository):
    pass


class InfoBotReports:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.tracking = InfoTrackingMetricsRepository(db)
        self.channels = InfoChannelMetricsRepository(db)
        self.lifecycle = InfoLifecycleMetricsRepository(db)

    async def summary(self, project: Project, start: date, end: date,
                      link: TrackingLink | None = None, bot_id: UUID | None = None) -> dict:
        codes = TrackingMetricsService._tracking_lead_status_codes(project)
        if link:
            values = {
                "clicks": await self.tracking.aggregate_clicks_by_link(link.id, start, end),
                "starts": await self.tracking.aggregate_starts_by_link(link.id, start, end),
                "leads": await self.tracking.aggregate_leads_by_link(link.id, start, end, codes),
                "submitted_leads": 0 if project.project_format == "gambling" else await self.tracking.aggregate_submitted_by_link(link.id, start, end),
            }
        else:
            values = {
                "clicks": await self.tracking.aggregate_clicks_by_project(project.id, bot_id, start, end),
                "starts": await self.tracking.aggregate_starts_by_project(project.id, bot_id, start, end),
                "leads": await self.tracking.aggregate_leads_by_project(project.id, bot_id, start, end, codes),
                "submitted_leads": 0 if project.project_format == "gambling" else await self.tracking.aggregate_submitted_by_project(project.id, bot_id, start, end),
            }
        values.update(await self.lifecycle.aggregate_counts(
            project_id=project.id, bot_id=bot_id, link_id=link.id if link else None, date_from=start, date_to=end))
        channels = await self.channels.aggregate_by_link_ids(project_id=project.id, bot_id=bot_id, date_from=start, date_to=end)
        channel_rows = [channels.get(link.id, {})] if link else list(channels.values())
        for key in ("channel_joins", "channel_leaves", "channel_join_requests", "channel_active_subscribers"):
            values[key] = sum(row.get(key, 0) for row in channel_rows)
        if link:
            values["spend"] = await self.tracking.aggregate_spend_by_link(link.id, start, end)
            if link.destination_type == "channel" and link.cost_model == "fix_pdp":
                values["spend"] = Decimal(link.price_per_unit or 0) * values["channel_joins"]
        else:
            rows = await self.tracking.get_link_metrics_rows(project_id=project.id, bot_id=bot_id,
                date_from=start, date_to=end, lead_status_codes=codes)
            values["spend"] = sum((Decimal(row.get("price_per_unit") or 0) * channels.get(row["link_id"], {}).get("channel_joins", 0)
                if row.get("destination_type") == "channel" and row.get("cost_model") == "fix_pdp"
                else Decimal(row["spend"] or 0) for row in rows), Decimal(0))
        return values


def format_summary(values: dict, *, gambling: bool = False) -> str:
    lines = [
        f"Подписчики канала: {values['channel_joins']}",
        f"Лиды: {values['leads']}",
        f"Старты: {values['starts']} | Клики: {values['clicks']}",
        f"Заявки в канал: {values['channel_join_requests']} | Отписки: {values['channel_leaves']}",
    ]
    if not gambling:
        lines.append(f"Поданные: {values['submitted_leads']}")
    lines.append(f"Рег: {values['registrations']} | ФД: {values['first_deposits']} | РД: {values['redeposits']}")
    denominator = values['channel_joins'] or values['starts']
    label = "подписчик" if values['channel_joins'] else "старт"
    lines.append(f"Конверсия {label} → лид: {values['leads'] / denominator * 100:.2f}%" if denominator else f"Конверсия {label} → лид: —")
    lines.append(f"Расход: {values['spend']:.2f}")
    lines.append(f"CPL: {values['spend'] / values['leads']:.2f}" if values['leads'] else "CPL: —")
    return "\n".join(lines)
