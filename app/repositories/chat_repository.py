"""
Chat repository.

is_red / unanswered / unread are NOT stored — they are SQL boolean expressions
built from timestamp columns and evaluated inside the DB engine.

All three expressions are defined as @staticmethod so they can be reused
in WHERE, ORDER BY, and count queries without repeating literal SQL.

Sorting contract:  is_red DESC → unanswered DESC → last_message_at DESC NULLS LAST

TODO (do not implement now):
  - Cursor-based pagination instead of OFFSET for large result sets.
    OFFSET N forces the DB to scan and discard N rows on every request.
    A cursor on (is_red, unanswered, last_message_at, id) is significantly
    faster at high page numbers.
  - Expression indexes for the three computed flags:
      is_red:      CREATE INDEX ON chats (project_id, last_user_message_at)
                   WHERE last_user_message_at IS NOT NULL
                     AND last_manager_reply_at IS NULL;
                   (partial index; covers the unanswered sub-condition)
      unanswered:  CREATE INDEX ON chats (project_id, last_user_message_at)
                   WHERE last_user_message_at > last_manager_reply_at
                      OR last_manager_reply_at IS NULL;
      unread:      CREATE INDEX ON chats (project_id, last_message_at)
                   WHERE last_message_at > last_read_at
                      OR last_read_at IS NULL;
    These partial indexes let the DB skip full-table evaluation of timestamp
    comparisons when filters are active.
  - count() optimisation: for very large tables, an exact COUNT is expensive.
    Consider returning an estimated count (pg_class.reltuples) for the
    unfiltered case, or caching the total in daily_stats.
"""
from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, String, case, func, or_, select, update

from app.core.constants import SenderType
from app.models.chat import Chat
from app.models.funnel import ChatFunnelState
from app.models.lead import Lead, LeadTag
from app.models.lead_status import LeadStatus
from app.models.message import Message
from app.models.tracking import TrackingLink
from app.repositories.base import BaseRepository


