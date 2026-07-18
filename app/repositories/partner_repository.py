from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import Text, delete, func, or_, select, update
from sqlalchemy.orm import selectinload

from app.models.lead import Lead
from app.models.chat import Chat
from app.models.tracking import TrackingLink
from app.models.partner import LeadSubmission, PartnerIntegration
from app.repositories.base import BaseRepository


class PartnerIntegrationRepository(BaseRepository[PartnerIntegration]):
    model = PartnerIntegration

    async def list_by_project(
        self,
        project_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PartnerIntegration]:
        result = await self.db.execute(
            select(PartnerIntegration)
            .where(PartnerIntegration.project_id == project_id)
            .order_by(PartnerIntegration.created_at.desc(), PartnerIntegration.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_project(self, project_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count(PartnerIntegration.id)).where(
                PartnerIntegration.project_id == project_id
            )
        )
        return int(result.scalar_one() or 0)

    async def list_auto_submit_by_project(
        self,
        project_id: UUID,
    ) -> list[PartnerIntegration]:
        result = await self.db.execute(
            select(PartnerIntegration).where(
                PartnerIntegration.project_id == project_id,
                PartnerIntegration.is_active.is_(True),
                PartnerIntegration.is_auto_submit_enabled.is_(True),
            )
        )
        return list(result.scalars().all())

    async def get_in_project(
        self,
        integration_id: UUID,
        project_id: UUID,
    ) -> Optional[PartnerIntegration]:
        result = await self.db.execute(
            select(PartnerIntegration).where(
                PartnerIntegration.id == integration_id,
                PartnerIntegration.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_in_project(
        self,
        *,
        project_id: UUID,
        name: str,
        postback_url: str,
        auth_token: str | None,
        auth_type: str,
        auth_config: dict[str, Any],
        field_mapping: dict[str, str],
        required_fields: list[str],
        response_mapping: dict[str, Any],
        retry_config: dict[str, Any],
        request_config: dict[str, Any],
        is_active: bool,
        is_auto_submit_enabled: bool,
        auto_submit_rules: dict[str, Any],
    ) -> PartnerIntegration:
        integration = PartnerIntegration(
            project_id=project_id,
            name=name,
            postback_url=postback_url,
            auth_token=auth_token,
            auth_type=auth_type,
            auth_config=auth_config,
            field_mapping=field_mapping,
            required_fields=required_fields,
            response_mapping=response_mapping,
            retry_config=retry_config,
            request_config=request_config,
            is_active=is_active,
            is_auto_submit_enabled=is_auto_submit_enabled,
            auto_submit_rules=auto_submit_rules,
        )
        self.db.add(integration)
        await self.db.flush()
        await self.db.refresh(integration)
        return integration

    async def update_in_project(
        self,
        integration_id: UUID,
        project_id: UUID,
        **values,
    ) -> Optional[PartnerIntegration]:
        await self.db.execute(
            update(PartnerIntegration)
            .where(
                PartnerIntegration.id == integration_id,
                PartnerIntegration.project_id == project_id,
            )
            .values(**values)
        )
        return await self.get_in_project(integration_id, project_id)

    async def delete_in_project(self, integration_id: UUID, project_id: UUID) -> bool:
        result = await self.db.execute(
            delete(PartnerIntegration).where(
                PartnerIntegration.id == integration_id,
                PartnerIntegration.project_id == project_id,
            )
        )
        return bool(result.rowcount)

    async def get_lead_in_project(
        self,
        lead_id: UUID,
        project_id: UUID,
        *,
        for_update: bool = False,
    ) -> Optional[Lead]:
        stmt = (
            select(Lead)
            .options(
                selectinload(Lead.project),
                selectinload(Lead.chat)
                .selectinload(Chat.tracking_link)
                .selectinload(TrackingLink.buyer),
                selectinload(Lead.chat).selectinload(Chat.bot),
            )
            .where(
                Lead.id == lead_id,
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                Lead.is_trash.is_(False),
            )
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_submission(
        self,
        *,
        lead_id: UUID,
        partner_integration_id: UUID,
        status: str,
        submitted_by_user_id: UUID | None = None,
        submitted_manually: bool = False,
        routing_decision_reason: str | None = None,
        submission_source: str = "legacy",
    ) -> LeadSubmission:
        submission = LeadSubmission(
            lead_id=lead_id,
            partner_integration_id=partner_integration_id,
            status=status,
            submitted_by_user_id=submitted_by_user_id,
            submitted_manually=submitted_manually,
            routing_decision_reason=routing_decision_reason,
            submission_source=submission_source,
        )
        self.db.add(submission)
        await self.db.flush()
        await self.db.refresh(submission)
        return submission

    async def upsert_manual_required_decision(
        self,
        *,
        lead_id: UUID,
        partner_integration_id: UUID,
        reason: str,
    ) -> LeadSubmission:
        result = await self.db.execute(
            select(LeadSubmission)
            .where(
                LeadSubmission.lead_id == lead_id,
                LeadSubmission.partner_integration_id == partner_integration_id,
                LeadSubmission.status == "manual_required",
            )
            .order_by(LeadSubmission.submitted_at.desc())
            .limit(1)
        )
        decision = result.scalar_one_or_none()
        if decision is None:
            return await self.create_submission(
                lead_id=lead_id,
                partner_integration_id=partner_integration_id,
                status="manual_required",
                routing_decision_reason=reason,
                submission_source="auto",
            )
        decision.routing_decision_reason = reason
        decision.completed_at = None
        await self.db.flush()
        return decision

    async def clear_manual_required_decision(
        self,
        *,
        lead_id: UUID,
        partner_integration_id: UUID,
    ) -> None:
        await self.db.execute(
            update(LeadSubmission)
            .where(
                LeadSubmission.lead_id == lead_id,
                LeadSubmission.partner_integration_id == partner_integration_id,
                LeadSubmission.status == "manual_required",
            )
            .values(
                status="routing_cleared",
                completed_at=datetime.now(timezone.utc),
            )
        )

    async def list_submissions_for_lead_partner(
        self,
        *,
        lead_id: UUID,
        partner_integration_id: UUID,
        project_id: UUID,
        for_update: bool = False,
    ) -> list[LeadSubmission]:
        stmt = (
            select(LeadSubmission)
            .join(Lead, Lead.id == LeadSubmission.lead_id)
            .where(
                LeadSubmission.lead_id == lead_id,
                LeadSubmission.partner_integration_id == partner_integration_id,
                Lead.project_id == project_id,
            )
            .order_by(LeadSubmission.submitted_at.desc(), LeadSubmission.id.desc())
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_submissions_for_lead(
        self,
        lead_id: UUID,
        project_id: UUID,
    ) -> list[LeadSubmission]:
        result = await self.db.execute(
            select(LeadSubmission)
            .join(Lead, Lead.id == LeadSubmission.lead_id)
            .where(
                LeadSubmission.lead_id == lead_id,
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                Lead.is_trash.is_(False),
            )
            .order_by(LeadSubmission.submitted_at.desc())
        )
        return list(result.scalars().all())

    async def list_pending_submissions(self, limit: int = 20) -> list[LeadSubmission]:
        result = await self.db.execute(
            select(LeadSubmission)
            .options(
                selectinload(LeadSubmission.lead).selectinload(Lead.project),
                selectinload(LeadSubmission.lead)
                .selectinload(Lead.chat)
                .selectinload(Chat.tracking_link)
                .selectinload(TrackingLink.buyer),
                selectinload(LeadSubmission.lead)
                .selectinload(Lead.chat)
                .selectinload(Chat.bot),
            )
            .options(selectinload(LeadSubmission.partner_integration))
            .where(LeadSubmission.status == "pending")
            .order_by(LeadSubmission.submitted_at.asc(), LeadSubmission.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_submission(self, submission_id: UUID) -> Optional[LeadSubmission]:
        result = await self.db.execute(
            select(LeadSubmission)
            .options(
                selectinload(LeadSubmission.lead).selectinload(Lead.project),
                selectinload(LeadSubmission.lead)
                .selectinload(Lead.chat)
                .selectinload(Chat.tracking_link)
                .selectinload(TrackingLink.buyer),
                selectinload(LeadSubmission.lead)
                .selectinload(Lead.chat)
                .selectinload(Chat.bot),
            )
            .options(selectinload(LeadSubmission.partner_integration))
            .where(LeadSubmission.id == submission_id)
        )
        return result.scalar_one_or_none()

    async def find_submission_for_partner_postback(
        self,
        *,
        partner_integration_id: UUID,
        submission_id: UUID | None = None,
        lead_id: UUID | None = None,
        external_id: str | None = None,
    ) -> Optional[LeadSubmission]:
        stmt = (
            select(LeadSubmission)
            .options(selectinload(LeadSubmission.lead))
            .options(selectinload(LeadSubmission.partner_integration))
            .where(LeadSubmission.partner_integration_id == partner_integration_id)
        )
        if submission_id is not None:
            stmt = stmt.where(LeadSubmission.id == submission_id)
        elif lead_id is not None:
            stmt = stmt.where(LeadSubmission.lead_id == lead_id)
        elif external_id:
            needle = self._ilike_needle(external_id)
            stmt = stmt.where(
                or_(
                    LeadSubmission.response_payload.contains(
                        {"parsed": {"external_id": external_id}}
                    ),
                    LeadSubmission.request_payload.cast(Text).ilike(needle, escape="\\"),
                    LeadSubmission.response_payload.cast(Text).ilike(needle, escape="\\"),
                )
            )
        else:
            return None

        result = await self.db.execute(
            stmt.order_by(LeadSubmission.submitted_at.desc(), LeadSubmission.id.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _ilike_needle(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"
