from __future__ import annotations

import hashlib
import logging
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.facebook_events import (
    FACEBOOK_AUTOMATIC_SOURCE_EVENTS,
    FACEBOOK_BROWSER_SOURCE_EVENTS,
    facebook_mapping_has_trigger,
    facebook_mapping_for_source,
    normalize_facebook_event_mappings,
    normalize_facebook_source_event,
)
from app.models.chat import Chat
from app.models.lead import Lead
from app.models.lead_status import LeadStatus
from app.models.tag import Tag
from app.models.tracking import TrackingLink
from app.services.facebook_capi_queue import enqueue_facebook_capi_event


logger = logging.getLogger(__name__)


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
        link = self._campaign_link(lead)
        if lead is None or link is None:
            return None

        mapping = facebook_mapping_for_source(
            link.fb_event_mappings_json,
            normalized_source,
        )
        if mapping is None:
            return None

        if (
            normalized_source not in FACEBOOK_AUTOMATIC_SOURCE_EVENTS
            and not facebook_mapping_has_trigger(
                mapping,
                trigger_type="funnel_action",
            )
        ):
            return None

        has_data_rule = any(
            isinstance(trigger, dict)
            and trigger.get("type") in {"lead_status", "lead_tag"}
            for trigger in mapping.get("triggers") or []
        )
        effective_reference = (
            f"crm_rule:{normalized_source}:{self._lifecycle_reference(lead)}"
            if has_data_rule
            else event_reference
        )

        return await self._enqueue_mapping(
            lead=lead,
            link=link,
            mapping=mapping,
            source_event=normalized_source,
            event_reference=effective_reference,
            extra_custom_data=extra_custom_data,
        )

    async def enqueue_triggered_events(
        self,
        *,
        lead_id: UUID,
        trigger_type: str,
        trigger_value: UUID | str,
    ) -> list[str]:
        normalized_type = str(trigger_type or "").strip().lower()
        if normalized_type not in {"lead_status", "lead_tag"}:
            raise ValueError(f"Unsupported Facebook CRM trigger type: {trigger_type}")
        normalized_value = str(UUID(str(trigger_value)))

        lead = await self._load_lead(lead_id)
        link = self._campaign_link(lead)
        if lead is None or link is None:
            return []
        try:
            mappings = normalize_facebook_event_mappings(
                link.fb_event_mappings_json
            )
        except ValueError:
            logger.exception(
                "Invalid Facebook event mappings; CRM trigger skipped "
                "lead_id=%s tracking_link_id=%s",
                lead.id,
                link.id,
            )
            return []

        lifecycle_reference = self._lifecycle_reference(lead)
        queued_job_ids: list[str] = []
        for mapping in mappings:
            source_event = str(mapping["source_event"])
            if (
                not mapping["enabled"]
                or source_event in FACEBOOK_BROWSER_SOURCE_EVENTS
                or not facebook_mapping_has_trigger(
                    mapping,
                    trigger_type=normalized_type,
                    trigger_value=normalized_value,
                )
            ):
                continue
            job_id = await self._enqueue_mapping(
                lead=lead,
                link=link,
                mapping=mapping,
                source_event=source_event,
                event_reference=f"crm_rule:{source_event}:{lifecycle_reference}",
                extra_custom_data={
                    "crm_trigger_type": normalized_type,
                    "crm_trigger_value": normalized_value,
                },
            )
            if job_id is not None:
                queued_job_ids.append(job_id)
        return queued_job_ids

    async def enqueue_status_change(
        self,
        *,
        lead_id: UUID,
        previous_status_id: UUID,
        current_status_id: UUID,
    ) -> list[str]:
        if previous_status_id == current_status_id:
            return []
        try:
            return await self.enqueue_triggered_events(
                lead_id=lead_id,
                trigger_type="lead_status",
                trigger_value=current_status_id,
            )
        except Exception:
            logger.exception(
                "Facebook status trigger enqueue failed without blocking CRM "
                "lead_id=%s status_id=%s",
                lead_id,
                current_status_id,
            )
            return []

    async def enqueue_tag_added(
        self,
        *,
        lead_id: UUID,
        tag_id: UUID,
    ) -> list[str]:
        try:
            return await self.enqueue_triggered_events(
                lead_id=lead_id,
                trigger_type="lead_tag",
                trigger_value=tag_id,
            )
        except Exception:
            logger.exception(
                "Facebook tag trigger enqueue failed without blocking CRM "
                "lead_id=%s tag_id=%s",
                lead_id,
                tag_id,
            )
            return []

    async def validate_mapping_triggers(
        self,
        *,
        project_id: UUID,
        mappings: object,
    ) -> list[dict[str, Any]]:
        raw_mappings = (
            [
                item.model_dump() if hasattr(item, "model_dump") else item
                for item in mappings
            ]
            if isinstance(mappings, list)
            else mappings
        )
        normalized = normalize_facebook_event_mappings(raw_mappings)
        status_ids: set[UUID] = set()
        tag_ids: set[UUID] = set()
        for mapping in normalized:
            for trigger in mapping.get("triggers") or []:
                trigger_type = trigger.get("type")
                trigger_value = trigger.get("value")
                if trigger_type == "lead_status" and trigger_value:
                    status_ids.add(UUID(str(trigger_value)))
                elif trigger_type == "lead_tag" and trigger_value:
                    tag_ids.add(UUID(str(trigger_value)))

        if status_ids:
            status_result = await self.db.execute(
                select(LeadStatus.id).where(LeadStatus.id.in_(status_ids))
            )
            found_status_ids = set(status_result.scalars().all())
            missing_status_ids = status_ids - found_status_ids
            if missing_status_ids:
                raise ValueError(
                    "Facebook event trigger references unknown lead status: "
                    + ", ".join(sorted(str(item) for item in missing_status_ids))
                )

        if tag_ids:
            tag_result = await self.db.execute(
                select(Tag.id).where(
                    Tag.id.in_(tag_ids),
                    Tag.project_id == project_id,
                )
            )
            found_tag_ids = set(tag_result.scalars().all())
            missing_tag_ids = tag_ids - found_tag_ids
            if missing_tag_ids:
                raise ValueError(
                    "Facebook event trigger references a tag outside this project: "
                    + ", ".join(sorted(str(item) for item in missing_tag_ids))
                )
        return normalized

    async def _enqueue_mapping(
        self,
        *,
        lead: Lead,
        link: TrackingLink,
        mapping: dict[str, Any],
        source_event: str,
        event_reference: str,
        extra_custom_data: dict[str, Any] | None,
    ) -> str | None:

        custom_data = self._render_parameters(
            mapping.get("parameters"),
            lead=lead,
            tracking_link=link,
        )
        custom_data.update(extra_custom_data or {})
        custom_data["crm_source_event"] = source_event
        event_id = self.build_event_id(
            tracking_link_id=link.id,
            lead_id=lead.id,
            source_event=source_event,
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

    @staticmethod
    def _campaign_link(lead: Lead | None) -> TrackingLink | None:
        if lead is None or lead.chat is None or lead.chat.tracking_link is None:
            return None
        link = lead.chat.tracking_link
        if (
            not link.fb_campaign_enabled
            or not link.fb_pixel_id
            or not link.fb_capi_token
        ):
            return None
        return link

    @staticmethod
    def _lifecycle_reference(lead: Lead) -> str:
        if lead.chat is not None and lead.chat.current_cycle_started_at is not None:
            return lead.chat.current_cycle_started_at.isoformat()
        return lead.created_at.isoformat()

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
