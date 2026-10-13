from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import distinct, func, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LeadStatusCode, MessageType, SenderType
from app.models.chat import Chat
from app.models.lead import Lead
from app.models.lead_status import LeadStatus
from app.models.message import Message
from app.models.project import Project
from app.models.lead import LeadTag
from app.models.tag import Tag
from app.models.tracking_journey import LeadTagHistory
from app.repositories.tracking_lead_criteria import tracking_lead_criterion
from app.repositories.tracking_metrics_repository import TrackingMetricsRepository
from app.repositories.lifecycle_metrics_repository import LifecycleMetricsRepository


class ProjectMetricsRepository:
    """Small project-scoped aggregates for the admin header."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def header_metrics(self, project_id: UUID, day: date) -> dict:
        start_at = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end_at = start_at + timedelta(days=1)

        project_result = await self.db.execute(
            select(Project.tracking_lead_status_codes, Project.project_format,
                   Project.tracking_lead_count_mode, Project.tracking_lead_tag_ids).where(
                Project.id == project_id
            )
        )
        project_row = project_result.one_or_none()
        tracking_status_codes = self._normalize_status_codes(
            project_row.tracking_lead_status_codes if project_row is not None else None
        )
        project_format = project_row.project_format if project_row is not None else "submission"

        leads_result = await self.db.execute(
            select(func.count(distinct(Lead.id)))
            .join(Chat, Chat.id == Lead.chat_id)
            .join(LeadStatus, LeadStatus.id == Lead.status_id)
            .where(
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                tracking_lead_criterion(tracking_status_codes),
                self._lead_lifecycle_at() >= start_at,
                self._lead_lifecycle_at() < end_at,
            )
        )
        tracking_metrics = TrackingMetricsRepository(self.db)
        starts = await tracking_metrics.aggregate_starts_by_project(project_id, None, day, day)
        mode = project_row.tracking_lead_count_mode if project_row is not None else "statuses"
        qualified_today = 0
        if mode == "tags":
            tag_ids = [UUID(value) for value in project_row.tracking_lead_tag_ids or []]
            events = union_all(
                select(LeadTagHistory.lead_id, LeadTagHistory.occurred_at.label("at")).where(LeadTagHistory.tag_id.in_(tag_ids)),
                select(LeadTag.lead_id, LeadTag.created_at.label("at")).join(Tag, Tag.id == LeadTag.tag_id)
                    .where(Tag.project_id == project_id, LeadTag.tag_id.in_(tag_ids)),
            ).subquery()
            first = select(events.c.lead_id, func.min(events.c.at).label("at")).group_by(events.c.lead_id).subquery()
            qualified_today = int(await self.db.scalar(select(func.count()).select_from(first)
                .join(Lead, Lead.id == first.c.lead_id).join(Chat, Chat.id == Lead.chat_id)
                .where(Lead.project_id == project_id, Lead.is_deleted.is_(False), Chat.is_deleted.is_(False),
                       Chat.reset_at.is_(None), first.c.at >= start_at, first.c.at < end_at)) or 0)
        submitted = await tracking_metrics.aggregate_submitted_by_project(
            project_id=project_id,
            bot_id=None,
            date_from=day,
            date_to=day,
        )
        lifecycle_counts = await LifecycleMetricsRepository(self.db).aggregate_counts(
            project_id=project_id,
            date_from=day,
            date_to=day,
        )
        spend = await tracking_metrics.aggregate_spend_by_project(
            project_id=project_id,
            bot_id=None,
            date_from=day,
            date_to=day,
        )
        leads = int(leads_result.scalar_one() or 0)
        starts = int(starts or 0)
        submitted = int(submitted or 0)
        spend = Decimal(spend or 0)
        cpl = spend / Decimal(leads) if leads > 0 else Decimal("0")
        conversion = (
            Decimal(leads) / Decimal(starts) * Decimal("100")
            if starts > 0
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
            "project_format": project_format,
            "subscribers_today": starts,
            "conversion_today": conversion,
            "leads_today": leads,
            "tracking_lead_count_mode": mode,
            "qualified_today": qualified_today,
            "timezone": "UTC",
            "chats_today": starts,
            "submitted_today": submitted,
            "submitted_percent_today": submitted_percent,
            "spend_today": spend,
            "cpl_today": cpl,
            "cost_per_submitted_today": cost_per_submitted,
            "registrations_today": lifecycle_counts["registrations"],
            "deposits_today": lifecycle_counts["first_deposits"],
            "redeposits_today": lifecycle_counts["redeposits"],
        }

    @staticmethod
    def _normalize_status_codes(raw_codes: list[str] | None) -> tuple[str, ...]:
        source = raw_codes or list(LeadStatusCode.TRACKING_LEAD_DEFAULT)
        normalized: list[str] = []
        for raw_code in source:
            code = str(raw_code).strip().lower()
            if code and code not in normalized:
                normalized.append(code)
        return tuple(normalized or LeadStatusCode.TRACKING_LEAD_DEFAULT)

    @staticmethod
    def _is_start_message():
        command = func.split_part(func.lower(func.trim(Message.body)), " ", 1)
        return or_(command == "/start", command.like("/start@%"))

    @staticmethod
    def _lead_lifecycle_at():
        return func.coalesce(Chat.current_cycle_started_at, Lead.created_at)
