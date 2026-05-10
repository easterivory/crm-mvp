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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AuditAction, EntityType, LeadStatusCode

logger = logging.getLogger(__name__)
from app.repositories.chat_repository import ChatRepository
from app.repositories.lead_repository import LeadRepository
from app.schemas.lead import LeadCreate, LeadOut, LeadStatusCreate, LeadStatusOut, LeadUpdate
from app.services.audit_service import AuditService


class LeadService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.lead_repo = LeadRepository(db)
        self.chat_repo = ChatRepository(db)
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

    # ── CRUD ──────────────────────────────────────────────────────────────────

    async def create_lead(
        self,
        data: LeadCreate,
        project_id: UUID,
        actor_id: Optional[UUID],
    ) -> LeadOut:
        if data.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="project_id in body must match authenticated project",
            )

        chat = await self.chat_repo.get_active(data.chat_id, project_id)
        if chat is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found",
            )

        existing = await self.lead_repo.get_any_by_chat(data.chat_id, project_id)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Chat already has a lead",
            )

        new_status = await self.lead_repo.get_status_by_code(LeadStatusCode.NEW)
        if new_status is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Default lead status is missing from reference table",
            )

        try:
            async with self.db.begin_nested():
                lead = await self.lead_repo.create(
                    project_id=project_id,
                    chat_id=data.chat_id,
                    status_id=new_status.id,
                )
        except IntegrityError:
            existing = await self.lead_repo.get_any_by_chat(data.chat_id, project_id)
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Chat already has a lead",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not create lead",
            )

        await self.audit.log(
            project_id=project_id,
            action=AuditAction.LEAD_CREATED,
            entity_type=EntityType.LEAD,
            entity_id=lead.id,
            actor_id=actor_id,
            meta={"source": "manual"},
        )

        return LeadOut.model_validate(lead)

    async def get_lead(self, lead_id: UUID, project_id: UUID) -> LeadOut:
        lead = await self.lead_repo.get_active(lead_id, project_id)
        if lead is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found",
            )
        return LeadOut.model_validate(lead)

    async def get_lead_by_chat(self, chat_id: UUID, project_id: UUID) -> LeadOut:
        lead = await self.lead_repo.get_by_chat(chat_id, project_id)
        if lead is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found for this chat",
            )
        return LeadOut.model_validate(lead)

    async def list_statuses(self) -> list[LeadStatusOut]:
        statuses = await self.lead_repo.list_statuses()
        return [LeadStatusOut.model_validate(item) for item in statuses]

    async def create_status(self, data: LeadStatusCreate) -> LeadStatusOut:
        code = self._normalize_status_code(data.code)
        name = self._normalize_status_name(data.name)

        existing = await self.lead_repo.get_status_by_code(code)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Lead status with this code already exists",
            )

        try:
            async with self.db.begin_nested():
                sort_order = await self.lead_repo.next_status_sort_order()
                lead_status = await self.lead_repo.create_status(
                    code=code,
                    name=name,
                    sort_order=sort_order,
                    is_final=data.is_final,
                )
        except IntegrityError:
            existing = await self.lead_repo.get_status_by_code(code)
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Lead status with this code already exists",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not create lead status",
            )

        return LeadStatusOut.model_validate(lead_status)

    async def list_leads(
        self,
        project_id: UUID,
        status_id: Optional[UUID],
        manager_id: Optional[UUID],
        limit: int,
        offset: int,
    ) -> tuple[list[LeadOut], int]:
        leads = await self.lead_repo.list_by_project(
            project_id=project_id,
            status_id=status_id,
            manager_id=manager_id,
            limit=limit,
            offset=offset,
        )
        total = await self.lead_repo.count_by_project(
            project_id=project_id,
            status_id=status_id,
            manager_id=manager_id,
        )
        return [LeadOut.model_validate(lead) for lead in leads], total

    async def update_contact(
        self,
        lead_id: UUID,
        project_id: UUID,
        data: LeadUpdate,
        actor_id: UUID,
    ) -> LeadOut:
        values = data.model_dump(exclude_unset=True)
        if "phone" in values:
            values["phone"] = self._normalize_optional(values["phone"])
        if "username" in values:
            values["username"] = self._normalize_optional(values["username"])

        if not values:
            return await self.get_lead(lead_id, project_id)

        lead = await self.lead_repo.update_contact(lead_id, project_id, **values)
        if lead is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found",
            )
        return LeadOut.model_validate(lead)

    @staticmethod
    def _normalize_optional(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _normalize_status_code(code: str) -> str:
        normalized = code.strip().lower()
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Status code must not be empty",
            )
        return normalized

    @staticmethod
    def _normalize_status_name(name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Status name must not be empty",
            )
        return normalized
