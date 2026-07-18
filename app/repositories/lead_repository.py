"""
Lead repository.

Includes status lookup methods so LeadService does not need to reach into
a separate repository for the LeadStatus model — they are part of the
same domain boundary.

Optimistic locking
------------------
update_status_with_check() and update_manager_with_check() use a WHERE clause
that includes the *expected current value* (expected_status_id / expected_manager_id).
If another request changes the row between the service's initial fetch and this
update, the WHERE clause matches zero rows (rowcount == 0) and the method
returns None. The caller must handle None as a 409 Conflict.

This avoids lost updates without requiring application-level distributed locks.

Implementation notes
--------------------
list_by_project() intentionally uses OFFSET pagination because the UI still
requests explicit offsets. Status lookups stay in this repository while the
reference table remains part of the lead domain boundary.
"""
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, func, or_, select, true, update
from sqlalchemy.orm import aliased

from app.core.constants import LeadStatusCode
from app.models.bot import Bot
from app.models.chat import Chat
from app.models.funnel import ChatFunnelState
from app.models.lead import Lead
from app.models.lead import LeadTag
from app.models.lead_status import LeadStatus
from app.models.partner import LeadSubmission, PartnerIntegration
from app.models.tracking import TrackingLink
from app.models.user import User
from app.repositories.base import BaseRepository


DEFAULT_EXCLUDED_STATUS_CODES = frozenset({LeadStatusCode.LOST, "rejected"})
SUCCESSFUL_SUBMISSION_STATUSES = frozenset({"completed", "success"})


