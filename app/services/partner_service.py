from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import RoleName
from app.models.partner import PartnerIntegration
from app.models.user import User
from app.repositories.partner_repository import PartnerIntegrationRepository
from app.repositories.lead_repository import LeadRepository
from app.schemas.partner import (
    LeadSubmissionPreviewOut,
    LeadSubmissionOut,
    PartnerConnectionTestOut,
    PartnerIntegrationCreate,
    PartnerIntegrationOut,
    PartnerIntegrationUpdate,
)
from app.services.postback_service import PostbackService


class PartnerService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = PartnerIntegrationRepository(db)
        self.lead_repo = LeadRepository(db)

    async def list_integrations(
        self,
        project_id: UUID,
        actor: User,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[PartnerIntegrationOut], int]:
        self._ensure_can_manage(actor)
        self._ensure_project_access(actor, project_id)
        integrations = await self.repo.list_by_project(project_id, limit=limit, offset=offset)
        total = await self.repo.count_by_project(project_id)
        return [self._integration_out(item) for item in integrations], total

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
            auth_type=data.auth_type,
            auth_config=data.auth_config.model_dump(exclude_none=True),
            field_mapping=data.field_mapping,
            required_fields=data.required_fields,
            response_mapping=data.response_mapping.model_dump(exclude_none=True),
            retry_config=data.retry_config.model_dump(),
            is_active=data.is_active,
        )
        return self._integration_out(integration)

    async def get_integration(
        self,
        integration_id: UUID,
        project_id: UUID,
        actor: User,
    ) -> PartnerIntegrationOut:
        self._ensure_can_manage(actor)
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
        values = data.model_dump(exclude_unset=True, mode="json")
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
        try:
            async with self.db.begin_nested():
                submission = await self.repo.create_submission(
                    lead_id=lead.id,
                    partner_integration_id=integration.id,
                    status="pending",
                )
        except IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Lead was already submitted to this partner",
            ) from exc
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
        return await PostbackService(self.db).process_pending_submissions(limit=limit)

    async def process_submission(self, submission_id: UUID) -> dict[str, object]:
        return await PostbackService(self.db).process_submission(submission_id)

    async def test_connection(
        self,
        *,
        integration_id: UUID,
        project_id: UUID,
        actor: User,
    ) -> PartnerConnectionTestOut:
        self._ensure_can_manage(actor)
        self._ensure_project_access(actor, project_id)
        integration = await self._get_or_404(integration_id, project_id)
        result = await PostbackService(self.db).test_connection(integration)
        return PartnerConnectionTestOut.model_validate(result)

    async def build_submission_preview(
        self,
        *,
        lead_id: UUID,
        partner_id: UUID,
        project_id: UUID,
        actor: User,
    ) -> LeadSubmissionPreviewOut:
        self._ensure_can_submit(actor)
        self._ensure_project_access(actor, project_id)
        lead = await self.repo.get_lead_in_project(lead_id, project_id)
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        integration = await self._get_or_404(partner_id, project_id)
        try:
            payload = PostbackService(self.db).build_payload(lead, integration)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        return LeadSubmissionPreviewOut(
            lead_id=lead.id,
            partner_id=integration.id,
            payload=payload,
        )

    async def _get_or_404(self, integration_id: UUID, project_id: UUID) -> PartnerIntegration:
        integration = await self.repo.get_in_project(integration_id, project_id)
        if integration is None:
            raise HTTPException(status_code=404, detail="Partner integration not found")
        return integration

    @staticmethod
    def _integration_out(integration: PartnerIntegration) -> PartnerIntegrationOut:
        auth_config = integration.auth_config or {}
        return PartnerIntegrationOut.model_validate(integration).model_copy(
            update={"has_auth_token": bool(integration.auth_token or auth_config.get("token"))}
        )

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
