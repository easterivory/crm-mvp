from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import extract, func, select
from sqlalchemy.orm import aliased

from app.core.constants import SenderType
from app.models.chat import Chat
from app.models.message import Message
from app.repositories.base import BaseRepository


class MessageRepository(BaseRepository[Message]):
    model = Message

    async def list_by_chat(
        self,
        chat_id: UUID,
        limit: int = 50,
        offset: int = 0,
        since: Optional[datetime] = None,
    ) -> list[Message]:
        stmt = select(Message).where(Message.chat_id == chat_id)
        if since is not None:
            stmt = stmt.where(Message.created_at >= since)
        stmt = stmt.order_by(Message.created_at.asc()).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_by_chat(
        self,
        chat_id: UUID,
        since: Optional[datetime] = None,
    ) -> int:
        stmt = select(func.count(Message.id)).where(Message.chat_id == chat_id)
        if since is not None:
            stmt = stmt.where(Message.created_at >= since)
        result = await self.db.execute(stmt)
        return result.scalar_one()

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

    async def get_first_response_time(self, chat_id: UUID) -> Optional[float]:
        first_user_at = (
            select(func.min(Message.created_at))
            .where(
                Message.chat_id == chat_id,
                Message.sender_type == SenderType.USER,
            )
            .scalar_subquery()
        )
        first_manager_reply_at = (
            select(func.min(Message.created_at))
            .where(
                Message.chat_id == chat_id,
                Message.sender_type == SenderType.MANAGER,
                Message.created_at > first_user_at,
            )
            .scalar_subquery()
        )

        result = await self.db.execute(
            select(extract("epoch", first_manager_reply_at - first_user_at)).where(
                first_user_at.is_not(None),
                first_manager_reply_at.is_not(None),
            )
        )
        value = result.scalar_one_or_none()
        return float(value) if value is not None else None

    async def avg_response_seconds(self, chat_id: UUID) -> Optional[float]:
        user_message = aliased(Message)
        manager_message = aliased(Message)

        next_manager_reply_at = (
            select(func.min(manager_message.created_at))
            .where(
                manager_message.chat_id == user_message.chat_id,
                manager_message.sender_type == SenderType.MANAGER,
                manager_message.created_at > user_message.created_at,
            )
            .correlate(user_message)
            .scalar_subquery()
        )

        result = await self.db.execute(
            select(
                func.avg(extract("epoch", next_manager_reply_at - user_message.created_at))
            ).where(
                user_message.chat_id == chat_id,
                user_message.sender_type == SenderType.USER,
                next_manager_reply_at.is_not(None),
            )
        )
        value = result.scalar_one_or_none()
        return float(value) if value is not None else None

    async def avg_response_seconds_for_project_date(
        self,
        project_id: UUID,
        target_date: date,
    ) -> Optional[float]:
        start_at = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
        end_at = start_at + timedelta(days=1)

        user_message = aliased(Message)
        manager_message = aliased(Message)

        next_manager_reply_at = (
            select(func.min(manager_message.created_at))
            .where(
                manager_message.chat_id == user_message.chat_id,
                manager_message.sender_type == SenderType.MANAGER,
                manager_message.created_at > user_message.created_at,
            )
            .correlate(user_message)
            .scalar_subquery()
        )

        result = await self.db.execute(
            select(
                func.avg(extract("epoch", next_manager_reply_at - user_message.created_at))
            )
            .join(Chat, Chat.id == user_message.chat_id)
            .where(
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                user_message.sender_type == SenderType.USER,
                user_message.created_at >= start_at,
                user_message.created_at < end_at,
                next_manager_reply_at.is_not(None),
            )
        )
        value = result.scalar_one_or_none()
        return float(value) if value is not None else None

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
