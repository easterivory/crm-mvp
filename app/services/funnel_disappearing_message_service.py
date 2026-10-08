"""Opt-in send-before-delete screens; never delete arbitrary chat messages."""
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SenderType
from app.models.chat import Chat
from app.models.message import Message
from app.repositories.bot_repository import BotRepository
from app.repositories.funnel_repository import FunnelRepository
from app.repositories.message_repository import MessageRepository
from app.schemas.message import MessageOut
from app.services.telegram_sender import TelegramDeliveryError, TelegramSenderService

logger = logging.getLogger(__name__)
MARKER = "disappearing_funnel_message"


class FunnelDisappearingMessageService:
    def __init__(self, db: AsyncSession, sender: TelegramSenderService) -> None:
        self.db = db
        self.sender = sender
        self.funnels = FunnelRepository(db)

    async def candidate(self, chat: Chat, marker: object, *, now: datetime) -> Message | None:
        if not isinstance(marker, str):
            return None
        try:
            message_id = UUID(marker)
        except ValueError:
            return None
        message = await self.db.scalar(select(Message).where(
            Message.id == message_id, Message.chat_id == chat.id,
            Message.sender_type == SenderType.BOT, Message.deleted_at.is_(None),
        ))
        if message is None or not str(message.external_message_id or "").isdigit():
            return None
        if message.created_at <= now - timedelta(hours=48):
            return None
        if chat.current_cycle_started_at and message.created_at < chat.current_cycle_started_at:
            return None
        return message

    async def after_delivery(
        self, *, chat: Chat, message: MessageOut | Message | None,
        disappear_after_next: bool = False,
    ) -> None:
        if (message is None or message.sender_type != SenderType.BOT
                or not str(message.external_message_id or "").isdigit()):
            return
        state = await self.funnels.get_chat_funnel_state(chat.id)
        if state is None:
            return
        state_id = state.id
        runtime = dict(state.runtime_json or {})
        previous_id = runtime.get(MARKER)
        if previous_id is None and not disappear_after_next:
            return
        if await BotRepository(self.db).get_transport_type(chat.bot_id, chat.project_id) != "bot_api":
            return
        now = datetime.now(timezone.utc)
        previous = await self.candidate(chat, previous_id, now=now)
        if previous is not None and previous.id != message.id:
            try:
                deleted = await self.sender.delete_message(
                    project_id=chat.project_id, bot_id=chat.bot_id,
                    external_chat_id=chat.external_chat_id,
                    message_id=int(previous.external_message_id),
                )
            except TelegramDeliveryError as exc:
                # The next message is already delivered. Retrying the step would duplicate it.
                deleted = False
                logger.warning("Funnel screen delete rejected chat_id=%s message_id=%s error=%s",
                    chat.id, previous.id, exc)
            if deleted:
                previous.raw_payload_json = {
                    **(previous.raw_payload_json or {}),
                    "funnel_screen_deleted": True,
                    "replaced_by_message_id": str(message.id),
                }
                await MessageRepository(self.db).mark_deleted(message_id=previous.id, deleted_at=now)
            else:
                logger.warning("Funnel screen retained after delete failure chat_id=%s message_id=%s replacement_id=%s",
                    chat.id, previous.id, message.id)
        elif previous_id:
            logger.info("Funnel screen cleanup skipped (expired, reset or unavailable) chat_id=%s message_id=%s",
                chat.id, previous_id)
        # Sender may commit before external I/O. Do not restore a reset state or
        # overwrite answers/markers changed while the network request was running.
        state = await self.funnels.get_chat_funnel_state(chat.id)
        if state is None or state.id != state_id:
            return
        await self.db.refresh(state)
        runtime = dict(state.runtime_json or {})
        if runtime.get(MARKER) != previous_id:
            return
        runtime.pop(MARKER, None)
        if disappear_after_next:
            runtime[MARKER] = str(message.id)
        await self.funnels.update_chat_funnel_runtime(chat_id=chat.id, runtime_json=runtime)
