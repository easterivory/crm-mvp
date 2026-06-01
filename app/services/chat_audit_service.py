from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ChatEventType, RoleName
from app.models.chat_event_log import ChatEventLog
from app.models.user import User
from app.repositories.chat_event_log_repository import ChatEventLogRepository
from app.repositories.chat_repository import ChatRepository
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


class ChatAuditService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.chat_repo = ChatRepository(db)
        self.user_repo = UserRepository(db)
        self.event_repo = ChatEventLogRepository(db)

    async def log_event(
        self,
        *,
        chat_id: UUID,
        user_id: Optional[UUID],
        event_type: str,
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
        project_id: Optional[UUID] = None,
    ) -> ChatEventLog:
        if event_type not in ChatEventType.ALL:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid chat event type: {event_type}",
            )

        chat = (
            await self.chat_repo.get_active(chat_id, project_id)
            if project_id is not None
            else await self.chat_repo.get_by_id(chat_id)
        )
        if chat is None or chat.is_deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")

        if user_id is not None:
            user = await self.user_repo.get_by_id(user_id)
            if user is None or user.is_deleted:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
            if user.role_name != RoleName.SUPER_ADMIN and user.project_id != chat.project_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User is not a member of this chat project",
                )

        event = await self.event_repo.create_event(
            chat_id=chat.id,
            user_id=user_id,
            event_type=event_type,
            old_value=old_value,
            new_value=new_value,
        )
        logger.info(
            "Chat audit event logged chat_id=%s user_id=%s event_type=%s",
            chat.id,
            user_id,
            event_type,
        )
        return event

    async def list_events(
        self,
        *,
        chat_id: UUID,
        project_id: UUID,
        actor: User,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ChatEventLog]:
        chat = await self.chat_repo.get_active(chat_id, project_id)
        if chat is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
        if actor.role_name != RoleName.SUPER_ADMIN and actor.project_id != chat.project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Chat is not accessible for current user",
            )
        return await self.event_repo.list_by_chat(chat_id, limit=limit, offset=offset)
