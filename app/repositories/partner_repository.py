from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import Text, delete, func, or_, select, update
from sqlalchemy.orm import selectinload

from app.models.lead import Lead
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
        is_active: bool,
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
            is_active=is_active,
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

    async def get_lead_in_project(self, lead_id: UUID, project_id: UUID) -> Optional[Lead]:
        result = await self.db.execute(
            select(Lead).where(
                Lead.id == lead_id,
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                Lead.is_trash.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def create_submission(
        self,
        *,
        lead_id: UUID,
        partner_integration_id: UUID,
        status: str,
    ) -> LeadSubmission:
        submission = LeadSubmission(
            lead_id=lead_id,
            partner_integration_id=partner_integration_id,
            status=status,
        )
        self.db.add(submission)
        await self.db.flush()
        await self.db.refresh(submission)
        return submission

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
            .options(selectinload(LeadSubmission.lead))
            .options(selectinload(LeadSubmission.partner_integration))
            .where(LeadSubmission.status == "pending")
            .order_by(LeadSubmission.submitted_at.asc(), LeadSubmission.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_submission(self, submission_id: UUID) -> Optional[LeadSubmission]:
        result = await self.db.execute(
            select(LeadSubmission)
            .options(selectinload(LeadSubmission.lead))
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
