from typing import Optional
from uuid import UUID

from sqlalchemy import select

from app.models.message import Message
from app.repositories.base import BaseRepository


class MessageRepository(BaseRepository[Message]):
    model = Message

    async def list_by_chat(
        self,
        chat_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Message]:
        result = await self.db.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_first_user_message(self, chat_id: UUID) -> Optional[Message]:
        result = await self.db.execute(
            select(Message)
            .where(Message.chat_id == chat_id, Message.sender_type == "user")
            .order_by(Message.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_first_manager_reply(self, chat_id: UUID) -> Optional[Message]:
        result = await self.db.execute(
            select(Message)
            .where(Message.chat_id == chat_id, Message.sender_type == "manager")
            .order_by(Message.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_external_id(
        self, chat_id: UUID, external_message_id: str
    ) -> Optional[Message]:
        result = await self.db.execute(
            select(Message).where(
                Message.chat_id == chat_id,
                Message.external_message_id == external_message_id,
            )
        )
        return result.scalar_one_or_none()
