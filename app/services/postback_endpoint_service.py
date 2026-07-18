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
    ) -> list[PostbackEndpointOut]:
        require_project_access(actor, project_id)
        stmt = select(PostbackEndpoint).where(PostbackEndpoint.project_id == project_id)
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
        endpoint = PostbackEndpoint(
            project_id=project_id,
            partner_integration_id=data.partner_integration_id,
            name=data.name,
            secret_token=secrets.token_urlsafe(32),
            event_type=LeadEventService.normalize_event_type(data.event_type),
            parameter_mapping=data.parameter_mapping.model_dump(),
            is_active=data.is_active,
        )
        self.db.add(endpoint)
        await self.db.flush()
        await self.db.refresh(endpoint)
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
        values = data.model_dump(exclude_unset=True)
        if "partner_integration_id" in values:
            await self._validate_integration(project_id, values["partner_integration_id"])
        if "event_type" in values and values["event_type"] is not None:
            values["event_type"] = LeadEventService.normalize_event_type(values["event_type"])
        if "parameter_mapping" in values and values["parameter_mapping"] is not None:
            mapping = data.parameter_mapping
            assert mapping is not None
            values["parameter_mapping"] = mapping.model_dump()
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
        return self._endpoint_out(endpoint)

    async def rotate_secret(
        self,
        *,
        endpoint_id: UUID,
        project_id: UUID,
        actor: User,
    ) -> PostbackEndpointOut:
        self._ensure_manage_access(actor, project_id)
        endpoint = await self.db.scalar(
            update(PostbackEndpoint)
            .where(
                PostbackEndpoint.id == endpoint_id,
                PostbackEndpoint.project_id == project_id,
            )
            .values(secret_token=secrets.token_urlsafe(32), updated_at=func.now())
            .returning(PostbackEndpoint)
        )
        if endpoint is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Postback endpoint not found")
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
            delete(PostbackEndpoint).where(
                PostbackEndpoint.id == endpoint_id,
                PostbackEndpoint.project_id == project_id,
            )
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
        require_project_access(actor, project_id)
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
    ) -> PublicPostbackResult:
        endpoint = await self.db.scalar(
            select(PostbackEndpoint).where(
                PostbackEndpoint.secret_token == secret_token,
                PostbackEndpoint.is_active.is_(True),
            )
        )
        if endpoint is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Postback endpoint not found")

        mapping = PostbackParameterMapping.model_validate(endpoint.parameter_mapping or {})
        merged_payload = {**query_payload, **body_payload}
        identifier = self._extract_value(merged_payload, mapping.identifier_param)
        event_type_value = (
            self._extract_value(merged_payload, mapping.event_type_param)
            if mapping.event_type_param
            else endpoint.event_type
        )
        event_type = str(event_type_value or endpoint.event_type)
        lead = await self._match_lead(
            endpoint=endpoint,
            identifier_type=mapping.identifier_type,
            identifier=identifier,
        )
        receipt = PostbackReceipt(
            endpoint_id=endpoint.id,
            project_id=endpoint.project_id,
            lead_id=lead.id if lead is not None else None,
            request_method=request_method.upper(),
            event_type=event_type[:100],
            status="unmatched",
            query_payload=query_payload,
            body_payload=body_payload,
        )
        self.db.add(receipt)
        await self.db.flush()

        if identifier is None:
            receipt.error_message = f"Parameter '{mapping.identifier_param}' is missing"
            return PublicPostbackResult(status="unmatched", receipt_id=receipt.id)
        if lead is None:
            receipt.error_message = (
                f"Lead not found by {mapping.identifier_type}={str(identifier)[:255]}"
            )
            return PublicPostbackResult(status="unmatched", receipt_id=receipt.id)

        try:
            amount = self._parse_amount(
                self._extract_value(merged_payload, mapping.amount_param)
                if mapping.amount_param
                else None
            )
            currency_value = (
                self._extract_value(merged_payload, mapping.currency_param)
                if mapping.currency_param
                else None
            )
            external_event_id_value = (
                self._extract_value(merged_payload, mapping.external_event_id_param)
                if mapping.external_event_id_param
                else None
            )
            event, created = await self.events.record_event(
                lead=lead,
                event_type=event_type,
                source="postback",
                amount=amount,
                currency=str(currency_value) if currency_value else None,
                partner_integration_id=endpoint.partner_integration_id,
                postback_endpoint_id=endpoint.id,
                external_event_id=(
                    str(external_event_id_value)[:255]
                    if external_event_id_value is not None
                    else None
                ),
                payload=merged_payload,
            )
        except (InvalidOperation, ValueError) as exc:
            receipt.status = "unmatched"
            receipt.error_message = str(exc)[:2000]
            return PublicPostbackResult(
                status="unmatched",
                receipt_id=receipt.id,
                lead_id=lead.id,
            )

        receipt.lead_event_id = event.id
        receipt.status = "processed" if created else "duplicate"
        return PublicPostbackResult(
            status="processed" if created else "duplicate",
            receipt_id=receipt.id,
            lead_id=lead.id,
            event_id=event.id,
        )

    async def _match_lead(
        self,
        *,
        endpoint: PostbackEndpoint,
        identifier_type: str,
        identifier: Any,
    ) -> Lead | None:
        if identifier is None:
            return None
        raw = str(identifier).strip()
        if not raw:
            return None
        base = select(Lead).where(
            Lead.project_id == endpoint.project_id,
            Lead.is_deleted.is_(False),
            Lead.is_trash.is_(False),
        )
        if identifier_type == "lead_id":
            try:
                return await self.db.scalar(base.where(Lead.id == UUID(raw)))
            except ValueError:
                return None
        if identifier_type == "chat_id":
            try:
                return await self.db.scalar(base.where(Lead.chat_id == UUID(raw)))
            except ValueError:
                return None
        if identifier_type == "telegram_id":
            return await self.db.scalar(
                base.join(Chat, Chat.id == Lead.chat_id)
                .where(or_(Chat.external_user_id == raw, Chat.external_chat_id == raw))
                .order_by(Lead.created_at.desc())
                .limit(1)
            )
        if identifier_type == "tracking_code":
            return await self.db.scalar(
                base.join(Chat, Chat.id == Lead.chat_id)
                .join(TrackingLink, TrackingLink.id == Chat.tracking_link_id)
                .where(or_(TrackingLink.code == raw, TrackingLink.ref_code == raw))
                .order_by(Lead.created_at.desc())
                .limit(1)
            )
        if identifier_type == "click_id":
            return await self.db.scalar(
                base.where(
                    or_(
                        Lead.custom_fields["click_id"].astext == raw,
                        Lead.custom_fields["fb_data"]["fbc"].astext == raw,
                        cast(Lead.custom_fields, Text).ilike(self._escaped_contains(raw), escape="\\"),
                    )
                )
                .order_by(Lead.created_at.desc())
                .limit(1)
            )

        submission_stmt = (
            base.join(LeadSubmission, LeadSubmission.lead_id == Lead.id)
            .where(
                or_(
                    cast(LeadSubmission.request_payload, Text).ilike(
                        self._escaped_contains(raw),
                        escape="\\",
                    ),
                    cast(LeadSubmission.response_payload, Text).ilike(
                        self._escaped_contains(raw),
                        escape="\\",
                    ),
                )
            )
            .order_by(LeadSubmission.submitted_at.desc())
            .limit(1)
        )
        if endpoint.partner_integration_id is not None:
            submission_stmt = submission_stmt.where(
                LeadSubmission.partner_integration_id == endpoint.partner_integration_id,
            )
        return await self.db.scalar(submission_stmt)

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
        return PostbackEndpointOut(
            id=endpoint.id,
            project_id=endpoint.project_id,
            partner_integration_id=endpoint.partner_integration_id,
            name=endpoint.name,
            event_type=endpoint.event_type,
            parameter_mapping=PostbackParameterMapping.model_validate(
                endpoint.parameter_mapping or {},
            ),
            is_active=endpoint.is_active,
            url=(
                f"{settings.BASE_URL.rstrip('/')}/pb/{endpoint.secret_token}"
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
        if value is None or value == "":
            return None
        normalized = str(value).strip().replace(" ", "").replace(",", ".")
        amount = Decimal(normalized)
        if amount < 0:
            raise ValueError("Event amount must not be negative")
        return amount

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
