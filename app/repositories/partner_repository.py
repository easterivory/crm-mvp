from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import selectinload

from app.models.lead import Lead
from app.models.partner import LeadSubmission, PartnerIntegration
from app.repositories.base import BaseRepository


class PartnerIntegrationRepository(BaseRepository[PartnerIntegration]):
    model = PartnerIntegration

    async def list_by_project(self, project_id: UUID) -> list[PartnerIntegration]:
        result = await self.db.execute(
            select(PartnerIntegration)
            .where(PartnerIntegration.project_id == project_id)
            .order_by(PartnerIntegration.created_at.desc())
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
        is_active: bool,
    ) -> PartnerIntegration:
        integration = PartnerIntegration(
            project_id=project_id,
            name=name,
            postback_url=postback_url,
            auth_token=auth_token,
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
