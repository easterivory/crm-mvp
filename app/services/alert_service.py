"""
AlertService — checks alert conditions and writes to the alerts table.

No Telegram notifications (DO_NOT_BUILD_YET).
Deduplicates: does not create a new alert if an unread one of the same type
already exists for this project.
"""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AlertType
from app.repositories.alert_repository import AlertRepository
from app.services.chat_service import ChatService


class AlertService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.alert_repo = AlertRepository(db)
        self.chat_service = ChatService(db)

    async def check_and_create(self, project_id: UUID) -> None:
        """
        Run both alert checks for a single project.
        Called by alert_worker for each project in batches.
        """
        await self._check_long_response(project_id)
        await self._check_many_unanswered(project_id)

    async def _check_long_response(self, project_id: UUID) -> None:
        """Creates a long_response alert if red chats exist and no unread alert for this type."""
        red_count = await self.chat_service.count_red(project_id)
        if red_count <= 0:
            return

        has_unread = await self.alert_repo.has_unread(
            project_id=project_id,
            alert_type=AlertType.LONG_RESPONSE,
        )
        if has_unread:
            return

        await self.alert_repo.create(
            project_id=project_id,
            type=AlertType.LONG_RESPONSE,
            payload={"red_count": red_count},
        )

    async def _check_many_unanswered(self, project_id: UUID) -> None:
        """Creates a many_unanswered alert based on a threshold."""
        unanswered_count = await self.chat_service.count_unanswered(project_id)
        if unanswered_count <= 10:
            return

        has_unread = await self.alert_repo.has_unread(
            project_id=project_id,
            alert_type=AlertType.MANY_UNANSWERED,
        )
        if has_unread:
            return

        await self.alert_repo.create(
            project_id=project_id,
            type=AlertType.MANY_UNANSWERED,
            payload={"unanswered_count": unanswered_count},
        )
