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

from app.core.constants import AuditAction, EntityType, RoleName

logger = logging.getLogger(__name__)
from app.repositories.lead_repository import LeadRepository
from app.repositories.chat_repository import ChatRepository
from app.repositories.tag_repository import TagRepository
from app.repositories.user_repository import UserRepository
from app.schemas.lead import LeadOut, LeadTagOut
from app.services.audit_service import AuditService
from app.services.chat_lease_service import ChatLeaseService


class AssignmentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.lead_repo = LeadRepository(db)
        self.chat_repo = ChatRepository(db)
        self.tag_repo = TagRepository(db)
        self.user_repo = UserRepository(db)
        self.audit = AuditService(db)
        self.chat_lease = ChatLeaseService(db)

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

        actor = await self.user_repo.get_by_id(actor_id)
        if actor is None or actor.is_deleted:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Actor is not active")
        if actor.role_name == RoleName.BUYER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Buyers have read-only access to leads.",
            )
        if actor.role_name == RoleName.MANAGER and manager_id != actor_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Managers can only take a dialogue for themselves.",
            )

        # ── Idempotency ───────────────────────────────────────────────────────
        if manager_id == old_manager_id:
            return await self._lead_out(lead)

        # ── Validate target manager ───────────────────────────────────────────
        if manager_id is not None:
            manager = await self.user_repo.get_active_in_project(manager_id, project_id)
            if manager is None:
                candidate = await self.user_repo.get_by_id(manager_id)
                if (
                    candidate is not None
                    and not candidate.is_deleted
                    and candidate.role_name == RoleName.SUPER_ADMIN
                ):
                    manager = candidate
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

        assignment_expires_at = await self.chat_lease.assignment_deadline(
            project_id=project_id,
            manager_id=manager_id,
        )
        assignment_updated = await self.chat_repo.set_assignment_expires_at(
            chat_id=lead.chat_id,
            project_id=project_id,
            assignment_expires_at=assignment_expires_at,
        )
        if not assignment_updated:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Chat changed while manager assignment was being updated.",
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
                "chat_id": str(lead.chat_id),
                "assignment_expires_at": (
                    assignment_expires_at.isoformat()
                    if assignment_expires_at is not None
                    else None
                ),
            },
        )

        if manager_id is not None:
            from app.services.funnel_runtime_service import FunnelRuntimeService

            await FunnelRuntimeService(self.db).pause_for_manager_assignment(
                chat_id=lead.chat_id,
                project_id=project_id,
                actor_id=actor_id,
            )

        return await self._lead_out(updated)

    async def _lead_out(self, lead) -> LeadOut:
        tags = await self.tag_repo.list_for_lead(lead.id)
        return LeadOut.model_validate(lead).model_copy(
            update={
                "tags": [LeadTagOut(id=tag.id, name=tag.name, color=tag.color) for tag in tags],
            }
        )
