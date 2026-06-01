from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.chat_event_log import ChatEventLog
from app.repositories.base import BaseRepository


class ChatEventLogRepository(BaseRepository[ChatEventLog]):
    model = ChatEventLog

    async def create_event(
        self,
        *,
        chat_id: UUID,
        user_id: Optional[UUID],
        event_type: str,
        old_value: Optional[str],
        new_value: Optional[str],
    ) -> ChatEventLog:
        return await self.create(
            chat_id=chat_id,
            user_id=user_id,
            event_type=event_type,
            old_value=old_value,
            new_value=new_value,
        )

    async def list_by_chat(
        self,
        chat_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ChatEventLog]:
        result = await self.db.execute(
            select(ChatEventLog)
            .options(selectinload(ChatEventLog.user))
            .where(ChatEventLog.chat_id == chat_id)
            .order_by(ChatEventLog.created_at.desc(), ChatEventLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())
