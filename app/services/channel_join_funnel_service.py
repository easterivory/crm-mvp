from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LeadStatusCode
from app.core.lead_names import compose_lead_name, normalize_name_part
from app.models.channel_tracking import TelegramChannelSubscriptionEvent
from app.models.chat import Chat
from app.repositories.chat_repository import ChatRepository
from app.repositories.lead_repository import LeadRepository
from app.services.funnel_runtime_service import FunnelRuntimeService


@dataclass(frozen=True, slots=True)
class ChannelJoinFunnelResult:
    chat_id: UUID
    started: bool
    already_started: bool = False
    error: str | None = None


class ChannelJoinFunnelUnavailable(RuntimeError):
    pass


class ChannelJoinFunnelService:
    """Create the private CRM identity and start the tracker bot's active funnel."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.chat_repo = ChatRepository(db)
        self.lead_repo = LeadRepository(db)
        self.runtime = FunnelRuntimeService(
            db,
            release_transaction_before_external_io=True,
            raise_on_telegram_delivery_error=True,
        )

    async def start_for_join_request(
        self,
        *,
        event: TelegramChannelSubscriptionEvent,
        user_chat_id: int,
    ) -> ChannelJoinFunnelResult:
        chat = await self._ensure_chat(event=event, user_chat_id=user_chat_id)
        await self._ensure_lead(event=event, chat_id=chat.id)
        # The CRM identity must survive even when no funnel is published yet.
        await self.db.commit()

        active_funnel, active_version = (
            await self.runtime.get_active_published_funnel_for_bot(
                event.tracker_bot_id,
                event.project_id,
            )
        )
        if active_funnel is None or active_version is None:
            return ChannelJoinFunnelResult(
                chat_id=chat.id,
                started=False,
                error="У бота-трекера нет активной опубликованной воронки",
            )

        state = await self.runtime.repo.get_chat_funnel_state(chat.id)
        if state is not None:
            return ChannelJoinFunnelResult(
                chat_id=chat.id,
                started=False,
                already_started=True,
            )

        await self.runtime.start_funnel_for_chat(
            chat_id=chat.id,
            funnel_id=active_funnel.id,
            funnel_version_id=active_version.id,
        )
        started_state = await self.runtime.repo.get_chat_funnel_state(chat.id)
        if started_state is None:
            return ChannelJoinFunnelResult(
                chat_id=chat.id,
                started=False,
                error="Активная воронка не содержит исполняемого стартового пути",
            )
        return ChannelJoinFunnelResult(chat_id=chat.id, started=True)

    async def _ensure_chat(
        self,
        *,
        event: TelegramChannelSubscriptionEvent,
        user_chat_id: int,
    ) -> Chat:
        external_chat_id = str(user_chat_id)
        external_user_id = str(event.telegram_user_id)
        chat = await self.chat_repo.get_by_external(
            event.project_id,
            external_chat_id,
            bot_id=event.tracker_bot_id,
        )
        if chat is None:
            chat = await self.chat_repo.get_by_external_user(
                project_id=event.project_id,
                bot_id=event.tracker_bot_id,
                external_user_id=external_user_id,
            )
        contact_name = compose_lead_name(event.first_name, event.last_name)
        has_click_attribution = bool(
            isinstance(getattr(event, "attribution_data_json", None), dict)
            and event.attribution_data_json
        )
        if chat is not None:
            updates: dict[str, object] = {}
            if chat.external_chat_id != external_chat_id:
                updates["external_chat_id"] = external_chat_id
            if event.tracking_link_id is not None and (
                chat.tracking_link_id is None
                or (
                    has_click_attribution
                    and chat.tracking_link_id != event.tracking_link_id
                )
            ):
                updates["tracking_link_id"] = event.tracking_link_id
            if contact_name and not chat.contact_name:
                updates["contact_name"] = contact_name
            if updates:
                chat = await self.chat_repo.update_by_id(chat.id, **updates) or chat
            return chat

        try:
            async with self.db.begin_nested():
                return await self.chat_repo.create(
                    project_id=event.project_id,
                    bot_id=event.tracker_bot_id,
                    tracking_link_id=event.tracking_link_id,
                    external_chat_id=external_chat_id,
                    external_user_id=external_user_id,
                    contact_name=contact_name,
                )
        except IntegrityError:
            winner = await self.chat_repo.get_by_external(
                event.project_id,
                external_chat_id,
                bot_id=event.tracker_bot_id,
            )
            if winner is None:
                raise
            return winner

    async def _ensure_lead(
        self,
        *,
        event: TelegramChannelSubscriptionEvent,
        chat_id: UUID,
    ) -> None:
        attribution_data = (
            dict(event.attribution_data_json)
            if isinstance(getattr(event, "attribution_data_json", None), dict)
            else {}
        )
        existing = await self.lead_repo.get_by_chat(chat_id, event.project_id)
        if existing is not None:
            existing_fields = dict(existing.custom_fields or {})
            if attribution_data and existing_fields.get("fb_data") != attribution_data:
                existing_fields["fb_data"] = attribution_data
                await self.lead_repo.update_contact(
                    existing.id,
                    event.project_id,
                    custom_fields=existing_fields,
                )
            return
        status = await self.lead_repo.get_status_by_code(LeadStatusCode.NEW)
        if status is None:
            raise ChannelJoinFunnelUnavailable(
                "В CRM отсутствует обязательный статус лида new"
            )
        first_name = normalize_name_part(event.first_name)
        last_name = normalize_name_part(event.last_name)
        custom_fields = {
            key: value
            for key, value in {
                "first_name": first_name,
                "last_name": last_name,
            }.items()
            if value
        }
        if attribution_data:
            custom_fields["fb_data"] = attribution_data
        try:
            async with self.db.begin_nested():
                await self.lead_repo.create(
                    project_id=event.project_id,
                    chat_id=chat_id,
                    status_id=status.id,
                    name=compose_lead_name(first_name, last_name),
                    username=event.username,
                    custom_fields=custom_fields,
                )
        except IntegrityError:
            if await self.lead_repo.get_by_chat(chat_id, event.project_id) is None:
                raise