class LeadRepository(BaseRepository[Lead]):
    model = Lead

    # ── Single-object lookups ──────────────────────────────────────────────────

    async def get_active(self, lead_id: UUID, project_id: UUID) -> Optional[Lead]:
        """Fetch a single non-deleted lead scoped to the given project."""
        result = await self.db.execute(
            select(Lead).where(
                Lead.id == lead_id,
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                Lead.is_trash.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_chat(self, chat_id: UUID, project_id: UUID) -> Optional[Lead]:
        """Fetch a lead by chat, scoped to a project."""
        result = await self.db.execute(
            select(Lead).where(
                Lead.chat_id == chat_id,
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                Lead.is_trash.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def get_existing_by_chat(self, chat_id: UUID, project_id: UUID) -> Optional[Lead]:
        """Fetch a non-deleted lead by chat, including trash rows."""
        result = await self.db.execute(
            select(Lead).where(
                Lead.chat_id == chat_id,
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def get_any_by_chat(self, chat_id: UUID, project_id: UUID) -> Optional[Lead]:
        """Fetch a lead by chat, including soft-deleted rows."""
        result = await self.db.execute(
            select(Lead).where(
                Lead.chat_id == chat_id,
                Lead.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()

    # ── List / count ───────────────────────────────────────────────────────────

    async def list_by_project(
        self,
        project_id: UUID,
        status_id: Optional[UUID] = None,
        status_code: Optional[str] = None,
        manager_id: Optional[UUID] = None,
        bot_ids: list[UUID] | None = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        tag_ids: list[UUID] | None = None,
        search: Optional[str] = None,
        q: Optional[str] = None,
        is_trash: bool = False,
        partner_id: Optional[UUID] = None,
        age_from: Optional[int] = None,
        age_to: Optional[int] = None,
        country: Optional[str] = None,
        submission_state: Optional[str] = None,
        funnel_completed: bool = False,
        current_step_id: Optional[UUID] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Lead]:
        lifecycle_at = self._lead_lifecycle_at()
        stmt = (
            select(Lead)
            .select_from(Lead)
            .join(Chat, Chat.id == Lead.chat_id)
            .join(LeadStatus, LeadStatus.id == Lead.status_id)
            .where(
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                Lead.is_trash.is_(is_trash),
                Chat.reset_at.is_(None),
            )
        )
        if status_id is not None:
            stmt = stmt.where(Lead.status_id == status_id)
        if status_code is not None:
            stmt = stmt.where(LeadStatus.code == status_code)
        if (
            status_id is None
            and status_code is None
            and not is_trash
            and submission_state != "submitted"
        ):
            stmt = stmt.where(~LeadStatus.code.in_(DEFAULT_EXCLUDED_STATUS_CODES))
        if manager_id is not None:
            stmt = stmt.where(Lead.manager_id == manager_id)
        if bot_ids:
            stmt = stmt.where(Chat.bot_id.in_(bot_ids))
        if date_from is not None:
            stmt = stmt.where(
                lifecycle_at
                >= datetime.combine(date_from, time.min, tzinfo=timezone.utc)
            )
        if date_to is not None:
            stmt = stmt.where(
                lifecycle_at
                < datetime.combine(
                    date_to + timedelta(days=1),
                    time.min,
                    tzinfo=timezone.utc,
                )
            )
        if tag_ids:
            stmt = stmt.join(LeadTag, LeadTag.lead_id == Lead.id).where(
                LeadTag.tag_id.in_(tag_ids)
            )
        if partner_id is not None:
            stmt = stmt.join(LeadSubmission, LeadSubmission.lead_id == Lead.id).where(
                LeadSubmission.partner_integration_id == partner_id
            )
        stmt = self._apply_submission_state(
            stmt,
            submission_state,
            partner_id=partner_id if submission_state == "submitted" else None,
        )
        stmt = self._apply_funnel_completed(stmt, funnel_completed)
        stmt = self._apply_current_step(stmt, current_step_id)
        if age_from is not None:
            stmt = stmt.where(Lead.age >= age_from)
        if age_to is not None:
            stmt = stmt.where(Lead.age <= age_to)
        if country:
            stmt = stmt.where(
                func.lower(func.coalesce(Lead.country, "")) == country.strip().lower()
            )
        effective_search = q if q is not None else search
        if effective_search:
            needle = f"%{effective_search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(func.coalesce(Lead.name, "")).like(needle),
                    func.lower(func.coalesce(Lead.username, "")).like(needle),
                    func.lower(func.coalesce(Lead.phone, "")).like(needle),
                    func.lower(func.coalesce(Chat.contact_name, "")).like(needle),
                    func.lower(func.coalesce(Chat.external_chat_id, "")).like(needle),
                    func.lower(func.coalesce(Chat.external_user_id, "")).like(needle),
                )
            )

        stmt = (
            stmt.order_by(Lead.updated_at.desc(), Lead.created_at.desc())
            .distinct()
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_by_project(
        self,
        project_id: UUID,
        status_id: Optional[UUID] = None,
        status_code: Optional[str] = None,
        manager_id: Optional[UUID] = None,
        bot_ids: list[UUID] | None = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        tag_ids: list[UUID] | None = None,
        search: Optional[str] = None,
        q: Optional[str] = None,
        is_trash: bool = False,
        partner_id: Optional[UUID] = None,
        age_from: Optional[int] = None,
        age_to: Optional[int] = None,
        country: Optional[str] = None,
        submission_state: Optional[str] = None,
        funnel_completed: bool = False,
        current_step_id: Optional[UUID] = None,
    ) -> int:
        lifecycle_at = self._lead_lifecycle_at()
        stmt = (
            select(func.count(Lead.id.distinct()))
            .select_from(Lead)
            .join(Chat, Chat.id == Lead.chat_id)
            .join(LeadStatus, LeadStatus.id == Lead.status_id)
            .where(
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                Lead.is_trash.is_(is_trash),
                Chat.reset_at.is_(None),
            )
        )
        if status_id is not None:
            stmt = stmt.where(Lead.status_id == status_id)
        if status_code is not None:
            stmt = stmt.where(LeadStatus.code == status_code)
        if (
            status_id is None
            and status_code is None
            and not is_trash
            and submission_state != "submitted"
        ):
            stmt = stmt.where(~LeadStatus.code.in_(DEFAULT_EXCLUDED_STATUS_CODES))
        if manager_id is not None:
            stmt = stmt.where(Lead.manager_id == manager_id)
        if bot_ids:
            stmt = stmt.where(Chat.bot_id.in_(bot_ids))
        if date_from is not None:
            stmt = stmt.where(
                lifecycle_at
                >= datetime.combine(date_from, time.min, tzinfo=timezone.utc)
            )
        if date_to is not None:
            stmt = stmt.where(
                lifecycle_at
                < datetime.combine(
                    date_to + timedelta(days=1),
                    time.min,
                    tzinfo=timezone.utc,
                )
            )
        if tag_ids:
            stmt = stmt.join(LeadTag, LeadTag.lead_id == Lead.id).where(
                LeadTag.tag_id.in_(tag_ids)
            )
        if partner_id is not None:
            stmt = stmt.join(LeadSubmission, LeadSubmission.lead_id == Lead.id).where(
                LeadSubmission.partner_integration_id == partner_id
            )
        stmt = self._apply_submission_state(
            stmt,
            submission_state,
            partner_id=partner_id if submission_state == "submitted" else None,
        )
        stmt = self._apply_funnel_completed(stmt, funnel_completed)
        stmt = self._apply_current_step(stmt, current_step_id)
        if age_from is not None:
            stmt = stmt.where(Lead.age >= age_from)
        if age_to is not None:
            stmt = stmt.where(Lead.age <= age_to)
        if country:
            stmt = stmt.where(
                func.lower(func.coalesce(Lead.country, "")) == country.strip().lower()
            )
        effective_search = q if q is not None else search
        if effective_search:
            needle = f"%{effective_search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(func.coalesce(Lead.name, "")).like(needle),
                    func.lower(func.coalesce(Lead.username, "")).like(needle),
                    func.lower(func.coalesce(Lead.phone, "")).like(needle),
                    func.lower(func.coalesce(Chat.contact_name, "")).like(needle),
                    func.lower(func.coalesce(Chat.external_chat_id, "")).like(needle),
                    func.lower(func.coalesce(Chat.external_user_id, "")).like(needle),
                )
            )

        result = await self.db.execute(stmt)
        return result.scalar_one()

    @staticmethod
    def _apply_submission_state(
        stmt,
        submission_state: Optional[str],
        *,
        partner_id: Optional[UUID] = None,
    ):
        if submission_state not in {"active", "submitted"}:
            return stmt
        submission = aliased(LeadSubmission)
        successful_submission = (
            select(submission.id)
            .where(
                submission.lead_id == Lead.id,
                func.lower(submission.status).in_(SUCCESSFUL_SUBMISSION_STATUSES),
            )
        )
        if partner_id is not None:
            successful_submission = successful_submission.where(
                submission.partner_integration_id == partner_id
            )
        successful_submission = successful_submission.exists()
        return stmt.where(
            successful_submission if submission_state == "submitted" else ~successful_submission
        )

    @staticmethod
    def _apply_funnel_completed(stmt, funnel_completed: bool):
        if not funnel_completed:
            return stmt
        return stmt.where(
            select(ChatFunnelState.id)
            .where(
                ChatFunnelState.chat_id == Chat.id,
                ChatFunnelState.completed_at.is_not(None),
            )
            .exists()
        )

    @staticmethod
    def _apply_current_step(stmt, current_step_id: Optional[UUID]):
        if current_step_id is None:
            return stmt
        return stmt.where(
            select(ChatFunnelState.id)
            .where(
                ChatFunnelState.chat_id == Chat.id,
                ChatFunnelState.current_step_id == current_step_id,
                ChatFunnelState.completed_at.is_(None),
            )
            .exists()
        )

    async def get_lead_context(self, lead_id: UUID) -> dict:
        latest_successful_submission = (
            select(
                LeadSubmission.submitted_at.label("submitted_at"),
                LeadSubmission.status.label("submission_status"),
                LeadSubmission.partner_integration_id.label("partner_integration_id"),
            )
            .where(
                LeadSubmission.lead_id == Lead.id,
                func.lower(LeadSubmission.status).in_(SUCCESSFUL_SUBMISSION_STATUSES),
            )
            .order_by(
                LeadSubmission.completed_at.desc().nullslast(),
                LeadSubmission.submitted_at.desc(),
            )
            .limit(1)
            .correlate(Lead)
            .lateral("latest_successful_submission")
        )
        result = await self.db.execute(
            select(
                Chat.bot_id,
                Chat.tracking_link_id,
                Chat.contact_name,
                Chat.external_chat_id,
                Chat.external_user_id,
                Chat.current_cycle_started_at,
                Bot.name.label("bot_name"),
                Bot.bot_username,
                TrackingLink.code.label("tracking_code"),
                TrackingLink.ref_code.label("tracking_ref_code"),
                TrackingLink.title.label("tracking_title"),
                User.name.label("manager_name"),
                LeadStatus.code.label("status_code"),
                LeadStatus.name.label("status_name"),
                latest_successful_submission.c.submitted_at,
                latest_successful_submission.c.submission_status,
                PartnerIntegration.name.label("submission_partner_name"),
            )
            .select_from(Lead)
            .join(Chat, Chat.id == Lead.chat_id)
            .join(LeadStatus, LeadStatus.id == Lead.status_id)
            .outerjoin(Bot, Bot.id == Chat.bot_id)
            .outerjoin(TrackingLink, TrackingLink.id == Chat.tracking_link_id)
            .outerjoin(User, User.id == Lead.manager_id)
            .outerjoin(latest_successful_submission, true())
            .outerjoin(
                PartnerIntegration,
                PartnerIntegration.id
                == latest_successful_submission.c.partner_integration_id,
            )
            .where(Lead.id == lead_id)
        )
        row = result.mappings().first()
        return dict(row) if row is not None else {}

    async def aggregate_leads_by_status_for_date(
        self,
        project_id: UUID,
        target_date: date,
    ) -> dict[str, int]:
        start_at = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
        end_at = start_at + timedelta(days=1)

        result = await self.db.execute(
            select(LeadStatus.code, func.count(Lead.id))
            .join(LeadStatus, Lead.status_id == LeadStatus.id)
            .where(
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                Lead.created_at >= start_at,
                Lead.created_at < end_at,
            )
            .group_by(LeadStatus.code)
        )
        return {code: count for code, count in result.all()}

    # ── Optimistic-locking updates ─────────────────────────────────────────────

    async def update_status_with_check(
        self,
        lead_id: UUID,
        expected_status_id: UUID,
        new_status_id: UUID,
    ) -> Optional[Lead]:
        """
        Update lead.status_id only if the current status_id matches
        expected_status_id (optimistic locking).

        Returns the refreshed Lead on success, or None if the row was not
        found or the status was concurrently changed by another request.
        Caller should raise 409 Conflict on None.
        """
        result = await self.db.execute(
            update(Lead)
            .where(
                Lead.id == lead_id,
                Lead.status_id == expected_status_id,
                Lead.is_deleted.is_(False),
            )
            .values(status_id=new_status_id, updated_at=func.now())
        )
        if result.rowcount == 0:
            return None
        return await self.get_by_id(lead_id)

    async def update_manager_with_check(
        self,
        lead_id: UUID,
        expected_manager_id: Optional[UUID],
        new_manager_id: Optional[UUID],
    ) -> Optional[Lead]:
        """
        Update lead.manager_id only if the current manager_id matches
        expected_manager_id (optimistic locking).

        Handles None on both sides (unassigned → assigned, assigned → unassigned,
        assigned → reassigned).

        Returns the refreshed Lead on success, or None if the row was not
        found or the manager was concurrently changed by another request.
        Caller should raise 409 Conflict on None.
        """
        if expected_manager_id is None:
            manager_check = Lead.manager_id.is_(None)
        else:
            manager_check = Lead.manager_id == expected_manager_id

        result = await self.db.execute(
            update(Lead)
            .where(
                Lead.id == lead_id,
                manager_check,
                Lead.is_deleted.is_(False),
            )
            .values(manager_id=new_manager_id, updated_at=func.now())
        )
        if result.rowcount == 0:
            return None
        return await self.get_by_id(lead_id)

    async def update_contact(
        self,
        lead_id: UUID,
        project_id: UUID,
        **values,
    ) -> Optional[Lead]:
        result = await self.db.execute(
            update(Lead)
            .where(
                Lead.id == lead_id,
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
            )
            .values(**values, updated_at=func.now())
        )
        if result.rowcount == 0:
            return None
        return await self.get_active(lead_id, project_id)

    async def set_trash(
        self,
        lead_id: UUID,
        project_id: UUID,
        *,
        is_trash: bool,
    ) -> Optional[Lead]:
        result = await self.db.execute(
            update(Lead)
            .where(
                Lead.id == lead_id,
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
            )
            .values(is_trash=is_trash, updated_at=func.now())
        )
        if result.rowcount == 0:
            return None
        return await self.get_existing_by_id(lead_id, project_id)

    async def get_existing_by_id(self, lead_id: UUID, project_id: UUID) -> Optional[Lead]:
        result = await self.db.execute(
            select(Lead).where(
                Lead.id == lead_id,
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def mark_deleted_for_chat(
        self,
        chat_id: UUID,
        project_id: UUID,
    ) -> Optional[Lead]:
        result = await self.db.execute(
            update(Lead)
            .where(
                Lead.chat_id == chat_id,
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
            )
            .values(
                is_deleted=True,
                is_trash=False,
                manager_id=None,
                updated_at=func.now(),
            )
        )
        if result.rowcount == 0:
            return None
        return await self.get_any_by_chat(chat_id, project_id)

    async def set_status_by_code(
        self,
        lead_id: UUID,
        project_id: UUID,
        status_code: str,
        *,
        reset_contact: bool = False,
        reset_manager: bool = False,
    ) -> Optional[Lead]:
        lead_status = await self.get_status_by_code(status_code)
        if lead_status is None:
            return None

        values: dict = {"status_id": lead_status.id, "updated_at": func.now()}
        if reset_contact:
            values.update(
                {
                    "name": None,
                    "phone": None,
                    "username": None,
                    "age": None,
                    "country": None,
                    "call_time_text": None,
                    "preferred_call_time": None,
                    "has_card": None,
                    "custom_fields": {},
                }
            )
        if reset_manager:
            values["manager_id"] = None

        result = await self.db.execute(
            update(Lead)
            .where(
                Lead.id == lead_id,
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
            )
            .values(**values)
        )
        if result.rowcount == 0:
            return None
        return await self.get_active(lead_id, project_id)

    async def reset_existing_for_new_cycle(
        self,
        lead_id: UUID,
        project_id: UUID,
        *,
        username: Optional[str],
        name: Optional[str] = None,
        custom_fields: Optional[dict] = None,
    ) -> Optional[Lead]:
        new_status = await self.get_status_by_code("new")
        if new_status is None:
            return None

        await self.clear_tags(lead_id)
        result = await self.db.execute(
            update(Lead)
            .where(
                Lead.id == lead_id,
                Lead.project_id == project_id,
            )
            .values(
                status_id=new_status.id,
                is_deleted=False,
                is_trash=False,
                manager_id=None,
                name=name,
                phone=None,
                username=username,
                age=None,
                country=None,
                call_time_text=None,
                preferred_call_time=None,
                has_card=None,
                custom_fields=custom_fields or {},
                updated_at=func.now(),
            )
        )
        if result.rowcount == 0:
            return None
        return await self.get_active(lead_id, project_id)

    async def clear_tags(self, lead_id: UUID) -> None:
        await self.db.execute(delete(LeadTag).where(LeadTag.lead_id == lead_id))

    # ── LeadStatus lookups (same domain, no separate repository needed) ────────

    @staticmethod
    def _lead_lifecycle_at():
        return func.coalesce(Chat.current_cycle_started_at, Lead.created_at)

    async def get_status(self, status_id: UUID) -> Optional[LeadStatus]:
        """Fetch a LeadStatus row by PK."""
        result = await self.db.execute(
            select(LeadStatus).where(LeadStatus.id == status_id)
        )
        return result.scalar_one_or_none()

    async def get_status_by_code(self, code: str) -> Optional[LeadStatus]:
        """Fetch a LeadStatus row by its unique code (e.g. 'new', 'in_progress')."""
        result = await self.db.execute(
            select(LeadStatus).where(LeadStatus.code == code)
        )
        return result.scalar_one_or_none()

    async def list_statuses(self) -> list[LeadStatus]:
        """All statuses ordered by sort_order — for seeding and admin UI."""
        result = await self.db.execute(
            select(LeadStatus).order_by(LeadStatus.sort_order.asc())
        )
        return list(result.scalars().all())

    async def next_status_sort_order(self) -> int:
        result = await self.db.execute(
            select(func.coalesce(func.max(LeadStatus.sort_order), 0) + 1)
        )
        return result.scalar_one()

    async def create_status(
        self,
        *,
        code: str,
        name: str,
        sort_order: int,
        is_final: bool,
    ) -> LeadStatus:
        status = LeadStatus(
            code=code,
            name=name,
            sort_order=sort_order,
            is_final=is_final,
        )
        self.db.add(status)
        await self.db.flush()
        await self.db.refresh(status)
        return status

    async def update_status(
        self,
        status_id: UUID,
        **values,
    ) -> Optional[LeadStatus]:
        result = await self.db.execute(
            update(LeadStatus)
            .where(LeadStatus.id == status_id)
            .values(**values)
        )
        if result.rowcount == 0:
            return None
        return await self.get_status(status_id)

    async def count_leads_by_status(self, status_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count(Lead.id)).where(Lead.status_id == status_id)
        )
        return result.scalar_one()

    async def delete_status(self, status_id: UUID) -> bool:
        result = await self.db.execute(
            delete(LeadStatus).where(LeadStatus.id == status_id)
        )
        return result.rowcount > 0
