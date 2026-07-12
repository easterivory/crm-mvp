from __future__ import annotations

import hashlib
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.facebook_events import (
    FACEBOOK_BROWSER_SOURCE_EVENTS,
    facebook_mapping_for_source,
    normalize_facebook_source_event,
)
from app.models.chat import Chat
from app.models.lead import Lead
from app.models.tracking import TrackingLink
from app.services.facebook_capi_queue import enqueue_facebook_capi_event


class FacebookCampaignService:
    TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def enqueue_mapped_event(
        self,
        *,
        lead_id: UUID,
        source_event: str,
        event_reference: str,
        extra_custom_data: dict[str, Any] | None = None,
    ) -> str | None:
        normalized_source = normalize_facebook_source_event(source_event)
        if normalized_source in FACEBOOK_BROWSER_SOURCE_EVENTS:
            return None

        lead = await self._load_lead(lead_id)
        if lead is None or lead.chat is None or lead.chat.tracking_link is None:
            return None
        link = lead.chat.tracking_link
        if (
            not link.fb_campaign_enabled
            or not link.fb_pixel_id
            or not link.fb_capi_token
        ):
            return None

        mapping = facebook_mapping_for_source(
            link.fb_event_mappings_json,
            normalized_source,
        )
        if mapping is None:
            return None

        custom_data = self._render_parameters(
            mapping.get("parameters"),
            lead=lead,
            tracking_link=link,
        )
        custom_data.update(extra_custom_data or {})
        custom_data["crm_source_event"] = normalized_source
        event_id = self.build_event_id(
            tracking_link_id=link.id,
            lead_id=lead.id,
            source_event=normalized_source,
            event_reference=event_reference,
        )
        fb_data = lead.custom_fields.get("fb_data") if isinstance(lead.custom_fields, dict) else None
        event_source_url = (
            str(fb_data.get("event_source_url") or "").strip()
            if isinstance(fb_data, dict)
            else None
        )
        return await enqueue_facebook_capi_event(
            lead_id=lead.id,
            tracking_link_id=link.id,
            event_name=mapping["event_name"],
            custom_data=custom_data,
            event_time=int(time.time()),
            event_id=event_id,
            event_source_url=event_source_url or None,
        )

    async def _load_lead(self, lead_id: UUID) -> Lead | None:
        result = await self.db.execute(
            select(Lead)
            .options(
                selectinload(Lead.chat)
                .selectinload(Chat.tracking_link)
                .selectinload(TrackingLink.bot),
                selectinload(Lead.chat)
                .selectinload(Chat.tracking_link)
                .selectinload(TrackingLink.buyer),
                selectinload(Lead.project),
            )
            .where(Lead.id == lead_id, Lead.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    @staticmethod
    def build_event_id(
        *,
        tracking_link_id: UUID,
        lead_id: UUID,
        source_event: str,
        event_reference: str,
    ) -> str:
        material = ":".join(
            (
                str(tracking_link_id),
                str(lead_id),
                source_event,
                str(event_reference).strip()[:200],
            )
        )
        return f"crm_{hashlib.sha256(material.encode('utf-8')).hexdigest()}"

    def _render_parameters(
        self,
        raw_parameters: object,
        *,
        lead: Lead,
        tracking_link: TrackingLink,
    ) -> dict[str, Any]:
        if not isinstance(raw_parameters, dict):
            return {}
        context = self._template_context(lead, tracking_link)
        rendered: dict[str, Any] = {}
        for raw_key, raw_value in raw_parameters.items():
            key = str(raw_key)
            value = self._render_value(raw_value, context)
            if value is None or value == "":
                continue
            if key == "value":
                numeric = self._decimal_number(value)
                if numeric is None:
                    continue
                value = numeric
            elif key == "currency":
                currency = str(value).strip().upper()
                if not re.fullmatch(r"[A-Z]{3}", currency):
                    continue
                value = currency
            rendered[key] = value
        return rendered

    @staticmethod
    def _template_context(lead: Lead, tracking_link: TrackingLink) -> dict[str, Any]:
        custom_fields = lead.custom_fields if isinstance(lead.custom_fields, dict) else {}
        expected_start_amount = custom_fields.get("expected_start_amount")
        if expected_start_amount is None:
            expected_start_amount = custom_fields.get("budget")
        buyer = tracking_link.buyer
        project = lead.project
        bot = tracking_link.bot
        return {
            "lead": {
                "id": str(lead.id),
                "name": lead.name,
                "phone": lead.phone,
                "age": lead.age,
                "country": lead.country,
                "expected_start_amount": expected_start_amount,
                "custom": custom_fields,
            },
            "tracking": {
                "id": str(tracking_link.id),
                "code": tracking_link.code or tracking_link.ref_code,
            },
            "buyer": {
                "name": buyer.name if buyer is not None else tracking_link.buyer_name,
            },
            "project": {"name": project.name if project is not None else None},
            "bot": {"name": bot.name if bot is not None else None},
        }

    def _render_value(self, raw_value: object, context: dict[str, Any]) -> Any:
        if not isinstance(raw_value, str):
            return raw_value
        exact = self.TEMPLATE_RE.fullmatch(raw_value.strip())
        if exact is not None:
            return self._lookup_context(context, exact.group(1))

        def replace(match: re.Match[str]) -> str:
            resolved = self._lookup_context(context, match.group(1))
            return "" if resolved is None else str(resolved)

        return self.TEMPLATE_RE.sub(replace, raw_value).strip()

    @staticmethod
    def _lookup_context(context: dict[str, Any], path: str) -> Any:
        current: Any = context
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    @staticmethod
    def _decimal_number(value: Any) -> int | float | None:
        try:
            decimal_value = Decimal(str(value).replace(",", ".").strip())
        except (InvalidOperation, ValueError):
            return None
        if not decimal_value.is_finite():
            return None
        if decimal_value == decimal_value.to_integral_value():
            return int(decimal_value)
        return float(decimal_value)
