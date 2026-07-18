from __future__ import annotations

import re
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import RoleName
from app.models.partner import LeadSubmission, PartnerIntegration
from app.models.user import User
from app.repositories.partner_repository import PartnerIntegrationRepository
from app.repositories.lead_repository import LeadRepository
from app.schemas.partner import (
    LeadSubmissionPreviewOut,
    LeadSubmissionOut,
    PartnerAuthConfig,
    PartnerConnectionTestOut,
    PartnerIntegrationCreate,
    PartnerIntegrationOut,
    PartnerIntegrationUpdate,
    PartnerRequestConfig,
)
from app.services.access_control import require_project_access
from app.services.postback_service import PostbackService


class PartnerService:
    RETRYABLE_SUBMISSION_STATUSES = frozenset(
        {"failed", "manual_required", "routing_cleared"}
    )
    TEMPLATE_PATTERN = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_.]{0,127})\s*}}")

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
        request_config = data.request_config.model_dump()
        self._validate_request_config(request_config, is_active=data.is_active)
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
            request_config=request_config,
            is_active=data.is_active,
            is_auto_submit_enabled=data.is_auto_submit_enabled,
            auto_submit_rules=data.auto_submit_rules.model_dump(),
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
        current = await self._get_or_404(integration_id, project_id)
        values = data.model_dump(exclude_unset=True, mode="json")
        if not values:
            integration = await self._get_or_404(integration_id, project_id)
            return self._integration_out(integration)
        if "request_config" in values:
            values["request_config"] = self._merge_request_config_secrets(
                current.request_config or {},
                values["request_config"],
            )
        if "auth_config" in values:
            values["auth_config"] = self._merge_auth_secret(
                current.auth_config or {},
                values["auth_config"],
            )
        self._validate_request_config(
            values.get("request_config", current.request_config or {}),
            is_active=values.get("is_active", current.is_active),
        )
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
        lead = await self.repo.get_lead_in_project(
            lead_id,
            project_id,
            for_update=True,
        )
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        integration = await self._get_or_404(partner_integration_id, project_id)
        if not integration.is_active:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Partner integration is not active",
            )
        existing_submissions = await self.repo.list_submissions_for_lead_partner(
            lead_id=lead.id,
            partner_integration_id=integration.id,
            project_id=project_id,
            for_update=True,
        )
        if self._has_blocking_submission(existing_submissions):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Lead submission is already queued or completed for this partner",
            )
        try:
            async with self.db.begin_nested():
                submission = await self.repo.create_submission(
                    lead_id=lead.id,
                    partner_integration_id=integration.id,
                    status="pending",
                    submitted_by_user_id=actor.id,
                    submitted_manually=True,
                    submission_source="manual",
                )
                await self.repo.clear_manual_required_decision(
                    lead_id=lead.id,
                    partner_integration_id=integration.id,
                )
        except IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Lead was already submitted to this partner",
            ) from exc
        return LeadSubmissionOut.model_validate(submission)

    @classmethod
    def _has_blocking_submission(cls, submissions: list[LeadSubmission]) -> bool:
        return any(
            str(item.status).lower() not in cls.RETRYABLE_SUBMISSION_STATUSES
            for item in submissions
        )

    @classmethod
    def _validate_request_config(cls, config: dict, *, is_active: bool) -> None:
        if not is_active:
            return
        placeholders: set[str] = set()
        for template_source in (
            config.get("payload_template") or {},
            config.get("headers") or {},
            config.get("query_params") or {},
        ):
            placeholders.update(cls._collect_placeholders(template_source))
        secrets = config.get("secret_variables") or {}
        missing_secrets = sorted(
            placeholder.removeprefix("secret.")
            for placeholder in placeholders
            if placeholder.startswith("secret.")
            and not secrets.get(placeholder.removeprefix("secret."))
        )
        if missing_secrets:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Не заполнены секретные переменные партнёра: "
                    + ", ".join(missing_secrets)
                ),
            )
        if "random.ipv4" in placeholders:
            ipv4_cidrs = (config.get("generator_config") or {}).get("ipv4_cidrs") or []
            if not ipv4_cidrs:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Не заполнен IPv4 CIDR pool для генерации IP",
                )

    @classmethod
    def _collect_placeholders(cls, value: object) -> set[str]:
        if isinstance(value, dict):
            result: set[str] = set()
            for item in value.values():
                result.update(cls._collect_placeholders(item))
            return result
        if isinstance(value, list):
            result = set()
            for item in value:
                result.update(cls._collect_placeholders(item))
            return result
        if isinstance(value, str):
            return set(cls.TEMPLATE_PATTERN.findall(value))
        return set()

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
            postback_service = PostbackService(self.db)
            context = postback_service._build_template_context(lead, integration)
            payload = postback_service.build_payload(
                lead,
                integration,
                context=context,
            )
            postback_service.build_request(integration, context=context)
            payload = postback_service.redact_payload(payload, integration)
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
        request_config = dict(integration.request_config or {})
        secret_variables = dict(request_config.get("secret_variables") or {})
        request_config["secret_variables"] = {key: "" for key in secret_variables}
        return PartnerIntegrationOut.model_validate(integration).model_copy(
            update={
                "has_auth_token": bool(integration.auth_token or auth_config.get("token")),
                "auth_config": PartnerAuthConfig.model_validate(
                    {**auth_config, "token": None}
                ),
                "request_config": PartnerRequestConfig.model_validate(request_config),
                "secret_variable_keys": sorted(secret_variables),
            }
        )

    @staticmethod
    def _merge_auth_secret(current: dict, incoming: dict) -> dict:
        merged = {**current, **incoming}
        if not incoming.get("token"):
            if current.get("token"):
                merged["token"] = current["token"]
            else:
                merged.pop("token", None)
        return merged

    @staticmethod
    def _merge_request_config_secrets(
        current: dict,
        incoming: dict,
    ) -> dict:
        merged = {**current, **incoming}
        if "secret_variables" not in incoming:
            return merged
        current_secrets = dict(current.get("secret_variables") or {})
        incoming_secrets = dict(incoming.get("secret_variables") or {})
        merged["secret_variables"] = {
            key: current_secrets.get(key, "") if value == "" else value
            for key, value in incoming_secrets.items()
        }
        return merged

    @staticmethod
    def _ensure_project_access(actor: User, project_id: UUID) -> None:
        require_project_access(actor, project_id)

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
