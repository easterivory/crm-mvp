"""Opt-in send-before-delete screens; never delete arbitrary chat messages."""
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import inspect, or_, select
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
        identity = inspect(chat).identity
        if identity is None:
            return None
        # Message timestamp updates can expire the ORM cycle field. Keep the
        # lifecycle check in SQL instead of triggering implicit async loading.
        message = await self.db.scalar(select(Message).join(Chat, Chat.id == Message.chat_id).where(
            Message.id == message_id, Message.chat_id == identity[0],
            Message.sender_type == SenderType.BOT, Message.deleted_at.is_(None),
            Message.created_at > now - timedelta(hours=48),
            or_(Chat.current_cycle_started_at.is_(None),
                Message.created_at >= Chat.current_cycle_started_at),
        ).execution_options(populate_existing=True))
        if message is None or not str(message.external_message_id or "").isdigit():
            return None
        return message

    async def after_delivery(
        self, *, chat: Chat, message: MessageOut | Message | None,
        disappear_after_next: bool = False,
    ) -> None:
        if (message is None or message.sender_type != SenderType.BOT
                or not str(message.external_message_id or "").isdigit()):
            return
        identity = inspect(chat).identity
        if identity is None:
            return
        chat_id = identity[0]
        message_id = message.id
        state = await self.funnels.get_chat_funnel_state(chat_id)
        if state is None:
            return
        state_id = state.id
        runtime = dict(state.runtime_json or {})
        previous_id = runtime.get(MARKER)
        if previous_id is None and not disappear_after_next:
            return
        destination = (await self.db.execute(select(
            Chat.bot_id, Chat.project_id, Chat.external_chat_id,
        ).where(Chat.id == chat_id))).one_or_none()
        if destination is None:
            return
        bot_id, project_id, external_chat_id = destination
        if await BotRepository(self.db).get_transport_type(bot_id, project_id) != "bot_api":
            return
        now = datetime.now(timezone.utc)
        previous = await self.candidate(chat, previous_id, now=now)
        if previous is not None and previous.id != message_id:
            previous_message_id = previous.id
            previous_external_id = int(previous.external_message_id)
            previous_payload = dict(previous.raw_payload_json or {})
            try:
                deleted = await self.sender.delete_message(
                    project_id=project_id, bot_id=bot_id,
                    external_chat_id=external_chat_id,
                    message_id=previous_external_id,
                )
            except TelegramDeliveryError as exc:
                # The next message is already delivered. Retrying the step would duplicate it.
                deleted = False
                logger.warning("Funnel screen delete rejected chat_id=%s message_id=%s error=%s",
                    chat_id, previous_message_id, exc)
            if deleted:
                previous.raw_payload_json = {
                    **previous_payload,
                    "funnel_screen_deleted": True,
                    "replaced_by_message_id": str(message_id),
                }
                await MessageRepository(self.db).mark_deleted(message_id=previous_message_id, deleted_at=now)
            else:
                logger.warning("Funnel screen retained after delete failure chat_id=%s message_id=%s replacement_id=%s",
                    chat_id, previous_message_id, message_id)
        elif previous_id:
            logger.info("Funnel screen cleanup skipped (expired, reset or unavailable) chat_id=%s message_id=%s",
                chat_id, previous_id)
        # Sender may commit before external I/O. Do not restore a reset state or
        # overwrite answers/markers changed while the network request was running.
        state = await self.funnels.get_chat_funnel_state(chat_id)
        if state is None:
            return
        await self.db.refresh(state)
        if state.id != state_id:
            return
        runtime = dict(state.runtime_json or {})
        if runtime.get(MARKER) != previous_id:
            return
        runtime.pop(MARKER, None)
        if disappear_after_next:
            runtime[MARKER] = str(message_id)
        await self.funnels.update_chat_funnel_runtime(chat_id=chat_id, runtime_json=runtime)
