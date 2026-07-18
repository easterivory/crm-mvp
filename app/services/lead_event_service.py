from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ChatEventType
from app.models.lead import Lead
from app.models.lead_event import LeadEvent
from app.models.partner import PartnerIntegration
from app.models.user import User
from app.services.access_control import require_project_access
from app.services.chat_audit_service import ChatAuditService


EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,99}$")


class LeadEventService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.chat_audit = ChatAuditService(db)

    async def record_event(
        self,
        *,
        lead: Lead,
        event_type: str,
        source: str,
        amount: Decimal | None = None,
        currency: str | None = None,
        partner_integration_id: UUID | None = None,
        postback_endpoint_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
        external_event_id: str | None = None,
        payload: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> tuple[LeadEvent, bool]:
        normalized_event_type = self.normalize_event_type(event_type)
        normalized_source = source.strip().lower()
        if not normalized_source or len(normalized_source) > 30:
            raise ValueError("Invalid lead event source")
        if amount is not None and amount < 0:
            raise ValueError("Event amount must not be negative")
        normalized_currency = currency.strip().upper() if currency else None
        if normalized_currency and len(normalized_currency) > 10:
            raise ValueError("Event currency is too long")

        if partner_integration_id is not None:
            integration = await self.db.scalar(
                select(PartnerIntegration).where(
                    PartnerIntegration.id == partner_integration_id,
                    PartnerIntegration.project_id == lead.project_id,
                )
            )
            if integration is None:
                raise ValueError("Partner integration does not belong to the lead project")

        if postback_endpoint_id is not None and external_event_id:
            existing = await self.db.scalar(
                select(LeadEvent).where(
                    LeadEvent.postback_endpoint_id == postback_endpoint_id,
                    LeadEvent.external_event_id == external_event_id,
                )
            )
            if existing is not None:
                return existing, False

        event = LeadEvent(
            project_id=lead.project_id,
            lead_id=lead.id,
            partner_integration_id=partner_integration_id,
            postback_endpoint_id=postback_endpoint_id,
            created_by_user_id=created_by_user_id,
            attributed_manager_id=lead.manager_id,
            event_type=normalized_event_type,
            source=normalized_source,
            amount=amount,
            currency=normalized_currency,
            external_event_id=external_event_id,
            payload_json=dict(payload or {}),
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )
        if postback_endpoint_id is not None and external_event_id:
            try:
                async with self.db.begin_nested():
                    self.db.add(event)
                    await self.db.flush()
            except IntegrityError:
                existing = await self.db.scalar(
                    select(LeadEvent).where(
                        LeadEvent.postback_endpoint_id == postback_endpoint_id,
                        LeadEvent.external_event_id == external_event_id,
                    )
                )
                if existing is not None:
                    return existing, False
                raise
        else:
            self.db.add(event)
            await self.db.flush()
        await self.chat_audit.log_event(
            chat_id=lead.chat_id,
            project_id=lead.project_id,
            user_id=created_by_user_id,
            event_type=ChatEventType.NOTE_ADDED,
            new_value=self._event_log_text(event),
        )
        return event, True

    async def record_manual_event(
        self,
        *,
        lead_id: UUID,
        project_id: UUID,
        actor: User,
        event_type: str,
        amount: Decimal | None,
        currency: str | None,
        partner_integration_id: UUID | None,
        external_event_id: str | None,
        payload: dict[str, Any],
    ) -> LeadEvent:
        require_project_access(actor, project_id)
        lead = await self.db.scalar(
            select(Lead).where(
                Lead.id == lead_id,
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                Lead.is_trash.is_(False),
            )
        )
        if lead is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
        event, _ = await self.record_event(
            lead=lead,
            event_type=event_type,
            source="manual",
            amount=amount,
            currency=currency,
            partner_integration_id=partner_integration_id,
            created_by_user_id=actor.id,
            external_event_id=external_event_id,
            payload=payload,
        )
        return event

    @staticmethod
    def normalize_event_type(value: str) -> str:
        normalized = value.strip().lower()
        if not EVENT_TYPE_RE.fullmatch(normalized):
            raise ValueError(
                "Event type must start with a letter and contain only a-z, 0-9, _, . or -"
            )
        return normalized

    @staticmethod
    def _event_log_text(event: LeadEvent) -> str:
        labels = {
            "registration": "Регистрация",
            "deposit": "Депозит",
            "redeposit": "Повторный депозит",
        }
        label = labels.get(event.event_type, event.event_type)
        amount = ""
        if event.amount is not None:
            amount = f" на сумму {event.amount} {event.currency or ''}".rstrip()
        return f"Событие лида: {label}{amount}. Источник: {event.source}."
