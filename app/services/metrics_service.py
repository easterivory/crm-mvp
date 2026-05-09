"""
MetricsService — SLA calculations.

  first_response_time: time from first user message to first manager reply.
  avg_response_time:   mean across all user→manager reply pairs in a chat.

All queries go through message_repository — no direct SQL here.
"""
from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.message_repository import MessageRepository


class MetricsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.message_repo = MessageRepository(db)

    async def first_response_seconds(self, chat_id: UUID) -> Optional[float]:
        """
        Returns seconds between the first user message and the first manager reply.
        Returns None if the manager has not replied yet.
        """
        return await self.message_repo.get_first_response_time(chat_id)

    async def avg_response_seconds(self, chat_id: UUID) -> Optional[float]:
        """Average response time across all user→manager reply pairs."""
        return await self.message_repo.avg_response_seconds(chat_id)

    async def avg_response_seconds_for_project_date(
        self,
        project_id: UUID,
        target_date: date,
    ) -> Optional[float]:
        """Average response time for user messages created on target_date."""
        return await self.message_repo.avg_response_seconds_for_project_date(
            project_id=project_id,
            target_date=target_date,
        )
