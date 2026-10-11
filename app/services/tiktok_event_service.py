from __future__ import annotations

import hashlib
import time
from typing import Any
import re
from uuid import UUID, uuid4
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.facebook_events import FACEBOOK_AUTOMATIC_SOURCE_EVENTS, facebook_mapping_has_trigger, normalize_facebook_source_event
from app.models.tiktok import TikTokDelivery, TikTokIntegration
from app.models.channel_tracking import TelegramChannelSubscriptionEvent


class TikTokEventService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def config(self, link_id: UUID) -> TikTokIntegration | None:
        return await self.db.get(TikTokIntegration, link_id)

    async def mapped_event(
        self, *, lead_id: UUID, source_event: str, event_reference: str,
        extra_custom_data: dict | None = None, event_time: int | None = None,
    ) -> None:
        from app.services.facebook_campaign_service import FacebookCampaignService

        helper = FacebookCampaignService(self.db)
        lead = await helper._load_lead(lead_id)
        if lead is None or lead.chat is None or lead.chat.tracking_link is None:
            return
        link = lead.chat.tracking_link
        config = await self.config(link.id)
        if config is None or not config.enabled:
            return
        source = normalize_facebook_source_event(source_event)
        for mapping in config.mappings_json:
            if mapping["source_event"] != source or not mapping.get("enabled", True):
                continue
            if source not in FACEBOOK_AUTOMATIC_SOURCE_EVENTS and not facebook_mapping_has_trigger(mapping, trigger_type="funnel_action"):
                continue
            has_rule = any(t.get("type") in {"lead_status", "lead_tag"} for t in mapping.get("triggers", []))
            reference = f"crm_rule:{source}:{helper._lifecycle_reference(lead)}" if has_rule or source in {"registration", "sale"} else event_reference
            context = (lead.custom_fields or {}).get("fb_data", {})
            properties = helper._render_parameters(mapping.get("parameters"), lead=lead, tracking_link=link)
            properties.update(extra_custom_data or {})
            await self.store(config, mapping, reference=f"{lead.id}:{reference}", context=context,
                             external_id=lead.chat.external_user_id or lead.chat.external_chat_id,
                             phone=lead.phone, properties=properties, event_time=event_time)

    async def triggered_event(self, *, lead_id: UUID, trigger_type: str, trigger_value: UUID | str) -> None:
        from app.services.facebook_campaign_service import FacebookCampaignService

        helper = FacebookCampaignService(self.db)
        lead = await helper._load_lead(lead_id)
        if lead is None or lead.chat is None or lead.chat.tracking_link is None:
            return
        link = lead.chat.tracking_link
        config = await self.config(link.id)
        if config is None or not config.enabled:
            return
        for mapping in config.mappings_json:
            if not mapping.get("enabled", True) or not facebook_mapping_has_trigger(mapping, trigger_type=trigger_type, trigger_value=str(trigger_value)):
                continue
            source = mapping["source_event"]
            await self.store(config, mapping, reference=f"{lead.id}:crm_rule:{source}:{helper._lifecycle_reference(lead)}",
                             context=(lead.custom_fields or {}).get("fb_data", {}),
                             external_id=lead.chat.external_user_id or lead.chat.external_chat_id, phone=lead.phone,
                             properties=helper._render_parameters(mapping.get("parameters"), lead=lead, tracking_link=link))

    async def channel_event(self, *, tracking_link_id: UUID, channel: Any, user: Any,
                            source_event: str, update_id: int, occurred_at: Any) -> None:
        config = await self.config(tracking_link_id)
        if config is None or not config.enabled:
            return
        context = await self.db.scalar(select(TelegramChannelSubscriptionEvent.attribution_data_json).where(
            TelegramChannelSubscriptionEvent.tracking_link_id == tracking_link_id,
            TelegramChannelSubscriptionEvent.telegram_user_id == user.id,
            TelegramChannelSubscriptionEvent.telegram_update_id == update_id))
        for mapping in config.mappings_json:
            if mapping["source_event"] == source_event and mapping.get("enabled", True):
                await self.store(config, mapping, reference=f"channel:{channel.id}:{user.id}:{update_id}",
                                 context=context or {}, external_id=str(user.id), event_time=int(occurred_at.timestamp()),
                                 properties=static_tiktok_parameters(mapping.get("parameters", {})))

    async def browser_event(self, *, link_id: UUID, source: str, start_key: str, context: dict) -> None:
        if source not in {"page_view", "telegram_click"}:
            return
        config = await self.config(link_id)
        if config is None or not config.enabled:
            return
        for mapping in config.mappings_json:
            if mapping["source_event"] == source and mapping.get("enabled", True):
                await self.store(config, mapping, reference=f"browser:{start_key}", context=context,
                                 properties=static_tiktok_parameters(mapping.get("parameters", {})))

    async def store(self, config: TikTokIntegration, mapping: dict, *, reference: str,
                    context: dict, external_id: str | None = None, phone: str | None = None,
                    properties: dict | None = None, event_time: int | None = None) -> None:
        source = mapping["source_event"]
        event_id = tiktok_event_id(config.tracking_link_id, source, reference)
        payload = build_tiktok_payload(pixel_id=config.pixel_id, event_name=mapping["event_name"],
                                     event_id=event_id, event_time=event_time or int(time.time()),
                                     context=context, external_id=external_id, phone=phone,
                                     properties=properties, test_event_code=config.test_event_code)
        await self.db.execute(insert(TikTokDelivery).values(id=uuid4(), tracking_link_id=config.tracking_link_id,
                              event_id=event_id, source_event=source, payload_json=payload)
                              .on_conflict_do_nothing(index_elements=[TikTokDelivery.event_id]))


