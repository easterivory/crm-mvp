from __future__ import annotations

"""
Chat repository.

is_red / unanswered / unread are NOT stored — they are SQL boolean expressions
built from timestamp columns and evaluated inside the DB engine.

All expressions are defined as @staticmethod so they can be reused in WHERE,
ORDER BY, and count queries without repeating literal SQL.

Sorting contract:
  - latest: last_message_at DESC NULLS LAST
  - priority: is_red DESC → unanswered DESC → last_message_at DESC NULLS LAST
"""
from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, String, and_, case, func, or_, select, update

from app.core.constants import SenderType
from app.models.chat import Chat
from app.models.funnel import ChatFunnelState
from app.models.lead import Lead, LeadTag
from app.models.lead_status import LeadStatus
from app.models.message import Message
from app.models.tag import Tag
from app.models.tracking import TrackingLink
from app.repositories.base import BaseRepository


class ChatRepository(BaseRepository[Chat]):
    model = Chat
    CYCLE_START_TOLERANCE_SECONDS = 1

    # ── SQL expressions ────────────────────────────────────────────────────────

    @staticmethod
    def _unanswered_expr() -> ColumnElement:
        """
        True when the client sent at least one message and an operator has not
        replied after it. Legacy timestamp columns are used as a fallback while
        older rows are migrated by normal message flow.
        """
        last_client_message_at = func.coalesce(
            Chat.last_client_message_at,
            Chat.last_user_message_at,
        )
        last_operator_message_at = case(
            (
                Chat.last_client_message_at.is_(None),
                func.coalesce(Chat.last_operator_message_at, Chat.last_manager_reply_at),
            ),
            else_=Chat.last_operator_message_at,
        )
        return (
            Chat.is_blocked.is_(False)
            & Chat.is_blocked_by_user.is_(False)
            & (last_client_message_at.isnot(None))
            & (
                last_operator_message_at.is_(None)
                | (last_client_message_at > last_operator_message_at)
            )
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
        last_client_message_at = func.coalesce(
            Chat.last_client_message_at,
            Chat.last_user_message_at,
        )
        return ChatRepository._unanswered_expr() & (
            (func.now() - last_client_message_at)
            > func.make_interval(0, 0, 0, 0, 0, sla_threshold_minutes, 0)
        )

    @staticmethod
    def _unread_expr() -> ColumnElement:
        """
        True when the chat has unread client activity for the operator workspace.
        """
        return Chat.is_read.is_(False)

    @staticmethod
    def _has_text_expr(column) -> ColumnElement:
        return func.nullif(func.trim(func.coalesce(column, "")), "").isnot(None)

    @classmethod
    def _hot_lead_condition(cls) -> ColumnElement:
        """
        Sales-hot lead signal.

        This is intentionally separate from SLA/red chats: a hot lead is one
        that looks close to sale by score or strong buying intent, not merely a
        chat waiting for an operator reply.
        """
        return or_(
            func.coalesce(Lead.score_percent, 0) >= 70,
            and_(
                cls._has_text_expr(Lead.phone),
                or_(
                    Lead.has_card.is_(True),
                    cls._has_text_expr(Lead.preferred_call_time),
                    cls._has_text_expr(Lead.call_time_text),
                ),
            ),
            and_(
                Lead.has_card.is_(True),
                or_(
                    cls._has_text_expr(Lead.country),
                    cls._has_text_expr(Lead.username),
                ),
            ),
        )

    @classmethod
    def _is_hot_lead_expr(cls) -> ColumnElement:
        return (
            select(Lead.id)
            .where(
                Lead.chat_id == Chat.id,
                Lead.is_deleted.is_(False),
                cls._hot_lead_condition(),
            )
            .exists()
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
        only_hot_lead: bool,
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
        if only_hot_lead:
            stmt = stmt.where(self._is_hot_lead_expr())
        if only_unanswered:
            stmt = stmt.where(self._unanswered_expr())
        if only_unread:
            stmt = stmt.where(self._unread_expr())
        if tracking_link_id is not None:
            stmt = stmt.where(Chat.tracking_link_id == tracking_link_id)
        if search_query:
            stmt = stmt.where(self._search_expr(search_query))
        if date_from is not None or date_to is not None:
            activity_at = func.coalesce(
                Chat.last_message_at,
                Chat.current_cycle_started_at,
                Chat.created_at,
            )
            if date_from is not None:
                stmt = stmt.where(activity_at >= date_from)
            if date_to is not None:
                stmt = stmt.where(activity_at < date_to)
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
        query = search_query.strip().lower()
        if not query:
            return True
        needle = ChatRepository._search_needle(query)
        username_needle = ChatRepository._search_needle(query.removeprefix("@"))
        phone_digits = "".join(character for character in query if character.isdigit())
        cycle_started_at = Chat.current_cycle_started_at - func.make_interval(
            0,
            0,
            0,
            0,
            0,
            0,
            ChatRepository.CYCLE_START_TOLERANCE_SECONDS,
        )
        cycle_lower_bound = func.coalesce(cycle_started_at, Chat.created_at)
        lead_exists = (
            select(Lead.id)
            .where(
                Lead.chat_id == Chat.id,
                Lead.is_deleted.is_(False),
                or_(
                    func.lower(func.coalesce(Lead.name, "")).like(needle, escape="\\"),
                    func.lower(func.coalesce(Lead.phone, "")).like(needle, escape="\\"),
                    func.lower(func.coalesce(Lead.username, "")).like(username_needle, escape="\\"),
                    func.lower(func.cast(Lead.custom_fields, String)).like(needle, escape="\\"),
                    *(
                        [
                            func.regexp_replace(
                                func.coalesce(Lead.phone, ""),
                                r"\D",
                                "",
                                "g",
                            ).like(f"%{phone_digits}%")
                        ]
                        if phone_digits
                        else []
                    ),
                ),
            )
            .exists()
        )
        tracking_exists = (
            select(TrackingLink.id)
            .where(
                TrackingLink.id == Chat.tracking_link_id,
                or_(
                    func.lower(func.coalesce(TrackingLink.code, "")).like(needle, escape="\\"),
                    func.lower(func.coalesce(TrackingLink.ref_code, "")).like(needle, escape="\\"),
                    func.lower(func.coalesce(TrackingLink.title, "")).like(needle, escape="\\"),
                    func.lower(func.coalesce(TrackingLink.buyer_name, "")).like(needle, escape="\\"),
                ),
            )
            .exists()
        )
        message_exists = (
            select(Message.id)
            .where(
                Message.chat_id == Chat.id,
                Message.created_at >= cycle_lower_bound,
                or_(
                    func.lower(func.coalesce(Message.body, "")).like(needle, escape="\\"),
                    func.lower(func.coalesce(Message.caption, "")).like(needle, escape="\\"),
                ),
            )
            .limit(1)
            .exists()
        )
        return or_(
            func.lower(func.coalesce(Chat.contact_name, "")).like(needle, escape="\\"),
            func.lower(func.coalesce(Chat.external_chat_id, "")).like(needle, escape="\\"),
            func.lower(func.coalesce(Chat.external_user_id, "")).like(needle, escape="\\"),
            lead_exists,
            tracking_exists,
            message_exists,
        )

    @staticmethod
    def _search_needle(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

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
        paused_exists = (
            select(ChatFunnelState.id)
            .where(
                ChatFunnelState.chat_id == Chat.id,
                ChatFunnelState.completed_at.is_(None),
                ChatFunnelState.is_paused.is_(True),
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
        if funnel_state == "paused":
            return paused_exists
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

    async def get_active_by_telegram_identity(
        self,
        *,
        project_id: UUID,
        bot_id: UUID,
        telegram_id: int,
    ) -> Optional[Chat]:
        """Return the current private chat for one Telegram user and bot."""
        identity = str(telegram_id)
        result = await self.db.execute(
            select(Chat)
            .where(
                Chat.project_id == project_id,
                Chat.bot_id == bot_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                Chat.external_chat_id == identity,
            )
            .order_by(Chat.updated_at.desc(), Chat.created_at.desc())
            .limit(1)
        )
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

    async def is_blocked_by_user(
        self,
        chat_id: UUID,
        project_id: UUID | None = None,
    ) -> bool:
        stmt = select(Chat.is_blocked_by_user).where(
            Chat.id == chat_id,
            Chat.is_deleted.is_(False),
            Chat.reset_at.is_(None),
        )
        if project_id is not None:
            stmt = stmt.where(Chat.project_id == project_id)
        result = await self.db.execute(stmt)
        return bool(result.scalar_one_or_none())

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

    async def update_client_lang(
        self,
        chat_id: UUID,
        project_id: UUID,
        client_lang: str | None,
    ) -> Optional[Chat]:
        result = await self.db.execute(
            update(Chat)
            .where(
                Chat.id == chat_id,
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
            )
            .values(client_lang=client_lang, updated_at=func.now())
        )
        if result.rowcount == 0:
            return None
        return await self.get_active(chat_id, project_id)

    async def list(
        self,
        project_id: UUID,
        limit: int = 50,
        offset: int = 0,
        only_unread: bool = False,
        only_unanswered: bool = False,
        only_red: bool = False,
        only_hot_lead: bool = False,
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
        sort_by: str = "latest",
    ) -> list[Chat]:
        """
        Returns chats matching the given filters. The default order is the
        latest dialog activity; the operator can explicitly switch to SLA
        priority order.
        """
        stmt = self._apply_filters(
            self._base_select(project_id, bot_id=bot_id, bot_ids=bot_ids),
            only_unread=only_unread,
            only_unanswered=only_unanswered,
            only_red=only_red,
            only_hot_lead=only_hot_lead,
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
        if sort_by == "priority":
            stmt = stmt.order_by(
                self._is_red_expr(sla_threshold_minutes).desc(),
                self._unanswered_expr().desc(),
                Chat.last_message_at.desc().nullslast(),
                Chat.id.desc(),
            )
        else:
            stmt = stmt.order_by(
                Chat.last_message_at.desc().nullslast(),
                Chat.id.desc(),
            )
        stmt = stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count(
        self,
        project_id: UUID,
        only_unread: bool = False,
        only_unanswered: bool = False,
        only_red: bool = False,
        only_hot_lead: bool = False,
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
        sort_by: str = "latest",
    ) -> int:
        """
        Mirror of list() without LIMIT/OFFSET — used for pagination totals.

        COUNT(DISTINCT Chat.id) is used only when a JOIN is present — adding
        DISTINCT unconditionally hurts performance on the common no-join path.
        """
        del sort_by
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
            only_hot_lead=only_hot_lead,
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

    async def hot_lead_flags_for_chats(self, chat_ids: Sequence[UUID]) -> dict[UUID, bool]:
        if not chat_ids:
            return {}
        result = await self.db.execute(
            select(Lead.chat_id)
            .where(
                Lead.chat_id.in_(chat_ids),
                Lead.is_deleted.is_(False),
                self._hot_lead_condition(),
            )
            .distinct()
        )
        return {chat_id: True for chat_id in result.scalars().all()}

    async def latest_messages_for_chats(self, chat_ids: Sequence[UUID]) -> dict[UUID, Message]:
        if not chat_ids:
            return {}
        cycle_started_at = Chat.current_cycle_started_at - func.make_interval(
            0,
            0,
            0,
            0,
            0,
            0,
            self.CYCLE_START_TOLERANCE_SECONDS,
        )
        cycle_lower_bound = func.coalesce(cycle_started_at, Chat.created_at)
        result = await self.db.execute(
            select(Message)
            .distinct(Message.chat_id)
            .join(Chat, Chat.id == Message.chat_id)
            .where(
                Message.chat_id.in_(chat_ids),
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                Message.created_at >= cycle_lower_bound,
            )
            .order_by(Message.chat_id, Message.created_at.desc(), Message.id.desc())
        )
        return {message.chat_id: message for message in result.scalars().all()}

    async def search_hit_messages_for_chats(
        self,
        chat_ids: Sequence[UUID],
        search_query: str | None,
    ) -> dict[UUID, Message]:
        query = (search_query or "").strip()
        if not chat_ids or not query:
            return {}
        needle = self._search_needle(query.lower())
        cycle_started_at = Chat.current_cycle_started_at - func.make_interval(
            0,
            0,
            0,
            0,
            0,
            0,
            self.CYCLE_START_TOLERANCE_SECONDS,
        )
        cycle_lower_bound = func.coalesce(cycle_started_at, Chat.created_at)
        result = await self.db.execute(
            select(Message)
            .distinct(Message.chat_id)
            .join(Chat, Chat.id == Message.chat_id)
            .where(
                Message.chat_id.in_(chat_ids),
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                Message.created_at >= cycle_lower_bound,
                or_(
                    func.lower(func.coalesce(Message.body, "")).like(needle, escape="\\"),
                    func.lower(func.coalesce(Message.caption, "")).like(needle, escape="\\"),
                ),
            )
            .order_by(Message.chat_id, Message.created_at.desc(), Message.id.desc())
        )
        return {message.chat_id: message for message in result.scalars().all()}

    async def lead_tags_for_chats(self, chat_ids: Sequence[UUID]) -> dict[UUID, list[dict]]:
        if not chat_ids:
            return {}
        result = await self.db.execute(
            select(Lead.chat_id, Tag.id, Tag.name, Tag.color)
            .join(LeadTag, LeadTag.lead_id == Lead.id)
            .join(Tag, Tag.id == LeadTag.tag_id)
            .where(
                Lead.chat_id.in_(chat_ids),
                Lead.is_deleted.is_(False),
            )
            .order_by(Tag.name.asc())
        )
        tags_by_chat: dict[UUID, list[dict]] = {}
        for chat_id, tag_id, tag_name, tag_color in result.all():
            tags_by_chat.setdefault(chat_id, []).append(
                {"id": tag_id, "name": tag_name, "color": tag_color}
            )
        return tags_by_chat

    async def lead_statuses_for_chats(self, chat_ids: Sequence[UUID]) -> dict[UUID, dict]:
        if not chat_ids:
            return {}
        result = await self.db.execute(
            select(Lead.chat_id, LeadStatus.id, LeadStatus.code, LeadStatus.name)
            .join(LeadStatus, LeadStatus.id == Lead.status_id)
            .where(
                Lead.chat_id.in_(chat_ids),
                Lead.is_deleted.is_(False),
            )
        )
        statuses: dict[UUID, dict] = {}
        for chat_id, status_id, code, name in result.all():
            statuses[chat_id] = {"id": status_id, "code": code, "name": name}
        return statuses

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
            values["last_client_message_at"] = ts
            values["is_blocked_by_user"] = False
            values["is_read"] = False
            values["unanswered_minutes"] = 0
        elif sender_type == SenderType.MANAGER:
            values["last_manager_reply_at"] = ts
            values["last_operator_message_at"] = ts
            values["last_read_at"] = ts
            values["is_read"] = True
            values["unanswered_minutes"] = 0
        elif sender_type == SenderType.BOT:
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
            .values(last_read_at=now, is_read=True, updated_at=now)
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
                last_client_message_at=None,
                last_operator_message_at=None,
                last_read_at=None,
                is_read=True,
                unanswered_minutes=0,
                updated_at=now,
            )
        )
        if result.rowcount == 0:
            return None
        return await self.get_by_id(chat_id)

    async def set_blocked(
        self,
        *,
        chat_id: UUID,
        project_id: UUID,
        is_blocked: bool,
    ) -> Optional[Chat]:
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            update(Chat)
            .where(
                Chat.id == chat_id,
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
            )
            .values(is_blocked=is_blocked, updated_at=now)
        )
        if result.rowcount == 0:
            return None
        return await self.get_active(chat_id, project_id)

    async def set_blocked_by_user(
        self,
        *,
        project_id: UUID,
        external_chat_id: str,
        bot_id: Optional[UUID],
        is_blocked_by_user: bool,
    ) -> Optional[Chat]:
        now = datetime.now(timezone.utc)
        values: dict = {
            "is_blocked_by_user": is_blocked_by_user,
            "updated_at": now,
        }
        if is_blocked_by_user:
            values.update(
                {
                    "is_read": True,
                    "last_read_at": now,
                    "unanswered_minutes": 0,
                }
            )
        stmt = (
            update(Chat)
            .where(
                Chat.project_id == project_id,
                Chat.external_chat_id == str(external_chat_id),
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
            )
            .values(**values)
        )
        if bot_id is not None:
            stmt = stmt.where(Chat.bot_id == bot_id)
        result = await self.db.execute(stmt)
        if result.rowcount == 0:
            return None
        lookup = select(Chat).where(
            Chat.project_id == project_id,
            Chat.external_chat_id == str(external_chat_id),
            Chat.is_deleted.is_(False),
            Chat.reset_at.is_(None),
        )
        if bot_id is not None:
            lookup = lookup.where(Chat.bot_id == bot_id)
        refreshed = await self.db.execute(lookup.order_by(Chat.updated_at.desc()).limit(1))
        return refreshed.scalar_one_or_none()

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
                last_client_message_at=None,
                last_operator_message_at=None,
                last_read_at=None,
                is_read=True,
                unanswered_minutes=0,
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
