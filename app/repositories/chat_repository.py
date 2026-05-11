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
from typing import Optional
from uuid import UUID

from sqlalchemy import ColumnElement, func, select, update

from app.core.constants import SenderType
from app.models.chat import Chat
from app.models.lead import Lead
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

    def _base_select(self, project_id: UUID, bot_id: Optional[UUID] = None):
        stmt = select(Chat).where(
            Chat.project_id == project_id,
            Chat.is_deleted.is_(False),
        )
        if bot_id is not None:
            stmt = stmt.where(Chat.bot_id == bot_id)
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
    ):
        if manager_id is not None:
            # INNER JOIN: only chats that have a lead assigned to this manager.
            stmt = (
                stmt.join(
                    Lead,
                    (Lead.chat_id == Chat.id) & Lead.is_deleted.is_(False),
                )
                .where(Lead.manager_id == manager_id)
            )

        if only_red:
            stmt = stmt.where(self._is_red_expr(sla_threshold_minutes))
        if only_unanswered:
            stmt = stmt.where(self._unanswered_expr())
        if only_unread:
            stmt = stmt.where(self._unread_expr())

        return stmt

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
        bot_id: Optional[UUID] = None,
    ) -> list[Chat]:
        """
        Returns chats matching the given filters, ordered by priority:
          1. is_red DESC  (SLA breached)
          2. unanswered DESC
          3. last_message_at DESC NULLS LAST
        """
        stmt = self._apply_filters(
            self._base_select(project_id, bot_id=bot_id),
            only_unread=only_unread,
            only_unanswered=only_unanswered,
            only_red=only_red,
            sla_threshold_minutes=sla_threshold_minutes,
            manager_id=manager_id,
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
        bot_id: Optional[UUID] = None,
    ) -> int:
        """
        Mirror of list() without LIMIT/OFFSET — used for pagination totals.

        COUNT(DISTINCT Chat.id) is used only when a JOIN is present — adding
        DISTINCT unconditionally hurts performance on the common no-join path.
        """
        # Use DISTINCT only when the JOIN could produce duplicate chat rows.
        count_col = (
            func.count(Chat.id.distinct())
            if manager_id is not None
            else func.count(Chat.id)
        )
        stmt = select(count_col).where(
            Chat.project_id == project_id,
            Chat.is_deleted.is_(False),
        )
        if bot_id is not None:
            stmt = stmt.where(Chat.bot_id == bot_id)

        stmt = self._apply_filters(
            stmt,
            only_unread=only_unread,
            only_unanswered=only_unanswered,
            only_red=only_red,
            sla_threshold_minutes=sla_threshold_minutes,
            manager_id=manager_id,
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
        values: dict = {"last_message_at": ts, "updated_at": ts}
        if sender_type == SenderType.USER:
            values["last_user_message_at"] = ts
        elif sender_type in {SenderType.MANAGER, SenderType.BOT}:
            values["last_manager_reply_at"] = ts

        result = await self.db.execute(
            update(Chat)
            .where(Chat.id == chat_id, Chat.is_deleted.is_(False))
            .values(**values)
        )
        if result.rowcount == 0:
            raise LookupError("Chat not found or already deleted")

    async def mark_as_read(self, chat_id: UUID) -> None:
        now = datetime.now(timezone.utc)
        await self.db.execute(
            update(Chat)
            .where(Chat.id == chat_id)
            .values(last_read_at=now, updated_at=now)
        )

    async def count_red(self, project_id: UUID, sla_threshold_minutes: int) -> int:
        result = await self.db.execute(
            select(func.count()).where(
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                self._is_red_expr(sla_threshold_minutes),
            )
        )
        return result.scalar_one()

    async def count_unanswered(self, project_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count()).where(
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                self._unanswered_expr(),
            )
        )
        return result.scalar_one()
