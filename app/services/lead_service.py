"""
LeadService — lead lifecycle: status transitions and contact info updates.

Status transition rules
-----------------------
- Manual status changes are allowed from any current status, including
  terminal/final statuses, so operators can correct lead cards after a funnel.
- The target status must exist in the lead_statuses reference table.
- There is no fixed transition graph for manual status changes.

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
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AuditAction, ChatEventType, EntityType, LeadStatusCode

logger = logging.getLogger(__name__)
from app.repositories.chat_repository import ChatRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.tag_repository import TagRepository
from app.schemas.lead import (
    LeadCreate,
    LeadOut,
    LeadTagOut,
    LeadStatusAdminUpdate,
    LeadStatusCreate,
    LeadStatusOut,
    LeadUpdate,
)
from app.services.audit_service import AuditService
from app.services.chat_audit_service import ChatAuditService
from app.services.lead_scoring_service import LeadScoringService


class LeadService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.lead_repo = LeadRepository(db)
        self.chat_repo = ChatRepository(db)
        self.tag_repo = TagRepository(db)
        self.audit = AuditService(db)
        self.chat_audit = ChatAuditService(db)
        self.scoring = LeadScoringService(db)

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
        2. Target status must exist in lead_statuses.
        3. If target == current, returns early (idempotent, no write).
        4. Writes audit log entry with before/after status codes.
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
            return await self._lead_out(lead)

        # ── Fetch current status ──────────────────────────────────────────────
        current_status = await self.lead_repo.get_status(lead.status_id)
        if current_status is None:
            # Data integrity issue — should not happen in a well-seeded DB
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Current lead status is missing from reference table",
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
                "from_status_is_final": current_status.is_final,
                "to_status_id": str(new_status.id),
                "to_status_code": new_status.code,
                "to_status_is_final": new_status.is_final,
                "manual_override": current_status.is_final,
            },
        )

        return await self._lead_out(updated)

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

        return await self._lead_out(lead)

    async def get_lead(self, lead_id: UUID, project_id: UUID) -> LeadOut:
        lead = await self.lead_repo.get_active(lead_id, project_id)
        if lead is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found",
            )
        return await self._lead_out(lead)

    async def get_lead_by_chat(self, chat_id: UUID, project_id: UUID) -> LeadOut:
        lead = await self.lead_repo.get_by_chat(chat_id, project_id)
        if lead is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found for this chat",
            )
        return await self._lead_out(lead)

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

    async def update_status(
        self,
        status_id: UUID,
        data: LeadStatusAdminUpdate,
    ) -> LeadStatusOut:
        lead_status = await self.lead_repo.get_status(status_id)
        if lead_status is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead status not found",
            )

        values = {
            key: value
            for key, value in data.model_dump(exclude_unset=True).items()
            if value is not None
        }
        if "name" in values and values["name"] is not None:
            values["name"] = self._normalize_status_name(values["name"])

        if not values:
            return LeadStatusOut.model_validate(lead_status)

        try:
            updated = await self.lead_repo.update_status(status_id, **values)
        except IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Could not update lead status",
            )

        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead status not found",
            )
        return LeadStatusOut.model_validate(updated)

    async def delete_status(self, status_id: UUID) -> None:
        lead_status = await self.lead_repo.get_status(status_id)
        if lead_status is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead status not found",
            )

        if lead_status.code in {LeadStatusCode.NEW, LeadStatusCode.LOST}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Base status '{lead_status.code}' cannot be deleted",
            )

        linked_leads = await self.lead_repo.count_leads_by_status(status_id)
        if linked_leads > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Cannot delete lead status while leads are attached to it. "
                    "Move those leads to another status first."
                ),
            )

        deleted = await self.lead_repo.delete_status(status_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead status not found",
            )

    async def list_leads(
        self,
        project_id: UUID,
        status_id: Optional[UUID],
        status_code: Optional[str],
        manager_id: Optional[UUID],
        bot_ids: list[UUID],
        date_from: Optional[date],
        date_to: Optional[date],
        tag_ids: list[UUID],
        search: Optional[str],
        q: Optional[str] = None,
        is_trash: bool = False,
        partner_id: Optional[UUID] = None,
        age_from: Optional[int] = None,
        age_to: Optional[int] = None,
        country: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[LeadOut], int]:
        leads = await self.lead_repo.list_by_project(
            project_id=project_id,
            status_id=status_id,
            status_code=status_code,
            manager_id=manager_id,
            bot_ids=bot_ids,
            date_from=date_from,
            date_to=date_to,
            tag_ids=tag_ids,
            search=search,
            q=q,
            is_trash=is_trash,
            partner_id=partner_id,
            age_from=age_from,
            age_to=age_to,
            country=country,
            limit=limit,
            offset=offset,
        )
        total = await self.lead_repo.count_by_project(
            project_id=project_id,
            status_id=status_id,
            status_code=status_code,
            manager_id=manager_id,
            bot_ids=bot_ids,
            date_from=date_from,
            date_to=date_to,
            tag_ids=tag_ids,
            search=search,
            q=q,
            is_trash=is_trash,
            partner_id=partner_id,
            age_from=age_from,
            age_to=age_to,
            country=country,
        )
        return [await self._lead_out(lead) for lead in leads], total

    async def trash_lead(
        self,
        lead_id: UUID,
        project_id: UUID,
        actor_id: UUID,
    ) -> LeadOut:
        lead = await self.lead_repo.get_existing_by_id(lead_id, project_id)
        if lead is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found",
            )
        if lead.is_trash:
            return await self._lead_out(lead)

        updated = await self.lead_repo.set_trash(lead_id, project_id, is_trash=True)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found",
            )
        await self.audit.log(
            project_id=project_id,
            action=AuditAction.LEAD_TRASHED,
            entity_type=EntityType.LEAD,
            entity_id=lead_id,
            actor_id=actor_id,
            meta={"from_is_trash": False, "to_is_trash": True},
        )
        return await self._lead_out(updated)

    async def restore_lead(
        self,
        lead_id: UUID,
        project_id: UUID,
        actor_id: UUID,
    ) -> LeadOut:
        lead = await self.lead_repo.get_existing_by_id(lead_id, project_id)
        if lead is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found",
            )
        if not lead.is_trash:
            return await self._lead_out(lead)

        updated = await self.lead_repo.set_trash(lead_id, project_id, is_trash=False)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found",
            )
        await self.audit.log(
            project_id=project_id,
            action=AuditAction.LEAD_RESTORED,
            entity_type=EntityType.LEAD,
            entity_id=lead_id,
            actor_id=actor_id,
            meta={"from_is_trash": True, "to_is_trash": False},
        )
        return await self._lead_out(updated)

    async def submit_lead(
        self,
        lead_id: UUID,
        project_id: UUID,
        actor_id: UUID,
    ) -> LeadOut:
        lead = await self._move_to_status_code(
            lead_id=lead_id,
            project_id=project_id,
            status_code=LeadStatusCode.QUALIFIED,
            actor_id=actor_id,
            audit_action=AuditAction.LEAD_SUBMITTED,
            audit_meta={},
        )
        return await self._lead_out(lead)

    async def reject_lead(
        self,
        lead_id: UUID,
        project_id: UUID,
        actor_id: UUID,
    ) -> LeadOut:
        lead = await self._move_to_status_code(
            lead_id=lead_id,
            project_id=project_id,
            status_code=LeadStatusCode.LOST,
            actor_id=actor_id,
            audit_action=AuditAction.LEAD_REJECTED,
            audit_meta={"archive": True},
        )
        return await self._lead_out(lead)

    async def update_contact(
        self,
        lead_id: UUID,
        project_id: UUID,
        data: LeadUpdate,
        actor_id: UUID,
    ) -> LeadOut:
        lead = await self.lead_repo.get_active(lead_id, project_id)
        if lead is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found",
            )

        old_name = lead.name
        old_call_time = lead.preferred_call_time or lead.call_time_text
        values = data.model_dump(exclude_unset=True)
        requested_fields = set(values)
        for field_name in ("name", "country", "call_time_text", "preferred_call_time"):
            if field_name in values:
                values[field_name] = self._normalize_optional(values[field_name])
        if "preferred_call_time" in values and "call_time_text" not in values:
            values["call_time_text"] = values["preferred_call_time"]
        if "call_time_text" in values and "preferred_call_time" not in values:
            values["preferred_call_time"] = values["call_time_text"]
        if "phone" in values:
            values["phone"] = self._normalize_optional(values["phone"])
        if "username" in values:
            values["username"] = self._normalize_optional(values["username"])

        if not values:
            return await self._lead_out(lead)

        lead = await self.lead_repo.update_contact(lead_id, project_id, **values)
        if lead is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found",
            )

        # Recalculate lead score after contact update
        await self.scoring.update_lead_score(lead_id)
        await self._log_contact_updates(
            lead=lead,
            project_id=project_id,
            actor_id=actor_id,
            old_name=old_name,
            old_call_time=old_call_time,
            requested_fields=requested_fields,
        )

        return await self._lead_out(lead)

    async def _lead_out(self, lead) -> LeadOut:
        tags = await self.tag_repo.list_for_lead(lead.id)
        context = await self.lead_repo.get_lead_context(lead.id)
        return LeadOut.model_validate(lead).model_copy(
            update={
                "tags": [
                    LeadTagOut(id=tag.id, name=tag.name, color=tag.color)
                    for tag in tags
                ],
                **context,
            }
        )

    async def _move_to_status_code(
        self,
        *,
        lead_id: UUID,
        project_id: UUID,
        status_code: str,
        actor_id: UUID,
        audit_action: str,
        audit_meta: dict,
    ):
        lead = await self.lead_repo.get_active(lead_id, project_id)
        if lead is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found",
            )

        current_status = await self.lead_repo.get_status(lead.status_id)
        target_status = await self.lead_repo.get_status_by_code(status_code)
        if target_status is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Lead status '{status_code}' is missing",
            )

        if lead.status_id == target_status.id:
            return lead

        if (
            current_status is not None
            and current_status.is_final
            and target_status.code != LeadStatusCode.LOST
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Cannot change status: lead is in terminal status "
                    f"'{current_status.code}'."
                ),
            )

        updated = await self.lead_repo.update_status_with_check(
            lead_id,
            expected_status_id=lead.status_id,
            new_status_id=target_status.id,
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Lead status was changed by another request. Reload and retry.",
            )

        await self.audit.log(
            project_id=project_id,
            action=AuditAction.LEAD_STATUS_CHANGED,
            entity_type=EntityType.LEAD,
            entity_id=lead_id,
            actor_id=actor_id,
            meta={
                "from_status_id": str(lead.status_id),
                "from_status_code": current_status.code if current_status else None,
                "to_status_id": str(target_status.id),
                "to_status_code": target_status.code,
            },
        )
        await self.audit.log(
            project_id=project_id,
            action=audit_action,
            entity_type=EntityType.LEAD,
            entity_id=lead_id,
            actor_id=actor_id,
            meta=audit_meta,
        )
        return updated

    @staticmethod
    def _normalize_optional(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    async def _log_contact_updates(
        self,
        *,
        lead,
        project_id: UUID,
        actor_id: UUID,
        old_name: str | None,
        old_call_time: str | None,
        requested_fields: set[str],
    ) -> None:
        if "name" in requested_fields and self._changed(old_name, lead.name):
            await self.chat_audit.log_event(
                chat_id=lead.chat_id,
                project_id=project_id,
                user_id=actor_id,
                event_type=ChatEventType.LEAD_UPDATED,
                old_value=old_name,
                new_value=f"обновил ФИО лида: {lead.name or 'не указано'}",
            )

        if (
            {"preferred_call_time", "call_time_text"} & requested_fields
            and self._changed(old_call_time, lead.preferred_call_time or lead.call_time_text)
        ):
            new_call_time = lead.preferred_call_time or lead.call_time_text
            await self.chat_audit.log_event(
                chat_id=lead.chat_id,
                project_id=project_id,
                user_id=actor_id,
                event_type=ChatEventType.LEAD_UPDATED,
                old_value=old_call_time,
                new_value=f"изменил удобное время звонка на: {new_call_time or 'не указано'}",
            )

    @staticmethod
    def _changed(left: str | None, right: str | None) -> bool:
        return (left or "") != (right or "")

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
