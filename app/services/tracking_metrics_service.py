"""Tracking metrics service: permissions, date ranges, rates, and costs."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LeadStatusCode, RoleName
from app.models.user import User
from app.repositories.bot_repository import BotRepository
from app.repositories.lifecycle_metrics_repository import LifecycleMetricsRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.tracking_metrics_repository import TrackingMetricsRepository
from app.repositories.tracking_repository import TrackingLinkRepository
from app.schemas.tracking_metrics import (
    TrackingBreakdownItem,
    TrackingDailyMetric,
    TrackingFunnelStepItem,
    TrackingLinkMetric,
    TrackingLinkMetricsResponse,
    TrackingMetricSummary,
    TrackingProjectMetricsResponse,
)
from app.services.tracking_conversion import calculate_conversion_status
from app.services.access_control import require_project_access


class TrackingMetricsService:
    """
    Builds tracking metrics from current CRM source tables.

    Division-by-zero policy: all rates and costs return Decimal("0.00") so the
    frontend can render simple numeric cards without null handling.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.project_repo = ProjectRepository(db)
        self.bot_repo = BotRepository(db)
        self.link_repo = TrackingLinkRepository(db)
        self.metrics_repo = TrackingMetricsRepository(db)
        self.lifecycle_repo = LifecycleMetricsRepository(db)

    async def get_project_metrics(
        self,
        current_user: User,
        project_id: UUID,
        bot_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> TrackingProjectMetricsResponse:
        date_from, date_to = self._resolve_date_range(date_from, date_to)
        await self._ensure_project_access(current_user, project_id)
        project = await self._get_active_project_or_404(project_id)
        lead_status_codes = self._tracking_lead_status_codes(project)
        if bot_id is not None:
            await self._ensure_bot_in_project(bot_id, project_id)
        buyer_id = current_user.id if current_user.role_name == RoleName.BUYER else None

        link_rows = await self.metrics_repo.get_link_metrics_rows(
            project_id=project_id,
            bot_id=bot_id,
            date_from=date_from,
            date_to=date_to,
            lead_status_codes=lead_status_codes,
            buyer_id=buyer_id,
        )
        lifecycle_by_link = await self.lifecycle_repo.aggregate_by_link(
            project_id=project_id,
            bot_id=bot_id,
            date_from=date_from,
            date_to=date_to,
            buyer_id=buyer_id,
        )
        links: list[TrackingLinkMetric] = []
        for row in link_rows:
            row.update(lifecycle_by_link.get(row["link_id"], {}))
            row["deposits"] = row.get("first_deposits", 0)
            if project.project_format == "gambling":
                row["submitted_leads"] = 0
            summary = self._summary_from_values(row)
            links.append(
                TrackingLinkMetric(
                    link_id=row["link_id"],
                    code=row["code"],
                    title=row["title"],
                    buyer_name=row["buyer_name"],
                    ad_type=row["ad_type"],
                    payment_type=row["payment_type"],
                    is_active=row["is_active"],
                    base_conversion_rate=row["base_conversion_rate"],
                    min_sample_size=row["min_sample_size"],
                    conversion_status=calculate_conversion_status(
                        clicks=summary.clicks,
                        starts=summary.starts,
                        leads=summary.leads,
                        base_conversion_rate=row["base_conversion_rate"],
                        min_sample_size=row["min_sample_size"],
                    ),
                    summary=summary,
                )
            )
        daily_rows = await self.metrics_repo.aggregate_daily_by_project(
            project_id=project_id,
            bot_id=bot_id,
            date_from=date_from,
            date_to=date_to,
            lead_status_codes=lead_status_codes,
            buyer_id=buyer_id,
        )
        lifecycle_daily = await self.lifecycle_repo.aggregate_daily(
            project_id=project_id,
            bot_id=bot_id,
            date_from=date_from,
            date_to=date_to,
            buyer_id=buyer_id,
        )
        daily = self._fill_daily_range(
            self._merge_lifecycle_daily(
                daily_rows,
                lifecycle_daily,
                hide_submissions=project.project_format == "gambling",
            ),
            date_from,
            date_to,
        )

        if buyer_id is not None:
            summary_values = {
                "clicks": sum(item.summary.clicks for item in links),
                "starts": sum(item.summary.starts for item in links),
                "leads": sum(item.summary.leads for item in links),
                "submitted_leads": sum(
                    item.summary.submitted_leads for item in links
                ),
                "registrations": sum(item.summary.registrations for item in links),
                "first_deposits": sum(
                    item.summary.first_deposits for item in links
                ),
                "redeposits": sum(item.summary.redeposits for item in links),
                "spend": sum(
                    (item.summary.spend for item in links),
                    Decimal("0"),
                ),
            }
        else:
            lifecycle_totals = await self.lifecycle_repo.aggregate_counts(
                project_id=project_id,
                bot_id=bot_id,
                date_from=date_from,
                date_to=date_to,
            )
            summary_values = {
                "clicks": await self.metrics_repo.aggregate_clicks_by_project(
                    project_id,
                    bot_id,
                    date_from,
                    date_to,
                ),
                "starts": await self.metrics_repo.aggregate_starts_by_project(
                    project_id,
                    bot_id,
                    date_from,
                    date_to,
                ),
                "leads": await self.metrics_repo.aggregate_leads_by_project(
                    project_id,
                    bot_id,
                    date_from,
                    date_to,
                    lead_status_codes=lead_status_codes,
                ),
                "submitted_leads": (
                    0
                    if project.project_format == "gambling"
                    else await self.metrics_repo.aggregate_submitted_by_project(
                        project_id,
                        bot_id,
                        date_from,
                        date_to,
                    )
                ),
                **lifecycle_totals,
                "spend": await self.metrics_repo.aggregate_spend_by_project(
                    project_id,
                    bot_id,
                    date_from,
                    date_to,
                ),
            }
        summary = self._summary_from_values(summary_values)

        unattributed_rows: list[dict] = []
        unattributed_lifecycle_daily: list[dict] = []
        if buyer_id is None:
            unattributed_rows = await self.metrics_repo.aggregate_daily_unattributed_by_project(
                project_id=project_id,
                bot_id=bot_id,
                date_from=date_from,
                date_to=date_to,
                lead_status_codes=lead_status_codes,
            )
            unattributed_lifecycle_daily = await self.lifecycle_repo.aggregate_daily(
                project_id=project_id,
                bot_id=bot_id,
                date_from=date_from,
                date_to=date_to,
                unattributed_only=True,
            )
        unattributed_daily = self._fill_daily_range(
            self._merge_lifecycle_daily(
                unattributed_rows,
                unattributed_lifecycle_daily,
                hide_submissions=project.project_format == "gambling",
            ),
            date_from,
            date_to,
        )
        if buyer_id is None:
            unattributed_lifecycle = await self.lifecycle_repo.aggregate_counts(
                project_id=project_id,
                bot_id=bot_id,
                date_from=date_from,
                date_to=date_to,
                unattributed_only=True,
            )
            unattributed_values = {
                "clicks": 0,
                "starts": await self.metrics_repo.aggregate_starts_unattributed_by_project(
                    project_id,
                    bot_id,
                    date_from,
                    date_to,
                ),
                "leads": await self.metrics_repo.aggregate_leads_unattributed_by_project(
                    project_id,
                    bot_id,
                    date_from,
                    date_to,
                    lead_status_codes=lead_status_codes,
                ),
                "submitted_leads": (
                    0
                    if project.project_format == "gambling"
                    else await self.metrics_repo.aggregate_submitted_unattributed_by_project(
                        project_id,
                        bot_id,
                        date_from,
                        date_to,
                    )
                ),
                **unattributed_lifecycle,
                "spend": Decimal("0"),
            }
        else:
            unattributed_values = {}
        unattributed_summary = self._summary_from_values(unattributed_values)

        return TrackingProjectMetricsResponse(
            project_id=project_id,
            bot_id=bot_id,
            date_from=date_from,
            date_to=date_to,
            project_format=project.project_format,
            tracking_lead_status_codes=lead_status_codes,
            summary=summary,
            unattributed_summary=unattributed_summary,
            unattributed_daily=unattributed_daily,
            links=links,
            daily=daily,
            lifecycle_sources=await self.lifecycle_repo.aggregate_by_source(
                project_id=project_id,
                bot_id=bot_id,
                date_from=date_from,
                date_to=date_to,
                buyer_id=buyer_id,
            ),
        )

    async def get_link_metrics(
        self,
        current_user: User,
        link_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> TrackingLinkMetricsResponse:
        date_from, date_to = self._resolve_date_range(date_from, date_to)
        link = await self.link_repo.get_link_by_id(link_id)
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking link not found",
            )
        await self._ensure_project_access(current_user, link.project_id)
        if current_user.role_name == RoleName.BUYER and link.buyer_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking link not found",
            )
        project = await self._get_active_project_or_404(link.project_id)
        lead_status_codes = self._tracking_lead_status_codes(project)

        clicks = await self.metrics_repo.aggregate_clicks_by_link(
            link_id,
            date_from,
            date_to,
        )
        starts = await self.metrics_repo.aggregate_starts_by_link(
            link_id,
            date_from,
            date_to,
        )
        leads = await self.metrics_repo.aggregate_leads_by_link(
            link_id,
            date_from,
            date_to,
            lead_status_codes=lead_status_codes,
        )
        submitted = (
            0
            if project.project_format == "gambling"
            else await self.metrics_repo.aggregate_submitted_by_link(
                link_id,
                date_from,
                date_to,
            )
        )
        spend = await self.metrics_repo.aggregate_spend_by_link(
            link_id,
            date_from,
            date_to,
        )
        daily_rows = await self.metrics_repo.aggregate_daily_by_link(
            link_id=link_id,
            date_from=date_from,
            date_to=date_to,
            lead_status_codes=lead_status_codes,
        )
        lifecycle_counts = await self.lifecycle_repo.aggregate_counts(
            project_id=link.project_id,
            link_id=link_id,
            date_from=date_from,
            date_to=date_to,
        )
        lifecycle_daily = await self.lifecycle_repo.aggregate_daily(
            project_id=link.project_id,
            link_id=link_id,
            date_from=date_from,
            date_to=date_to,
        )
        daily = self._fill_daily_range(
            self._merge_lifecycle_daily(
                daily_rows,
                lifecycle_daily,
                hide_submissions=project.project_format == "gambling",
            ),
            date_from,
            date_to,
        )
        funnel_steps = self._build_funnel_steps(
            await self.metrics_repo.get_funnel_breakdown_by_link(
                link_id=link_id,
                date_from=date_from,
                date_to=date_to,
            )
        )

        summary = self._summary_from_values(
            {
                "clicks": clicks,
                "starts": starts,
                "leads": leads,
                "submitted_leads": submitted,
                **lifecycle_counts,
                "spend": spend,
            }
        )

        return TrackingLinkMetricsResponse(
            link_id=link.id,
            project_id=link.project_id,
            bot_id=link.bot_id,
            code=link.code,
            title=link.title,
            base_conversion_rate=link.base_conversion_rate,
            min_sample_size=link.min_sample_size,
            conversion_status=calculate_conversion_status(
                clicks=summary.clicks,
                starts=summary.starts,
                leads=summary.leads,
                base_conversion_rate=link.base_conversion_rate,
                min_sample_size=link.min_sample_size,
            ),
            date_from=date_from,
            date_to=date_to,
            project_format=project.project_format,
            tracking_lead_status_codes=lead_status_codes,
            summary=summary,
            daily=daily,
            funnel_steps=funnel_steps,
            age_breakdown=self._build_breakdown(
                await self.metrics_repo.get_age_breakdown_by_link(
                    link_id=link_id,
                    date_from=date_from,
                    date_to=date_to,
                )
            ),
            country_breakdown=self._build_breakdown(
                await self.metrics_repo.get_country_breakdown_by_link(
                    link_id=link_id,
                    date_from=date_from,
                    date_to=date_to,
                )
            ),
            city_breakdown=self._build_breakdown(
                await self.metrics_repo.get_city_breakdown_by_link(
                    link_id=link_id,
                    date_from=date_from,
                    date_to=date_to,
                )
            ),
            status_breakdown=self._build_breakdown(
                await self.metrics_repo.get_status_breakdown_by_link(
                    link_id=link_id,
                    date_from=date_from,
                    date_to=date_to,
                )
            ),
            card_breakdown=self._build_breakdown(
                await self.metrics_repo.get_card_breakdown_by_link(
                    link_id=link_id,
                    date_from=date_from,
                    date_to=date_to,
                )
            ),
            lifecycle_sources=await self.lifecycle_repo.aggregate_by_source(
                project_id=link.project_id,
                link_id=link_id,
                date_from=date_from,
                date_to=date_to,
            ),
        )

    async def _get_active_project_or_404(self, project_id: UUID):
        project = await self.project_repo.get_any_by_id(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        if project.is_deleted or project.status == "archived":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Project is archived",
            )
        return project

    @staticmethod
    async def _ensure_project_access(actor: User, project_id: UUID) -> None:
        require_project_access(actor, project_id)

    async def _ensure_bot_in_project(self, bot_id: UUID, project_id: UUID) -> None:
        bot = await self.bot_repo.get_by_id_in_project(bot_id, project_id)
        if bot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bot not found",
            )

    @classmethod
    def _resolve_date_range(
        cls,
        date_from: date | None,
        date_to: date | None,
    ) -> tuple[date, date]:
        resolved_to = date_to or date.today()
        resolved_from = date_from or (resolved_to - timedelta(days=6))
        if resolved_from > resolved_to:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="date_from must be before or equal to date_to",
            )
        return resolved_from, resolved_to

    @classmethod
    def _summary_from_values(cls, values: dict) -> TrackingMetricSummary:
        starts = int(values.get("starts") or 0)
        leads = int(values.get("leads") or 0)
        submitted = int(values.get("submitted_leads") or 0)
        registrations = int(values.get("registrations") or 0)
        first_deposits = int(
            values.get("first_deposits") or values.get("deposits") or 0
        )
        redeposits = int(values.get("redeposits") or 0)
        spend = cls._money(values.get("spend") or Decimal("0"))
        return TrackingMetricSummary(
            clicks=int(values.get("clicks") or 0),
            starts=starts,
            leads=leads,
            submitted_leads=submitted,
            deposits=first_deposits,
            registrations=registrations,
            first_deposits=first_deposits,
            redeposits=redeposits,
            spend=spend,
            cr_to_lead=cls._ratio_percent(leads, starts),
            cr_to_submit=cls._ratio_percent(submitted, leads),
            cr_to_deposit=cls._ratio_percent(first_deposits, registrations),
            cr_to_registration=cls._ratio_percent(registrations, starts),
            cr_registration_to_deposit=cls._ratio_percent(
                first_deposits,
                registrations,
            ),
            cr_deposit_to_redeposit=cls._ratio_percent(
                redeposits,
                first_deposits,
            ),
            cpl=cls._cost(spend, leads),
            cpsl=cls._cost(spend, submitted),
            cpd=cls._cost(spend, first_deposits),
            cpr=cls._cost(spend, registrations),
            cpfd=cls._cost(spend, first_deposits),
            cprd=cls._cost(spend, redeposits),
        )

    @classmethod
    def _unattributed_summary(
        cls,
        total: TrackingMetricSummary,
        links: list[TrackingLinkMetric],
    ) -> TrackingMetricSummary:
        tracked_clicks = sum(link.summary.clicks for link in links)
        tracked_starts = sum(link.summary.starts for link in links)
        tracked_leads = sum(link.summary.leads for link in links)
        tracked_submitted = sum(link.summary.submitted_leads for link in links)
        tracked_deposits = sum(link.summary.deposits for link in links)
        return cls._summary_from_values(
            {
                "clicks": max(total.clicks - tracked_clicks, 0),
                "starts": max(total.starts - tracked_starts, 0),
                "leads": max(total.leads - tracked_leads, 0),
                "submitted_leads": max(total.submitted_leads - tracked_submitted, 0),
                "deposits": max(total.deposits - tracked_deposits, 0),
                "spend": Decimal("0"),
            }
        )

    @staticmethod
    def _tracking_lead_status_codes(project) -> list[str]:
        raw_codes = project.tracking_lead_status_codes or list(
            LeadStatusCode.TRACKING_LEAD_DEFAULT
        )
        normalized: list[str] = []
        for raw_code in raw_codes:
            code = str(raw_code).strip().lower()
            if code and code not in normalized:
                normalized.append(code)
        return normalized or list(LeadStatusCode.TRACKING_LEAD_DEFAULT)

    @classmethod
    def _fill_daily_range(
        cls,
        rows: list[dict],
        date_from: date,
        date_to: date,
    ) -> list[TrackingDailyMetric]:
        rows_by_date = {row["date"]: row for row in rows}
        current = date_from
        daily: list[TrackingDailyMetric] = []
        while current <= date_to:
            row = rows_by_date.get(current, {})
            daily.append(
                TrackingDailyMetric(
                    date=current,
                    clicks=int(row.get("clicks") or 0),
                    starts=int(row.get("starts") or 0),
                    leads=int(row.get("leads") or 0),
                    submitted_leads=int(row.get("submitted_leads") or 0),
                    deposits=int(
                        row.get("first_deposits") or row.get("deposits") or 0
                    ),
                    registrations=int(row.get("registrations") or 0),
                    first_deposits=int(
                        row.get("first_deposits") or row.get("deposits") or 0
                    ),
                    redeposits=int(row.get("redeposits") or 0),
                    spend=cls._money(row.get("spend") or Decimal("0")),
                )
            )
            current += timedelta(days=1)
        return daily

    @staticmethod
    def _merge_lifecycle_daily(
        metric_rows: list[dict],
        lifecycle_rows: list[dict],
        *,
        hide_submissions: bool,
    ) -> list[dict]:
        rows_by_date = {
            row["date"]: {
                **row,
                "submitted_leads": (
                    0 if hide_submissions else int(row.get("submitted_leads") or 0)
                ),
            }
            for row in metric_rows
        }
        for lifecycle_row in lifecycle_rows:
            metric_date = lifecycle_row["date"]
            row = rows_by_date.setdefault(
                metric_date,
                {
                    "date": metric_date,
                    "clicks": 0,
                    "starts": 0,
                    "leads": 0,
                    "submitted_leads": 0,
                    "spend": Decimal("0"),
                },
            )
            row["registrations"] = int(lifecycle_row.get("registrations") or 0)
            row["first_deposits"] = int(
                lifecycle_row.get("first_deposits") or 0
            )
            row["deposits"] = row["first_deposits"]
            row["redeposits"] = int(lifecycle_row.get("redeposits") or 0)
        return [rows_by_date[key] for key in sorted(rows_by_date)]

    @classmethod
    def _build_breakdown(cls, rows: list[dict]) -> list[TrackingBreakdownItem]:
        total = sum(int(row.get("count") or 0) for row in rows)
        return [
            TrackingBreakdownItem(
                key=str(row.get("key") or ""),
                label=str(row.get("label") or row.get("key") or ""),
                count=int(row.get("count") or 0),
                percent=cls._ratio_percent(int(row.get("count") or 0), total),
            )
            for row in rows
        ]

    @classmethod
    def _build_funnel_steps(cls, rows: list[dict]) -> list[TrackingFunnelStepItem]:
        items: list[TrackingFunnelStepItem] = []
        previous_count: int | None = None
        for row in rows:
            count = int(row.get("count") or 0)
            dropoff_count = 0
            dropoff_percent = Decimal("0.00")
            if previous_count is not None:
                dropoff_count = max(previous_count - count, 0)
                dropoff_percent = cls._ratio_percent(dropoff_count, previous_count)
            items.append(
                TrackingFunnelStepItem(
                    step_key=str(row.get("step_key") or ""),
                    label=str(row.get("label") or row.get("step_key") or ""),
                    count=count,
                    dropoff_count=dropoff_count,
                    dropoff_percent=dropoff_percent,
                )
            )
            previous_count = count
        return items

    @staticmethod
    def _ratio_percent(numerator: int, denominator: int) -> Decimal:
        if denominator <= 0:
            return Decimal("0.00")
        return (
            Decimal(numerator) / Decimal(denominator) * Decimal("100")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @classmethod
    def _cost(cls, spend: Decimal, denominator: int) -> Decimal:
        if denominator <= 0:
            return Decimal("0.00")
        return cls._money(spend / Decimal(denominator))

    @staticmethod
    def _money(value) -> Decimal:
        return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
