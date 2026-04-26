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

TODO (do not implement now):
  - Cursor-based pagination instead of OFFSET for list_by_project().
    High-offset queries are slow; a cursor on (created_at, id) is O(1).
  - Heavy count optimisation: COUNT(*) on large leads tables is expensive.
    Consider caching totals in daily_stats or using pg_class.reltuples for
    the unfiltered case as an estimated count.
  - Cache lead_statuses reference table in Redis (or in-process LRU).
    The table is tiny and almost never changes — every status change currently
    issues two SELECT queries (get_status x2). An LRU with a 60-second TTL
    would eliminate the vast majority of these reads.
  - Consider a dedicated LeadStatusRepository if status management grows.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select, update

from app.models.lead import Lead
from app.models.lead_status import LeadStatus
from app.repositories.base import BaseRepository


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
            )
        )
        return result.scalar_one_or_none()

    # ── List / count ───────────────────────────────────────────────────────────

    async def list_by_project(
        self,
        project_id: UUID,
        status_id: Optional[UUID] = None,
        manager_id: Optional[UUID] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Lead]:
        stmt = select(Lead).where(
            Lead.project_id == project_id,
            Lead.is_deleted.is_(False),
        )
        if status_id is not None:
            stmt = stmt.where(Lead.status_id == status_id)
        if manager_id is not None:
            stmt = stmt.where(Lead.manager_id == manager_id)

        stmt = stmt.order_by(Lead.created_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_by_project(
        self,
        project_id: UUID,
        status_id: Optional[UUID] = None,
        manager_id: Optional[UUID] = None,
    ) -> int:
        stmt = select(func.count(Lead.id)).where(
            Lead.project_id == project_id,
            Lead.is_deleted.is_(False),
        )
        if status_id is not None:
            stmt = stmt.where(Lead.status_id == status_id)
        if manager_id is not None:
            stmt = stmt.where(Lead.manager_id == manager_id)

        result = await self.db.execute(stmt)
        return result.scalar_one()

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

    # ── LeadStatus lookups (same domain, no separate repository needed) ────────

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
