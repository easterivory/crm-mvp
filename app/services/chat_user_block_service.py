from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.models.chat import Chat
from app.repositories.chat_repository import ChatRepository
from app.repositories.funnel_repository import FunnelRepository


class ChatUserBlockService:
    """Persist Telegram user block state and pause active funnel work."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.chat_repo = ChatRepository(db)
        self.funnel_repo = FunnelRepository(db)

    async def set_blocked_by_user(
        self,
        *,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
        is_blocked_by_user: bool,
    ) -> Chat | None:
        chat = await self.chat_repo.set_blocked_by_user(
            project_id=project_id,
            bot_id=bot_id,
            external_chat_id=external_chat_id,
            is_blocked_by_user=is_blocked_by_user,
        )
        if chat is None or not is_blocked_by_user:
            return chat

        state = await self.funnel_repo.get_chat_funnel_state(chat.id)
        if state is None or state.completed_at is not None or state.is_paused:
            return chat

        await self.funnel_repo.cancel_scheduled_jobs_for_chat(chat_id=chat.id)
        await self.funnel_repo.set_chat_funnel_paused(
            chat_id=chat.id,
            is_paused=True,
            paused_at=datetime.now(timezone.utc),
            paused_by_user_id=None,
        )
        return chat

    @classmethod
    async def persist_blocked_from_telegram_error(
        cls,
        *,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
    ) -> bool:
        # The outgoing CRM request returns an error and its transaction rolls
        # back. Keep Telegram's authoritative block state independently. The
        # runtime pause is performed by the native webhook or by the next
        # runtime guard, avoiding a cross-transaction lock on funnel state.
        async with get_db_session() as db:
            try:
                chat = await ChatRepository(db).set_blocked_by_user(
                    project_id=project_id,
                    bot_id=bot_id,
                    external_chat_id=external_chat_id,
                    is_blocked_by_user=True,
                )
                await db.commit()
                return chat is not None
            except Exception:
                await db.rollback()
                raise
