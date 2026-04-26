"""
AssignmentService — assigns or removes a manager from a lead.

Design decisions
----------------
- manager_id lives directly on leads (no separate assignments table).
  The full history is preserved in audit_logs.
- Assigning the same manager twice is a no-op (idempotent, no write).
- A manager must belong to the same project as the lead. Assigning a user
  from a different project raises 403.
- Passing manager_id=None explicitly unassigns the current manager.

Audit log entries
-----------------
  lead.manager_assigned — manager_id is set to a non-null value
  lead.manager_removed  — manager_id is set to None

  meta = {
      "from_manager_id": "<uuid> | null",
      "to_manager_id":   "<uuid> | null",
  }

Transaction
-----------
UPDATE lead + INSERT audit_log share the caller's DB session.
The single commit is issued by get_db() at the end of the request.
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AuditAction, EntityType

logger = logging.getLogger(__name__)
from app.repositories.lead_repository import LeadRepository
from app.repositories.user_repository import UserRepository
from app.schemas.lead import LeadOut
from app.services.audit_service import AuditService


class AssignmentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.lead_repo = LeadRepository(db)
        self.user_repo = UserRepository(db)
        self.audit = AuditService(db)

    async def assign_manager(
        self,
        lead_id: UUID,
        project_id: UUID,
        manager_id: Optional[UUID],
        actor_id: UUID,
    ) -> LeadOut:
        """
        Assigns (or unassigns) a manager for the given lead.

        Steps:
        1. Fetch lead — 404 if not found or soft-deleted.
        2. Idempotency: return early if manager_id == lead.manager_id.
        3. Validate: if manager_id is not None, the user must exist and
           belong to the same project — 403 otherwise.
        4. Update lead.manager_id.
        5. Write audit log.
        6. Return updated LeadOut.
        """
        # ── Fetch lead ────────────────────────────────────────────────────────
        lead = await self.lead_repo.get_active(lead_id, project_id)
        if lead is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found",
            )

        old_manager_id = lead.manager_id

        # ── Idempotency ───────────────────────────────────────────────────────
        if manager_id == old_manager_id:
            return LeadOut.model_validate(lead)

        # ── Validate target manager ───────────────────────────────────────────
        if manager_id is not None:
            manager = await self.user_repo.get_active_in_project(manager_id, project_id)
            if manager is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "Cannot assign: user does not exist or does not "
                        "belong to this project"
                    ),
                )

        # ── Apply update with optimistic lock ────────────────────────────────
        # WHERE includes the expected current manager_id. If another request
        # changed the assignment concurrently, rowcount == 0 → None → 409.
        updated = await self.lead_repo.update_manager_with_check(
            lead_id,
            expected_manager_id=old_manager_id,
            new_manager_id=manager_id,
        )
        if updated is None:
            logger.warning(
                "Optimistic lock failed on manager assignment: lead_id=%s "
                "expected_manager_id=%s new_manager_id=%s actor_id=%s",
                lead_id, old_manager_id, manager_id, actor_id,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Lead manager was changed by another request. "
                    "Reload the lead and retry."
                ),
            )

        # ── Determine audit action ────────────────────────────────────────────
        action = (
            AuditAction.LEAD_MANAGER_ASSIGNED
            if manager_id is not None
            else AuditAction.LEAD_MANAGER_REMOVED
        )

        # ── Write audit log ───────────────────────────────────────────────────
        await self.audit.log(
            project_id=project_id,
            action=action,
            entity_type=EntityType.LEAD,
            entity_id=lead_id,
            actor_id=actor_id,
            meta={
                "from_manager_id": str(old_manager_id) if old_manager_id else None,
                "to_manager_id": str(manager_id) if manager_id else None,
            },
        )

        return LeadOut.model_validate(updated)