def tiktok_event_id(link_id: UUID, source: str, reference: str) -> str:
    return "tt_" + hashlib.sha256(f"{link_id}:{source}:{reference}".encode()).hexdigest()


def static_tiktok_parameters(raw: dict) -> dict:
    from app.services.facebook_campaign_service import FacebookCampaignService
    result = {}
    for key, value in raw.items():
        if "{{" in str(value):
            continue
        if key == "value":
            value = FacebookCampaignService._decimal_number(value)
        if key == "currency":
            value = str(value).upper()
            if not re.fullmatch(r"[A-Z]{3}", value):
                continue
        if value is not None:
            result[key] = value
    return result


def build_tiktok_payload(*, pixel_id: str, event_name: str, event_id: str, event_time: int,
                         context: dict, external_id: str | None = None, phone: str | None = None,
                         properties: dict | None = None, test_event_code: str | None = None) -> dict:
    user: dict[str, str] = {}
    context = dict(context)
    if not context.get("ttclid") and isinstance(context.get("event_source_url"), str):
        try:
            context["ttclid"] = parse_qs(urlsplit(context["event_source_url"]).query).get("ttclid", [None])[-1]
        except ValueError:
            pass
    for source, target in {"ttclid": "ttclid", "ttp": "ttp", "client_ip_address": "ip", "client_user_agent": "user_agent"}.items():
        value = context.get(source)
        if isinstance(value, list):
            value = next((v for v in reversed(value) if v), None)
        if isinstance(value, str) and value.strip():
            user[target] = value.strip()[:1000]
    if external_id:
        user["external_id"] = hashlib.sha256(str(external_id).strip().encode()).hexdigest()
    if phone:
        from app.services.facebook_capi_service import FacebookCAPIService
        normalized_hash = FacebookCAPIService._hash_phone(phone)
        if normalized_hash:
            user["phone"] = normalized_hash
    event = {"event": event_name, "event_id": event_id, "event_time": event_time, "user": user,
             "properties": {k: v for k, v in (properties or {}).items() if k in {"value", "currency", "description", "content_id", "content_type", "contents"}}}
    url = context.get("event_source_url")
    if isinstance(url, str) and url.startswith(("https://", "http://")):
        event["page"] = {"url": url[:2048]}
    payload = {"event_source": "web", "event_source_id": pixel_id, "data": [event]}
    if test_event_code:
        payload["test_event_code"] = test_event_code
    return payload
