"""
LeadService — lead lifecycle: status transitions and contact info updates.

Status transition rules
-----------------------
- Transitions FROM a terminal status (is_final=True) are forbidden.
  Once a lead is 'qualified' or 'lost', its status cannot be changed.
- The target status must exist in the lead_statuses reference table.
- There is no fixed transition graph beyond the terminal-status guard;
  any non-final status can move to any other status.

Audit log
---------
Every status change writes a 'lead.status_changed' entry to audit_logs with:
  meta = {
      "from_status_id": "<uuid>",
      "from_status_code": "<code>",
      "to_status_id": "<uuid>",
      "to_status_code": "<code>",
  }

Transaction
-----------
All DB writes (UPDATE lead + INSERT audit_log) happen inside the caller's
session. The single commit is issued by get_db() at the end of the request.
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AuditAction, EntityType

logger = logging.getLogger(__name__)
from app.repositories.lead_repository import LeadRepository
from app.schemas.lead import LeadCreate, LeadOut, LeadUpdate
from app.services.audit_service import AuditService


class LeadService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.lead_repo = LeadRepository(db)
        self.audit = AuditService(db)

    # ── Status transition ──────────────────────────────────────────────────────

    async def change_status(
        self,
        lead_id: UUID,
        project_id: UUID,
        new_status_id: UUID,
        actor_id: UUID,
    ) -> LeadOut:
        """
        Changes lead.status_id with validation:

        1. Lead must exist in this project and not be soft-deleted.
        2. Current status must not be terminal (is_final=True).
        3. Target status must exist in lead_statuses.
        4. If target == current, returns early (idempotent, no write).
        5. Writes audit log entry with before/after status codes.
        """
        # ── Fetch lead ────────────────────────────────────────────────────────
        lead = await self.lead_repo.get_active(lead_id, project_id)
        if lead is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found",
            )

        # ── Idempotency: no-op if status is unchanged ─────────────────────────
        if lead.status_id == new_status_id:
            return LeadOut.model_validate(lead)

        # ── Fetch current status ──────────────────────────────────────────────
        current_status = await self.lead_repo.get_status(lead.status_id)
        if current_status is None:
            # Data integrity issue — should not happen in a well-seeded DB
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Current lead status is missing from reference table",
            )

        # ── Guard: terminal status cannot transition ───────────────────────────
        if current_status.is_final:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Cannot change status: lead is in terminal status "
                    f"'{current_status.code}'. No further transitions are allowed."
                ),
            )

        # ── Fetch target status ───────────────────────────────────────────────
        new_status = await self.lead_repo.get_status(new_status_id)
        if new_status is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Status with id '{new_status_id}' not found",
            )

        # ── Apply update with optimistic lock ────────────────────────────────
        # WHERE includes the expected current status_id. If another request
        # changed the status concurrently, rowcount == 0 → None → 409.
        updated = await self.lead_repo.update_status_with_check(
            lead_id,
            expected_status_id=lead.status_id,
            new_status_id=new_status_id,
        )
        if updated is None:
            logger.warning(
                "Optimistic lock failed on status change: lead_id=%s "
                "expected_status_id=%s new_status_id=%s actor_id=%s",
                lead_id, lead.status_id, new_status_id, actor_id,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Lead status was changed by another request. "
                    "Reload the lead and retry."
                ),
            )

        # ── Write audit log ───────────────────────────────────────────────────
        await self.audit.log(
            project_id=project_id,
            action=AuditAction.LEAD_STATUS_CHANGED,
            entity_type=EntityType.LEAD,
            entity_id=lead_id,
            actor_id=actor_id,
            meta={
                "from_status_id": str(current_status.id),
                "from_status_code": current_status.code,
                "to_status_id": str(new_status.id),
                "to_status_code": new_status.code,
            },
        )

        return LeadOut.model_validate(updated)

    # ── Stubs (Phase 3) ────────────────────────────────────────────────────────

    async def create_lead(self, data: LeadCreate, actor_id: Optional[UUID]) -> LeadOut:
        raise NotImplementedError

    async def get_lead(self, lead_id: UUID, project_id: UUID) -> LeadOut:
        raise NotImplementedError

    async def list_leads(
        self,
        project_id: UUID,
        status_id: Optional[UUID],
        manager_id: Optional[UUID],
        limit: int,
        offset: int,
    ) -> list[LeadOut]:
        raise NotImplementedError

    async def update_contact(
        self,
        lead_id: UUID,
        project_id: UUID,
        data: LeadUpdate,
        actor_id: UUID,
    ) -> LeadOut:
        raise NotImplementedError
