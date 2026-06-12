from __future__ import annotations

import re
from collections import defaultdict
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bot import Bot
from app.models.chat import Chat
from app.models.lead import Lead
from app.models.lead_status import LeadStatus
from app.models.partner import LeadSubmission, PartnerIntegration
from app.models.project import Project
from app.schemas.lead_identity import (
    DuplicateLeadDetail,
    DuplicateSubmissionConflict,
    DuplicateSubmissionHistory,
)


class LeadIdentityService:
    SUCCESSFUL_SUBMISSION_STATUSES = frozenset({"completed", "success"})

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def find_duplicates(
        self,
        lead_id: UUID,
        project_id: UUID,
    ) -> list[DuplicateLeadDetail]:
        lead, chat = await self._get_source_identity(lead_id, project_id)
        phone_digits = self.normalize_phone(lead.phone)
        telegram_id = self._normalize_nonempty(chat.external_user_id)
        username = self.normalize_username(lead.username)

        conditions = []
        if phone_digits:
            conditions.append(self._phone_digits_expr() == phone_digits)
        if telegram_id:
            conditions.append(Chat.external_user_id == telegram_id)
        if username:
            conditions.append(self._username_expr() == username)

        if not conditions:
            return []

        rows = await self._fetch_duplicate_rows(lead_id, conditions)
        if not rows:
            return []

        lead_ids = [row.lead_id for row in rows]
        history_by_lead = await self._submission_history_by_lead(lead_ids)
        details: list[DuplicateLeadDetail] = []

        for row in rows:
            matched_fields: list[str] = []
            if phone_digits and self.normalize_phone(row.phone) == phone_digits:
                matched_fields.append("phone")
            if telegram_id and self._normalize_nonempty(row.external_user_id) == telegram_id:
                matched_fields.append("telegram_id")
            if username and self.normalize_username(row.username) == username:
                matched_fields.append("username")
            if not matched_fields:
                continue

            details.append(
                DuplicateLeadDetail(
                    lead_id=row.lead_id,
                    project_name=row.project_name,
                    bot_name=row.bot_name,
                    created_at=row.created_at,
                    match_type=matched_fields[0] if len(matched_fields) == 1 else "multiple",
                    matched_fields=matched_fields,
                    lead_status=row.status_name or row.status_code,
                    is_trash=row.is_trash,
                    is_deleted=row.is_deleted,
                    submission_history=history_by_lead.get(row.lead_id, []),
                )
            )

        return details

    async def find_partner_submission_conflict(
        self,
        *,
        lead_id: UUID,
        project_id: UUID,
        partner_integration: PartnerIntegration,
    ) -> DuplicateSubmissionConflict | None:
        duplicates = await self.find_duplicates(lead_id, project_id)
        partner_name_key = self.normalize_partner_name(partner_integration.name)

        for duplicate in duplicates:
            for submission in duplicate.submission_history:
                same_partner = (
                    submission.partner_integration_id == partner_integration.id
                    or self.normalize_partner_name(submission.partner_name) == partner_name_key
                )
                if (
                    same_partner
                    and submission.status.lower() in self.SUCCESSFUL_SUBMISSION_STATUSES
                ):
                    return DuplicateSubmissionConflict(
                        lead_id=lead_id,
                        partner_name=partner_integration.name,
                        duplicate=duplicate,
                        blocking_submission=submission,
                    )

        return None

    async def _get_source_identity(self, lead_id: UUID, project_id: UUID) -> tuple[Lead, Chat]:
        result = await self.db.execute(
            select(Lead, Chat)
            .join(Chat, Chat.id == Lead.chat_id)
            .where(
                Lead.id == lead_id,
                Lead.project_id == project_id,
            )
        )
        row = result.first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found",
            )
        return row[0], row[1]

    async def _fetch_duplicate_rows(self, lead_id: UUID, conditions: list) -> list:
        result = await self.db.execute(
            select(
                Lead.id.label("lead_id"),
                Lead.phone,
                Lead.username,
                Lead.created_at,
                Lead.is_trash,
                Lead.is_deleted,
                Chat.external_user_id,
                Project.name.label("project_name"),
                Bot.name.label("bot_name"),
                LeadStatus.code.label("status_code"),
                LeadStatus.name.label("status_name"),
            )
            .select_from(Lead)
            .join(Chat, Chat.id == Lead.chat_id)
            .join(Project, Project.id == Lead.project_id)
            .join(LeadStatus, LeadStatus.id == Lead.status_id)
            .outerjoin(Bot, Bot.id == Chat.bot_id)
            .where(Lead.id != lead_id, or_(*conditions))
            .order_by(Lead.created_at.desc(), Lead.id.desc())
        )
        return list(result.all())

    async def _submission_history_by_lead(
        self,
        lead_ids: list[UUID],
    ) -> dict[UUID, list[DuplicateSubmissionHistory]]:
        if not lead_ids:
            return {}

        result = await self.db.execute(
            select(
                LeadSubmission.lead_id,
                LeadSubmission.partner_integration_id,
                PartnerIntegration.name.label("partner_name"),
                LeadSubmission.status,
                LeadSubmission.partner_status,
                LeadSubmission.error_message,
                LeadSubmission.partner_feedback,
                LeadSubmission.submitted_at,
            )
            .join(PartnerIntegration, PartnerIntegration.id == LeadSubmission.partner_integration_id)
            .where(LeadSubmission.lead_id.in_(lead_ids))
            .order_by(LeadSubmission.submitted_at.desc(), LeadSubmission.id.desc())
        )

        history: dict[UUID, list[DuplicateSubmissionHistory]] = defaultdict(list)
        for row in result.all():
            history[row.lead_id].append(
                DuplicateSubmissionHistory(
                    partner_integration_id=row.partner_integration_id,
                    partner_name=row.partner_name,
                    status=row.status,
                    partner_status=row.partner_status,
                    error_message=row.error_message,
                    partner_feedback=row.partner_feedback,
                    created_at=row.submitted_at,
                )
            )
        return dict(history)

    @staticmethod
    def normalize_phone(value: str | None) -> str | None:
        if not value:
            return None
        digits = re.sub(r"\D+", "", value)
        return digits or None

    @staticmethod
    def normalize_username(value: str | None) -> str | None:
        if not value:
            return None
        username = value.strip().removeprefix("@").lower()
        return username or None

    @staticmethod
    def normalize_partner_name(value: str | None) -> str:
        return " ".join((value or "").strip().lower().split())

    @staticmethod
    def _normalize_nonempty(value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None

    @staticmethod
    def _phone_digits_expr():
        return func.regexp_replace(func.coalesce(Lead.phone, ""), r"\D", "", "g")

    @staticmethod
    def _username_expr():
        return func.lower(func.replace(func.coalesce(Lead.username, ""), "@", ""))
