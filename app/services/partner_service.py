from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import RoleName
from app.models.lead import Lead
from app.models.partner import LeadSubmission, PartnerIntegration
from app.models.user import User
from app.repositories.partner_repository import PartnerIntegrationRepository
from app.repositories.lead_repository import LeadRepository
from app.schemas.partner import (
    LeadSubmissionOut,
    PartnerIntegrationCreate,
    PartnerIntegrationOut,
    PartnerIntegrationUpdate,
)

logger = logging.getLogger(__name__)


class PartnerService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = PartnerIntegrationRepository(db)
        self.lead_repo = LeadRepository(db)

    async def list_integrations(
        self,
        project_id: UUID,
        actor: User,
    ) -> list[PartnerIntegrationOut]:
        self._ensure_project_access(actor, project_id)
        integrations = await self.repo.list_by_project(project_id)
        return [self._integration_out(item) for item in integrations]

    async def create_integration(
        self,
        data: PartnerIntegrationCreate,
        actor: User,
    ) -> PartnerIntegrationOut:
        self._ensure_can_manage(actor)
        self._ensure_project_access(actor, data.project_id)
        integration = await self.repo.create_in_project(
            project_id=data.project_id,
            name=data.name,
            postback_url=data.postback_url,
            auth_token=data.auth_token,
            is_active=data.is_active,
        )
        return self._integration_out(integration)

    async def get_integration(
        self,
        integration_id: UUID,
        project_id: UUID,
        actor: User,
    ) -> PartnerIntegrationOut:
        self._ensure_project_access(actor, project_id)
        integration = await self._get_or_404(integration_id, project_id)
        return self._integration_out(integration)

    async def update_integration(
        self,
        integration_id: UUID,
        project_id: UUID,
        data: PartnerIntegrationUpdate,
        actor: User,
    ) -> PartnerIntegrationOut:
        self._ensure_can_manage(actor)
        self._ensure_project_access(actor, project_id)
        await self._get_or_404(integration_id, project_id)
        values = data.model_dump(exclude_unset=True)
        if not values:
            integration = await self._get_or_404(integration_id, project_id)
            return self._integration_out(integration)
        integration = await self.repo.update_in_project(
            integration_id,
            project_id,
            **values,
        )
        if integration is None:
            raise HTTPException(status_code=404, detail="Partner integration not found")
        return self._integration_out(integration)

    async def delete_integration(
        self,
        integration_id: UUID,
        project_id: UUID,
        actor: User,
    ) -> None:
        self._ensure_can_manage(actor)
        self._ensure_project_access(actor, project_id)
        deleted = await self.repo.delete_in_project(integration_id, project_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Partner integration not found")

    async def queue_lead_submission(
        self,
        *,
        lead_id: UUID,
        partner_integration_id: UUID,
        project_id: UUID,
        actor: User,
    ) -> LeadSubmissionOut:
        self._ensure_can_submit(actor)
        self._ensure_project_access(actor, project_id)
        lead = await self.repo.get_lead_in_project(lead_id, project_id)
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        integration = await self._get_or_404(partner_integration_id, project_id)
        if not integration.is_active:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Partner integration is not active",
            )
        submission = await self.repo.create_submission(
            lead_id=lead.id,
            partner_integration_id=integration.id,
            status="pending",
        )
        return LeadSubmissionOut.model_validate(submission)

    async def list_lead_submissions(
        self,
        *,
        lead_id: UUID,
        project_id: UUID,
        actor: User,
    ) -> list[LeadSubmissionOut]:
        self._ensure_project_access(actor, project_id)
        lead = await self.repo.get_lead_in_project(lead_id, project_id)
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        submissions = await self.repo.list_submissions_for_lead(lead_id, project_id)
        return [LeadSubmissionOut.model_validate(item) for item in submissions]

    async def process_pending_submissions(self, limit: int = 20) -> int:
        submissions = await self.repo.list_pending_submissions(limit=limit)
        processed = 0
        for submission in submissions:
            await self._send_submission(submission)
            processed += 1
        return processed

    async def process_submission(self, submission_id: UUID) -> dict[str, Any]:
        submission = await self.repo.get_submission(submission_id)
        if submission is None:
            return {"status": "failed", "error": "Submission not found"}
        await self._send_submission(submission)
        return {"status": submission.status, "submission_id": str(submission.id)}

    async def _send_submission(self, submission: LeadSubmission) -> None:
        if submission.status != "pending":
            return
        submission.status = "sending"
        await self.db.flush()

        lead = submission.lead
        integration = submission.partner_integration
        if lead is None or integration is None:
            self._mark_failed(submission, "Lead or partner integration not found")
            await self.db.flush()
            return
        if lead.project_id != integration.project_id:
            self._mark_failed(submission, "Lead and partner integration project mismatch")
            await self.db.flush()
            return
        if not integration.is_active:
            self._mark_failed(submission, "Partner integration is not active")
            await self.db.flush()
            return

        payload = self._lead_payload(lead)
        submission.request_payload = payload
        headers = {"Content-Type": "application/json"}
        if integration.auth_token:
            headers["Authorization"] = f"Bearer {integration.auth_token}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    integration.postback_url,
                    json=payload,
                    headers=headers,
                )
        except httpx.TimeoutException:
            self._mark_failed(submission, "Request timeout")
            await self.db.flush()
            logger.warning("Postback timeout lead_id=%s integration_id=%s", lead.id, integration.id)
            return
        except Exception as exc:
            self._mark_failed(submission, str(exc)[:1000])
            await self.db.flush()
            logger.exception("Postback failed lead_id=%s integration_id=%s", lead.id, integration.id)
            return

        submission.response_payload = {
            "status_code": response.status_code,
            "body": response.text[:1000],
        }
        if response.status_code in (200, 201, 202):
            submission.status = "success"
            submission.error_message = None
            updated = await self.lead_repo.set_status_by_code(
                lead.id,
                lead.project_id,
                "submitted",
            )
            if updated is None:
                logger.warning(
                    "Postback succeeded but submitted status is missing lead_id=%s",
                    lead.id,
                )
        else:
            submission.status = "failed"
            submission.error_message = f"HTTP {response.status_code}: {response.text[:500]}"
        submission.completed_at = datetime.now(timezone.utc)
        await self.db.flush()
        logger.info(
            "Postback processed lead_id=%s integration_id=%s status=%s",
            lead.id,
            integration.id,
            submission.status,
        )

    async def _get_or_404(self, integration_id: UUID, project_id: UUID) -> PartnerIntegration:
        integration = await self.repo.get_in_project(integration_id, project_id)
        if integration is None:
            raise HTTPException(status_code=404, detail="Partner integration not found")
        return integration

    @staticmethod
    def _integration_out(integration: PartnerIntegration) -> PartnerIntegrationOut:
        return PartnerIntegrationOut.model_validate(integration).model_copy(
            update={"has_auth_token": bool(integration.auth_token)}
        )

    @staticmethod
    def _lead_payload(lead: Lead) -> dict[str, Any]:
        return {
            "lead_id": str(lead.id),
            "name": lead.name,
            "phone": lead.phone,
            "username": lead.username,
            "age": lead.age,
            "country": lead.country,
            "call_time": lead.call_time_text,
            "has_card": lead.has_card,
            "score_percent": lead.score_percent,
            "custom_fields": lead.custom_fields,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
        }

    @staticmethod
    def _mark_failed(submission: LeadSubmission, error: str) -> None:
        submission.status = "failed"
        submission.error_message = error[:1000]
        submission.completed_at = datetime.now(timezone.utc)

    @staticmethod
    def _ensure_project_access(actor: User, project_id: UUID) -> None:
        if actor.role_name == RoleName.SUPER_ADMIN:
            return
        if actor.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Project is not accessible for current user",
            )

    @staticmethod
    def _ensure_can_manage(actor: User) -> None:
        if actor.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only super_admin/admin can manage partner integrations",
            )

    @staticmethod
    def _ensure_can_submit(actor: User) -> None:
        if actor.role_name not in {
            RoleName.SUPER_ADMIN,
            RoleName.ADMIN,
            RoleName.MANAGER,
            RoleName.OPERATOR,
        }:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Current user cannot submit leads to partners",
            )
