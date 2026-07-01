from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LeadStatusCode, MessageType, SenderType
from app.models.chat import Chat
from app.models.lead import Lead
from app.models.lead_status import LeadStatus
from app.models.message import Message
from app.models.partner import LeadSubmission
from app.models.project import Project
from app.repositories.tracking_metrics_repository import TrackingMetricsRepository


class ProjectMetricsRepository:
    """Small project-scoped aggregates for the admin header."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def header_metrics(self, project_id: UUID, day: date) -> dict:
        start_at = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end_at = start_at + timedelta(days=1)

        project_result = await self.db.execute(
            select(Project.tracking_lead_status_codes).where(Project.id == project_id)
        )
        tracking_status_codes = self._normalize_status_codes(project_result.scalar_one_or_none())

        leads_result = await self.db.execute(
            select(func.count(distinct(Lead.id)))
            .join(Chat, Chat.id == Lead.chat_id)
            .join(LeadStatus, LeadStatus.id == Lead.status_id)
            .where(
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                LeadStatus.code.in_(tracking_status_codes),
                self._lead_lifecycle_at() >= start_at,
                self._lead_lifecycle_at() < end_at,
            )
        )
        starts_result = await self.db.execute(
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
        spend = await TrackingMetricsRepository(self.db).aggregate_spend_by_project(
            project_id=project_id,
            bot_id=None,
            date_from=day,
            date_to=day,
        )
        leads = int(leads_result.scalar_one() or 0)
        starts = int(starts_result.scalar_one() or 0)
        submitted = int(submitted_result.scalar_one() or 0)
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
            "subscribers_today": starts,
            "conversion_today": conversion,
            "leads_today": leads,
            "chats_today": starts,
            "submitted_today": submitted,
            "submitted_percent_today": submitted_percent,
            "spend_today": spend,
            "cpl_today": cpl,
            "cost_per_submitted_today": cost_per_submitted,
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