class ChatRepository(BaseRepository[Chat]):
    model = Chat

    # ── SQL expressions ────────────────────────────────────────────────────────

    @staticmethod
    def _unanswered_expr() -> ColumnElement:
        """
        True when the user sent at least one message AND the manager has not
        replied after the last user message.
        """
        return (Chat.last_user_message_at.isnot(None)) & (
            Chat.last_manager_reply_at.is_(None)
            | (Chat.last_user_message_at > Chat.last_manager_reply_at)
        )

    @staticmethod
    def _is_red_expr(sla_threshold_minutes: int) -> ColumnElement:
        """
        True when the chat is unanswered AND the last user message is older
        than the project SLA threshold.

        Uses func.make_interval(..., mins, ...) instead of a raw SQL text() so the
        threshold value is always a bound parameter — no SQL injection risk,
        no string formatting.
        """
        return ChatRepository._unanswered_expr() & (
            (func.now() - Chat.last_user_message_at)
            > func.make_interval(0, 0, 0, 0, 0, sla_threshold_minutes, 0)
        )

    @staticmethod
    def _unread_expr() -> ColumnElement:
        """
        True when the chat has at least one message (last_message_at IS NOT NULL)
        that arrived after the manager last opened the chat (or the manager
        has never opened it, i.e. last_read_at IS NULL).
        """
        return (Chat.last_message_at.isnot(None)) & (
            Chat.last_read_at.is_(None)
            | (Chat.last_message_at > Chat.last_read_at)
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _base_select(
        self,
        project_id: UUID,
        bot_id: Optional[UUID] = None,
        bot_ids: Sequence[UUID] | None = None,
    ):
        stmt = select(Chat).where(
            Chat.project_id == project_id,
            Chat.is_deleted.is_(False),
            Chat.reset_at.is_(None),
        )
        if bot_id is not None:
            stmt = stmt.where(Chat.bot_id == bot_id)
        if bot_ids:
            stmt = stmt.where(Chat.bot_id.in_(bot_ids))
        return stmt

    def _apply_filters(
        self,
        stmt,
        *,
        only_unread: bool,
        only_unanswered: bool,
        only_red: bool,
        sla_threshold_minutes: int,
        manager_id: Optional[UUID],
        assigned_user_id: Optional[UUID],
        unassigned: bool,
        search_query: Optional[str],
        tracking_link_id: Optional[UUID],
        date_from: Optional[datetime],
        date_to: Optional[datetime],
        tag_ids: Sequence[UUID],
        tag_mode: str,
        lead_statuses: Sequence[str],
        funnel_state: Optional[str],
    ):
        effective_manager_id = assigned_user_id or manager_id
        if effective_manager_id is not None:
            stmt = stmt.where(
                select(Lead.id)
                .where(
                    Lead.chat_id == Chat.id,
                    Lead.is_deleted.is_(False),
                    Lead.manager_id == effective_manager_id,
                )
                .exists()
            )
        if unassigned:
            stmt = stmt.where(
                select(Lead.id)
                .where(
                    Lead.chat_id == Chat.id,
                    Lead.is_deleted.is_(False),
                    Lead.manager_id.is_(None),
                )
                .exists()
            )
        if only_red:
            stmt = stmt.where(self._is_red_expr(sla_threshold_minutes))
        if only_unanswered:
            stmt = stmt.where(self._unanswered_expr())
        if only_unread:
            stmt = stmt.where(self._unread_expr())
        if tracking_link_id is not None:
            stmt = stmt.where(Chat.tracking_link_id == tracking_link_id)
        if search_query:
            stmt = stmt.where(self._search_expr(search_query))
        if date_from is not None or date_to is not None:
            added_at = func.coalesce(Chat.current_cycle_started_at, Chat.created_at)
            if date_from is not None:
                stmt = stmt.where(added_at >= date_from)
            if date_to is not None:
                stmt = stmt.where(added_at < date_to)
        if lead_statuses:
            stmt = stmt.where(
                select(Lead.id)
                .join(LeadStatus, LeadStatus.id == Lead.status_id)
                .where(
                    Lead.chat_id == Chat.id,
                    Lead.is_deleted.is_(False),
                    LeadStatus.code.in_(lead_statuses),
                )
                .exists()
            )
        if tag_ids:
            if tag_mode == "all":
                for tag_id in tag_ids:
                    stmt = stmt.where(self._tag_exists_expr(tag_id))
            else:
                stmt = stmt.where(
                    select(LeadTag.lead_id)
                    .join(Lead, Lead.id == LeadTag.lead_id)
                    .where(
                        Lead.chat_id == Chat.id,
                        Lead.is_deleted.is_(False),
                        LeadTag.tag_id.in_(tag_ids),
                    )
                    .exists()
                )

        if funnel_state:
            stmt = stmt.where(self._funnel_state_expr(funnel_state))
        return stmt

    @staticmethod
    def _search_expr(search_query: str) -> ColumnElement:
        needle = f"%{search_query.strip().lower()}%"
        if needle == "%%":
            return True
        lead_exists = (
            select(Lead.id)
            .where(
                Lead.chat_id == Chat.id,
                Lead.is_deleted.is_(False),
                or_(
                    func.lower(func.coalesce(Lead.name, "")).like(needle),
                    func.lower(func.coalesce(Lead.phone, "")).like(needle),
                    func.lower(func.coalesce(Lead.username, "")).like(needle),
                    func.lower(func.cast(Lead.custom_fields, String)).like(needle),
                ),
            )
            .exists()
        )
        tracking_exists = (
            select(TrackingLink.id)
            .where(
                TrackingLink.id == Chat.tracking_link_id,
                or_(
                    func.lower(func.coalesce(TrackingLink.code, "")).like(needle),
                    func.lower(func.coalesce(TrackingLink.ref_code, "")).like(needle),
                    func.lower(func.coalesce(TrackingLink.title, "")).like(needle),
                    func.lower(func.coalesce(TrackingLink.buyer_name, "")).like(needle),
                ),
            )
            .exists()
        )
        message_exists = (
            select(Message.id)
            .where(
                Message.chat_id == Chat.id,
                Message.created_at >= func.coalesce(Chat.current_cycle_started_at, Chat.created_at),
                or_(
                    func.lower(func.coalesce(Message.body, "")).like(needle),
                    func.lower(func.coalesce(Message.caption, "")).like(needle),
                ),
            )
            .limit(1)
            .exists()
        )
        return or_(
            func.lower(func.coalesce(Chat.contact_name, "")).like(needle),
            func.lower(func.coalesce(Chat.external_chat_id, "")).like(needle),
            func.lower(func.coalesce(Chat.external_user_id, "")).like(needle),
            lead_exists,
            tracking_exists,
            message_exists,
        )

    @staticmethod
    def _funnel_state_expr(funnel_state: str) -> ColumnElement:
        state_exists = (
            select(ChatFunnelState.id)
            .where(
                ChatFunnelState.chat_id == Chat.id,
                ChatFunnelState.completed_at.is_(None),
            )
            .exists()
        )
        waiting_exists = (
            select(ChatFunnelState.id)
            .where(
                ChatFunnelState.chat_id == Chat.id,
                ChatFunnelState.completed_at.is_(None),
                ChatFunnelState.waiting_for_answer.is_(True),
            )
            .exists()
        )
        completed_exists = (
            select(ChatFunnelState.id)
            .where(
                ChatFunnelState.chat_id == Chat.id,
                ChatFunnelState.completed_at.is_not(None),
            )
            .exists()
        )
        manual_after_completed = (
            select(ChatFunnelState.id)
            .where(
                ChatFunnelState.chat_id == Chat.id,
                ChatFunnelState.completed_at.is_not(None),
                Chat.last_user_message_at.is_not(None),
                Chat.last_user_message_at > ChatFunnelState.completed_at,
            )
            .exists()
        )
        if funnel_state == "waiting_for_answer":
            return waiting_exists
        if funnel_state == "in_funnel":
            return state_exists
        if funnel_state == "completed":
            return completed_exists
        return (~state_exists & ~completed_exists) | manual_after_completed

    @staticmethod
    def _tag_exists_expr(tag_id: UUID) -> ColumnElement:
        return (
            select(LeadTag.lead_id)
            .join(Lead, Lead.id == LeadTag.lead_id)
            .where(
                Lead.chat_id == Chat.id,
                Lead.is_deleted.is_(False),
                LeadTag.tag_id == tag_id,
            )
            .exists()
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    async def get_by_external(
        self,
        project_id: UUID,
        external_chat_id: str,
        bot_id: Optional[UUID] = None,
    ) -> Optional[Chat]:
        stmt = select(Chat).where(
            Chat.project_id == project_id,
            Chat.external_chat_id == external_chat_id,
            Chat.is_deleted.is_(False),
            Chat.reset_at.is_(None),
        )
        if bot_id is not None:
            stmt = stmt.where(Chat.bot_id == bot_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_reset_by_external(
        self,
        project_id: UUID,
        external_chat_id: str,
        bot_id: Optional[UUID] = None,
    ) -> Optional[Chat]:
        stmt = select(Chat).where(
            Chat.project_id == project_id,
            Chat.external_chat_id == external_chat_id,
            Chat.is_deleted.is_(False),
            Chat.reset_at.isnot(None),
        )
        if bot_id is not None:
            stmt = stmt.where(Chat.bot_id == bot_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_any_by_external(
        self,
        project_id: UUID,
        external_chat_id: str,
        bot_id: Optional[UUID] = None,
    ) -> Optional[Chat]:
        stmt = select(Chat).where(
            Chat.project_id == project_id,
            Chat.external_chat_id == external_chat_id,
        )
        if bot_id is not None:
            stmt = stmt.where(Chat.bot_id == bot_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active(self, chat_id: UUID, project_id: UUID) -> Optional[Chat]:
        """Single non-deleted chat scoped to a project."""
        result = await self.db.execute(
            select(Chat).where(
                Chat.id == chat_id,
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_any_in_project(self, chat_id: UUID, project_id: UUID) -> Optional[Chat]:
        """Fetch a non-deleted chat scoped to a project, including reset cycles."""
        result = await self.db.execute(
            select(Chat).where(
                Chat.id == chat_id,
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        project_id: UUID,
        limit: int = 50,
        offset: int = 0,
        only_unread: bool = False,
        only_unanswered: bool = False,
        only_red: bool = False,
        sla_threshold_minutes: int = 30,
        manager_id: Optional[UUID] = None,
        assigned_user_id: Optional[UUID] = None,
        unassigned: bool = False,
        search_query: Optional[str] = None,
        bot_id: Optional[UUID] = None,
        bot_ids: Sequence[UUID] | None = None,
        tracking_link_id: Optional[UUID] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        tag_ids: Sequence[UUID] | None = None,
        tag_mode: str = "any",
        lead_statuses: Sequence[str] | None = None,
        funnel_state: Optional[str] = None,
    ) -> list[Chat]:
        """
        Returns chats matching the given filters, ordered by priority:
          1. is_red DESC  (SLA breached)
          2. unanswered DESC
          3. last_message_at DESC NULLS LAST
        """
        stmt = self._apply_filters(
            self._base_select(project_id, bot_id=bot_id, bot_ids=bot_ids),
            only_unread=only_unread,
            only_unanswered=only_unanswered,
            only_red=only_red,
            sla_threshold_minutes=sla_threshold_minutes,
            manager_id=manager_id,
            assigned_user_id=assigned_user_id,
            unassigned=unassigned,
            search_query=search_query,
            tracking_link_id=tracking_link_id,
            date_from=date_from,
            date_to=date_to,
            tag_ids=tag_ids or (),
            tag_mode=tag_mode,
            lead_statuses=lead_statuses or (),
            funnel_state=funnel_state,
        )
        stmt = (
            stmt.order_by(
                self._is_red_expr(sla_threshold_minutes).desc(),
                self._unanswered_expr().desc(),
                Chat.last_message_at.desc().nullslast(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count(
        self,
        project_id: UUID,
        only_unread: bool = False,
        only_unanswered: bool = False,
        only_red: bool = False,
        sla_threshold_minutes: int = 30,
        manager_id: Optional[UUID] = None,
        assigned_user_id: Optional[UUID] = None,
        unassigned: bool = False,
        search_query: Optional[str] = None,
        bot_id: Optional[UUID] = None,
        bot_ids: Sequence[UUID] | None = None,
        tracking_link_id: Optional[UUID] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        tag_ids: Sequence[UUID] | None = None,
        tag_mode: str = "any",
        lead_statuses: Sequence[str] | None = None,
        funnel_state: Optional[str] = None,
    ) -> int:
        """
        Mirror of list() without LIMIT/OFFSET — used for pagination totals.

        COUNT(DISTINCT Chat.id) is used only when a JOIN is present — adding
        DISTINCT unconditionally hurts performance on the common no-join path.
        """
        count_col = func.count(Chat.id)
        stmt = select(count_col).where(
            Chat.project_id == project_id,
            Chat.is_deleted.is_(False),
            Chat.reset_at.is_(None),
        )
        if bot_id is not None:
            stmt = stmt.where(Chat.bot_id == bot_id)
        if bot_ids:
            stmt = stmt.where(Chat.bot_id.in_(bot_ids))

        stmt = self._apply_filters(
            stmt,
            only_unread=only_unread,
            only_unanswered=only_unanswered,
            only_red=only_red,
            sla_threshold_minutes=sla_threshold_minutes,
            manager_id=manager_id,
            assigned_user_id=assigned_user_id,
            unassigned=unassigned,
            search_query=search_query,
            tracking_link_id=tracking_link_id,
            date_from=date_from,
            date_to=date_to,
            tag_ids=tag_ids or (),
            tag_mode=tag_mode,
            lead_statuses=lead_statuses or (),
            funnel_state=funnel_state,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def update_timestamps(
        self,
        chat_id: UUID,
        sender_type: str,
        ts: datetime,
    ) -> None:
        """
        Update last_message_at (always) and the sender-specific timestamp.
        Called by MessageService inside the same DB transaction as the message INSERT.
        Never commits — the caller owns the transaction.

        Raises LookupError if the chat row was not found (0 rows updated).
        This should not happen in normal flow since MessageService validates
        the chat exists before calling this method.
        """
        cycle_start = case(
            (
                Chat.current_cycle_started_at.is_(None),
                ts,
            ),
            (
                Chat.current_cycle_started_at > ts,
                ts,
            ),
            else_=Chat.current_cycle_started_at,
        )
        values: dict = {
            "last_message_at": ts,
            "current_cycle_started_at": cycle_start,
            "updated_at": ts,
        }
        if sender_type == SenderType.USER:
            values["last_user_message_at"] = ts
        elif sender_type in {SenderType.MANAGER, SenderType.BOT}:
            values["last_manager_reply_at"] = ts

        result = await self.db.execute(
            update(Chat)
            .where(
                Chat.id == chat_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
            )
            .values(**values)
        )
        if result.rowcount == 0:
            raise LookupError("Chat not found or already deleted")

    async def mark_as_read(self, chat_id: UUID) -> None:
        now = datetime.now(timezone.utc)
        await self.db.execute(
            update(Chat)
            .where(Chat.id == chat_id, Chat.reset_at.is_(None))
            .values(last_read_at=now, updated_at=now)
        )

    async def reset_chat(self, chat_id: UUID) -> Optional[Chat]:
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            update(Chat)
            .where(
                Chat.id == chat_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
            )
            .values(
                tracking_link_id=None,
                reset_at=now,
                reset_count=Chat.reset_count + 1,
                current_cycle_started_at=None,
                last_message_at=None,
                last_user_message_at=None,
                last_manager_reply_at=None,
                last_read_at=None,
                updated_at=now,
            )
        )
        if result.rowcount == 0:
            return None
        return await self.get_by_id(chat_id)

    async def reactivate_reset_chat(
        self,
        chat_id: UUID,
        *,
        tracking_link_id: Optional[UUID],
        contact_name: Optional[str],
    ) -> Optional[Chat]:
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            update(Chat)
            .where(
                Chat.id == chat_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.isnot(None),
            )
            .values(
                tracking_link_id=tracking_link_id,
                contact_name=contact_name,
                reset_at=None,
                current_cycle_started_at=now,
                last_message_at=None,
                last_user_message_at=None,
                last_manager_reply_at=None,
                last_read_at=None,
                updated_at=now,
            )
        )
        if result.rowcount == 0:
            return None
        return await self.get_by_id(chat_id)

    async def count_red(self, project_id: UUID, sla_threshold_minutes: int) -> int:
        result = await self.db.execute(
            select(func.count()).where(
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                self._is_red_expr(sla_threshold_minutes),
            )
        )
        return result.scalar_one()

    async def count_unanswered(self, project_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count()).where(
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                self._unanswered_expr(),
            )
        )
        return result.scalar_one()
