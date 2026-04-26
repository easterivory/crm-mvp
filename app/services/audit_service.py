"""
AuditService — the single point of entry for writing to audit_logs.
Called by other services; never called directly from API routers.
Every write is part of the caller's transaction.
"""
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.audit_repository import AuditRepository


class AuditService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = AuditRepository(db)

    async def log(
        self,
        *,
        project_id: UUID,
        action: str,
        entity_type: str,
        entity_id: UUID,
        actor_id: Optional[UUID] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        await self.repo.create(
            project_id=project_id,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            meta=meta,
        )
