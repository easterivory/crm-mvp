from __future__ import annotations

import time
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.facebook_events import facebook_mapping_for_source
from app.models.channel_tracking import TelegramChannel
from app.models.tracking import TrackingLink
from app.schemas.telegram import TelegramUser
from app.services.facebook_capi_queue import enqueue_facebook_channel_event


class FacebookChannelEventService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def enqueue_event(
        self,
        *,
        tracking_link_id: UUID,
        channel: TelegramChannel,
        user: TelegramUser,
        source_event: str,
        update_id: int,
        occurred_at: datetime,
    ) -> str | None:
        result = await self.db.execute(
            select(TrackingLink).where(TrackingLink.id == tracking_link_id)
        )
        link = result.scalar_one_or_none()
        if (
            link is None
            or link.destination_type != "channel"
            or not link.fb_campaign_enabled
            or not link.fb_pixel_id
            or not link.fb_capi_token
        ):
            return None
        mapping = facebook_mapping_for_source(
            link.fb_event_mappings_json,
            source_event,
        )
        if mapping is None or mapping.get("enabled") is False:
            return None
        parameters = self._render_parameters(
            mapping.get("parameters"),
            link=link,
            channel=channel,
        )
        parameters.update(
            {
                "crm_source_event": source_event,
                "channel_id": str(channel.telegram_chat_id),
                "tracking_code": link.code,
            }
        )
        link_id = link.id
        channel_id = channel.id
        telegram_user_id = user.id
        first_name = user.first_name
        last_name = user.last_name
        event_name = str(mapping["event_name"])
        event_time = int(occurred_at.timestamp() or time.time())
        event_id = (
            f"channel:{channel_id}:{telegram_user_id}:{source_event}:{update_id}"
        )

        # Persist the Telegram membership event before touching Redis. A queue
        # outage must never keep the webhook transaction or its DB locks open.
        await self.db.commit()
        return await enqueue_facebook_channel_event(
            tracking_link_id=link_id,
            telegram_user_id=telegram_user_id,
            event_name=event_name,
            first_name=first_name,
            last_name=last_name,
            custom_data=parameters,
            event_time=event_time,
            event_id=event_id,
        )

    @staticmethod
    def _render_parameters(
        raw: object,
        *,
        link: TrackingLink,
        channel: TelegramChannel,
    ) -> dict[str, str]:
        if not isinstance(raw, dict):
            return {}
        replacements = {
            "{{tracking.code}}": link.code,
            "{{channel.title}}": channel.title,
            "{{channel.username}}": channel.username or "",
        }
        rendered: dict[str, str] = {}
        for key, value in raw.items():
            text = str(value)
            for marker, replacement in replacements.items():
                text = text.replace(marker, replacement)
            if text.strip():
                rendered[str(key)] = text.strip()
        return rendered
