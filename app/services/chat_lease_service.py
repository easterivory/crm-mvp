from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AuditAction, EntityType
from app.repositories.chat_repository import ChatRepository
from app.repositories.project_repository import ProjectRepository
from app.services.audit_service import AuditService


class ChatLeaseService:
    def __init__(self, db: AsyncSession) -> None:
        self.chat_repo = ChatRepository(db)
        self.project_repo = ProjectRepository(db)
        self.audit = AuditService(db)

    async def assignment_deadline(
        self,
        *,
        project_id: UUID,
        manager_id: UUID | None,
    ) -> datetime | None:
        if manager_id is None:
            return None
        project = await self.project_repo.get_active(project_id)
        if project is None or project.chat_lease_minutes <= 0:
            return None
        return datetime.now(timezone.utc) + timedelta(minutes=project.chat_lease_minutes)

    async def release_expired(
        self,
        *,
        project_id: UUID,
        chat_id: UUID | None = None,
    ) -> int:
        project = await self.project_repo.get_active(project_id)
        if project is None or project.chat_lease_minutes <= 0:
            return 0

        now = datetime.now(timezone.utc)
        released = await self.chat_repo.release_expired_assignments(
            project_id=project_id,
            expires_before=now,
            chat_id=chat_id,
        )
        for released_chat_id, lead_id, previous_manager_id in released:
            await self.audit.log(
                project_id=project_id,
                action=AuditAction.LEAD_MANAGER_REMOVED,
                entity_type=EntityType.LEAD,
                entity_id=lead_id,
                actor_id=None,
                meta={
                    "from_manager_id": str(previous_manager_id),
                    "to_manager_id": None,
                    "reason": "chat_lease_expired",
                    "chat_id": str(released_chat_id),
                },
            )
        return len(released)

    async def renew_from_client_message(
        self,
        *,
        project_id: UUID,
        chat_id: UUID,
    ) -> bool:
        project = await self.project_repo.get_active(project_id)
        if project is None or project.chat_lease_minutes <= 0:
            return False
        deadline = datetime.now(timezone.utc) + timedelta(
            minutes=project.chat_lease_minutes,
        )
        return await self.chat_repo.renew_assignment_on_incoming(
            chat_id=chat_id,
            project_id=project_id,
            assignment_expires_at=deadline,
        )
