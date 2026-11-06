from __future__ import annotations

import secrets
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Text, cast, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import RoleName
from app.models.chat import Chat
from app.models.lead import Lead
from app.models.partner import LeadSubmission, PartnerIntegration
from app.models.postback import PostbackEndpoint, PostbackReceipt
from app.models.tracking import TrackingLink
from app.models.user import User
from app.schemas.postback import (
    PostbackEndpointCreate,
    PostbackEndpointOut,
    PostbackEndpointUpdate,
    PostbackParameterMapping,
    PublicPostbackResult,
)
from app.services.access_control import require_project_access
from app.services.lead_event_service import LeadEventService


class PostbackEndpointService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.events = LeadEventService(db)

    async def list_endpoints(
        self,
        *,
        project_id: UUID,
        actor: User,
        partner_integration_id: UUID | None = None,
        include_archived: bool = False,
    ) -> list[PostbackEndpointOut]:
        self._ensure_manage_access(actor, project_id)
        stmt = select(PostbackEndpoint).where(PostbackEndpoint.project_id == project_id)
        if not include_archived:
            stmt = stmt.where(PostbackEndpoint.is_archived.is_(False))
        if partner_integration_id is not None:
            stmt = stmt.where(
                PostbackEndpoint.partner_integration_id == partner_integration_id,
            )
        endpoints = list(
            (
                await self.db.execute(
                    stmt.order_by(PostbackEndpoint.created_at.desc())
                )
            ).scalars().all()
        )
        return [self._endpoint_out(endpoint) for endpoint in endpoints]

    async def create_endpoint(
        self,
        *,
        project_id: UUID,
        actor: User,
        data: PostbackEndpointCreate,
    ) -> PostbackEndpointOut:
        self._ensure_manage_access(actor, project_id)
        await self._validate_integration(project_id, data.partner_integration_id)
        if data.parameter_mapping.identifier_type == "offer_token":
            from app.models.gambling_offer import GamblingOffer
            offer = await self.db.get(GamblingOffer, data.parameter_mapping.offer_id) if data.parameter_mapping.offer_id else None
            if not offer or offer.project_id != project_id or data.processing_kind != "lifecycle_event":
                raise HTTPException(422, "Персональный идентификатор требует оффер этого проекта и события REG / FD / RD")
        if data.processing_kind == "submission_status" and data.partner_integration_id is None:
            raise HTTPException(422, "Для статуса подачи выберите покупателя.")
        endpoint = PostbackEndpoint(
            project_id=project_id,
            processing_kind=data.processing_kind,
            partner_integration_id=data.partner_integration_id,
            name=data.name,
            secret_token=secrets.token_urlsafe(32),
            event_type=LeadEventService.normalize_event_type(data.event_type),
            parameter_mapping=data.parameter_mapping.model_dump(mode="json"),
            is_active=data.is_active,
        )
        self.db.add(endpoint)
        await self.db.flush()
        await self.db.refresh(endpoint)
        from app.services.postback_contract_service import snapshot
        await snapshot(self.db, endpoint)
        return self._endpoint_out(endpoint)

    async def update_endpoint(
        self,
        *,
        endpoint_id: UUID,
        project_id: UUID,
        actor: User,
        data: PostbackEndpointUpdate,
    ) -> PostbackEndpointOut:
        self._ensure_manage_access(actor, project_id)
        endpoint = await self.db.scalar(select(PostbackEndpoint).where(PostbackEndpoint.id == endpoint_id,
            PostbackEndpoint.project_id == project_id, PostbackEndpoint.is_archived.is_(False)).with_for_update())
        if endpoint is None:
            raise HTTPException(404, "Postback endpoint not found")
        from app.services.postback_contract_service import snapshot
        await snapshot(self.db, endpoint)
        values = data.model_dump(exclude_unset=True)
        if (endpoint.parameter_mapping or {}).get("offer_id"):
            if (data.parameter_mapping is not None and data.parameter_mapping.model_dump(mode="json") != endpoint.parameter_mapping
                    or any(key in values and values[key] != getattr(endpoint, key) for key in ("processing_kind", "event_type", "partner_integration_id"))):
                raise HTTPException(409, "Правила оффера меняются в настройках оффера; старый адрес сохраняется")
        for key in ("name", "event_type", "parameter_mapping", "is_active", "processing_kind"):
            if key in values and values[key] is None:
                raise HTTPException(422, f"{key} cannot be null")
        if values.get("processing_kind", endpoint.processing_kind) == "submission_status" and not values.get("partner_integration_id", endpoint.partner_integration_id):
            raise HTTPException(422, "Для статуса подачи выберите покупателя.")
        if "partner_integration_id" in values:
            await self._validate_integration(project_id, values["partner_integration_id"])
        if "event_type" in values and values["event_type"] is not None:
            values["event_type"] = LeadEventService.normalize_event_type(values["event_type"])
        if "parameter_mapping" in values and values["parameter_mapping"] is not None:
            mapping = data.parameter_mapping
            assert mapping is not None
            values["parameter_mapping"] = mapping.model_dump(mode="json")
        values["revision"] = endpoint.revision + 1
        result = await self.db.execute(
            update(PostbackEndpoint)
            .where(
                PostbackEndpoint.id == endpoint_id,
                PostbackEndpoint.project_id == project_id,
            )
            .values(**values)
            .returning(PostbackEndpoint)
        )
        endpoint = result.scalar_one_or_none()
        if endpoint is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Postback endpoint not found")
        await snapshot(self.db, endpoint)
        return self._endpoint_out(endpoint)

    async def rotate_secret(
        self,
        *,
        endpoint_id: UUID,
        project_id: UUID,
        actor: User,
        revoke_old: bool = False,
    ) -> PostbackEndpointOut:
        self._ensure_manage_access(actor, project_id)
        from app.services.postback_contract_service import snapshot, now
        from app.models.postback import PostbackEndpointRevision
        from datetime import timedelta
        endpoint = await self.db.scalar(select(PostbackEndpoint).where(PostbackEndpoint.id == endpoint_id,
            PostbackEndpoint.project_id == project_id, PostbackEndpoint.is_archived.is_(False)).with_for_update())
        if endpoint is None:
            raise HTTPException(404)
        await snapshot(self.db, endpoint)
        deadline = now() + timedelta(seconds=0 if revoke_old else max(0, settings.POSTBACK_ROTATION_GRACE_SECONDS))
        import hashlib
        await self.db.execute(update(PostbackEndpointRevision).where(PostbackEndpointRevision.endpoint_id == endpoint_id,
            PostbackEndpointRevision.token_hash == hashlib.sha256(endpoint.secret_token.encode()).hexdigest()).values(valid_until=deadline))
        if revoke_old:
            await self.db.execute(update(PostbackEndpointRevision).where(PostbackEndpointRevision.endpoint_id == endpoint_id)
                .values(valid_until=deadline, revoked=True))
        endpoint = await self.db.scalar(
            update(PostbackEndpoint)
            .where(
                PostbackEndpoint.id == endpoint_id,
                PostbackEndpoint.project_id == project_id,
            )
            .values(secret_token=secrets.token_urlsafe(32), updated_at=func.now(), revision=endpoint.revision + 1)
            .returning(PostbackEndpoint)
        )
        if endpoint is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Postback endpoint not found")
        await snapshot(self.db, endpoint)
        return self._endpoint_out(endpoint)

    async def delete_endpoint(
        self,
        *,
        endpoint_id: UUID,
        project_id: UUID,
        actor: User,
    ) -> None:
        self._ensure_manage_access(actor, project_id)
        result = await self.db.execute(
            update(PostbackEndpoint).where(
                PostbackEndpoint.id == endpoint_id,
                PostbackEndpoint.project_id == project_id,
            ).values(is_archived=True, is_active=False, updated_at=func.now())
        )
        if not result.rowcount:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Postback endpoint not found")

    async def list_receipts(
        self,
        *,
        endpoint_id: UUID,
        project_id: UUID,
        actor: User,
        limit: int,
    ) -> list[PostbackReceipt]:
        self._ensure_manage_access(actor, project_id)
        endpoint_exists = await self.db.scalar(
            select(PostbackEndpoint.id).where(
                PostbackEndpoint.id == endpoint_id,
                PostbackEndpoint.project_id == project_id,
            )
        )
        if endpoint_exists is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Postback endpoint not found")
        return list(
            (
                await self.db.execute(
                    select(PostbackReceipt)
                    .where(PostbackReceipt.endpoint_id == endpoint_id)
                    .order_by(PostbackReceipt.created_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
        )

    async def receive(
        self,
        *,
        secret_token: str,
        request_method: str,
        query_payload: dict[str, Any],
        body_payload: dict[str, Any],
        received_at=None,
        endpoint_id=None,
        revision=None,
    ) -> PublicPostbackResult:
        from app.services.postback_contract_service import PostbackContractService
        return await PostbackContractService(self.db).receive(token=secret_token, method=request_method,
            query=query_payload, body=body_payload, received_at=received_at, endpoint_id=endpoint_id, revision=revision)

    async def _match_lead(
        self,
        *,
        endpoint: PostbackEndpoint,
        identifier_type: str,
        identifier: Any,
    ) -> Lead | None:
        from app.services.postback_contract_service import PostbackContractService, config_of
        mapping = PostbackParameterMapping(identifier_type=identifier_type)
        lead, _, _, error = await PostbackContractService(self.db).match(endpoint, config_of(endpoint), mapping, str(identifier or ""))
        return lead if error is None else None

    async def _validate_integration(
        self,
        project_id: UUID,
        integration_id: UUID | None,
    ) -> None:
        if integration_id is None:
            return
        exists = await self.db.scalar(
            select(PartnerIntegration.id).where(
                PartnerIntegration.id == integration_id,
                PartnerIntegration.project_id == project_id,
            )
        )
        if exists is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Partner integration does not belong to the current project",
            )

    def _endpoint_out(self, endpoint: PostbackEndpoint) -> PostbackEndpointOut:
        from app.services.postback_relay_service import public_base_url, project_scope
        scope = project_scope() if settings.POSTBACK_RELAY_ENABLED else set()
        use_relay = settings.POSTBACK_RELAY_ENABLED and (scope is None or endpoint.project_id in scope)
        return PostbackEndpointOut(
            id=endpoint.id,
            project_id=endpoint.project_id,
            partner_integration_id=endpoint.partner_integration_id,
            name=endpoint.name,
            event_type=endpoint.event_type,
            processing_kind=endpoint.processing_kind,
            is_archived=endpoint.is_archived,
            revision=endpoint.revision,
            parameter_mapping=PostbackParameterMapping.model_validate(
                endpoint.parameter_mapping or {},
            ),
            is_active=endpoint.is_active,
            delivery_mode="relay" if use_relay and settings.POSTBACK_PUBLIC_BASE_URL else "direct",
            url=(
                f"{public_base_url() if use_relay else settings.BASE_URL.rstrip('/')}/pb/{endpoint.secret_token}"
            ),
            created_at=endpoint.created_at,
            updated_at=endpoint.updated_at,
        )

    @staticmethod
    def _extract_value(payload: dict[str, Any], path: str | None) -> Any:
        if not path:
            return None
        current: Any = payload
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    @staticmethod
    def _parse_amount(value: Any) -> Decimal | None:
        from app.services.postback_contract_service import amount_value
        return amount_value(value)

    @staticmethod
    def _escaped_contains(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    @staticmethod
    def _ensure_manage_access(actor: User, project_id: UUID) -> None:
        require_project_access(actor, project_id)
        if actor.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only super_admin/admin can manage postback endpoints",
            )
