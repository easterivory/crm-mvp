from __future__ import annotations

"""
Chat repository.

is_red / unanswered are SQL expressions. Unread workspace state is backed by
Chat.is_read and combined with routing reasons inside the DB engine.

All expressions are defined as @staticmethod so they can be reused in WHERE,
ORDER BY, and count queries without repeating literal SQL.

Sorting contract:
  - latest: last_message_at DESC NULLS LAST
  - priority: is_red DESC → unanswered DESC → last_message_at DESC NULLS LAST
"""
from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, String, and_, case, false, func, or_, select, update

from app.core.constants import SenderType
from app.models.chat import Chat
from app.models.funnel import ChatFunnelState
from app.models.lead import Lead, LeadTag
from app.models.lead_status import LeadStatus
from app.models.message import Message
from app.models.partner import LeadSubmission
from app.models.project import Project
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

    @classmethod
    def _workspace_unread_expr(
        cls,
        *,
        project_format: str,
        push_unread_threshold: int,
        use_confidence_score: bool,
    ) -> ColumnElement:
        # Routing events set is_read=False when attention is required. A later
        # explicit read is the global acknowledgement and must win over every
        # routing reason, otherwise reviewed chats remain in this workspace.
        unassigned = (
            select(Lead.id)
            .select_from(Lead)
            .where(
                Lead.chat_id == Chat.id,
                Lead.is_deleted.is_(False),
                Lead.manager_id.is_(None),
            )
            .correlate(Chat)
            .exists()
        )
        active_submission = (
            select(LeadSubmission.id)
            .select_from(LeadSubmission)
            .where(
                LeadSubmission.lead_id == Lead.id,
                LeadSubmission.status.in_(
                    (
                        "pending",
                        "processing",
                        "success",
                        "accepted",
                        "submitted",
                        "duplicate",
                    )
                ),
            )
            .correlate(Lead)
            .exists()
        )
        completed_potential = false()
        if use_confidence_score:
            completed_potential = (
                select(Lead.id)
                .select_from(Lead)
                .join(ChatFunnelState, ChatFunnelState.chat_id == Lead.chat_id)
                .where(
                    Lead.chat_id == Chat.id,
                    Lead.is_deleted.is_(False),
                    ChatFunnelState.completed_at.is_not(None),
                    Lead.score_percent < 100,
                    ~active_submission,
                )
                .correlate(Chat)
                .exists()
            )
        manual_required = (
            select(LeadSubmission.id)
            .select_from(LeadSubmission)
            .join(Lead, Lead.id == LeadSubmission.lead_id)
            .where(
                Lead.chat_id == Chat.id,
                Lead.is_deleted.is_(False),
                LeadSubmission.status == "manual_required",
            )
            .correlate(Chat)
            .exists()
        )
        gambling_attention = false()
        if project_format == "gambling":
            gambling_attention = or_(
                Chat.unanswered_push_count >= max(push_unread_threshold, 1),
                Chat.has_out_of_scenario_message.is_(True),
            )
        return and_(
            Chat.is_read.is_(False),
            or_(
                unassigned,
                completed_potential,
                manual_required,
                gambling_attention,
            ),
        )

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
        current_step_id: Optional[UUID] = None,
        workspace_view: Optional[str] = None,
        viewer_id: Optional[UUID] = None,
        hide_assigned_from_all: bool = False,
        project_format: str = "submission",
        push_unread_threshold: int = 1,
        use_confidence_score: bool = True,
    ):
        if workspace_view == "unread":
            stmt = stmt.where(
                self._workspace_unread_expr(
                    project_format=project_format,
                    push_unread_threshold=push_unread_threshold,
                    use_confidence_score=use_confidence_score,
                )
            )
        elif workspace_view == "mine":
            if viewer_id is None:
                stmt = stmt.where(Chat.id.is_(None))
            else:
                stmt = stmt.where(
                    select(Lead.id)
                    .where(
                        Lead.chat_id == Chat.id,
                        Lead.is_deleted.is_(False),
                        Lead.manager_id == viewer_id,
                    )
                    .exists()
                )
        elif workspace_view == "favorites":
            stmt = stmt.where(Chat.is_favorite.is_(True))
        elif workspace_view == "all" and hide_assigned_from_all:
            foreign_assignment = Lead.manager_id.isnot(None)
            if viewer_id is not None:
                foreign_assignment = and_(
                    foreign_assignment,
                    Lead.manager_id != viewer_id,
                )
            stmt = stmt.where(
                ~select(Lead.id)
                .where(
                    Lead.chat_id == Chat.id,
                    Lead.is_deleted.is_(False),
                    foreign_assignment,
                )
                .exists()
            )

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
        if current_step_id is not None:
            stmt = stmt.where(
                select(ChatFunnelState.id)
                .where(
                    ChatFunnelState.chat_id == Chat.id,
                    ChatFunnelState.current_step_id == current_step_id,
                )
                .exists()
            )
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
        current_step_id: Optional[UUID] = None,
        sort_by: str = "latest",
        workspace_view: Optional[str] = None,
        viewer_id: Optional[UUID] = None,
        hide_assigned_from_all: bool = False,
        project_format: str = "submission",
        push_unread_threshold: int = 1,
        use_confidence_score: bool = True,
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
            current_step_id=current_step_id,
            workspace_view=workspace_view,
            viewer_id=viewer_id,
            hide_assigned_from_all=hide_assigned_from_all,
            project_format=project_format,
            push_unread_threshold=push_unread_threshold,
            use_confidence_score=use_confidence_score,
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
        current_step_id: Optional[UUID] = None,
        sort_by: str = "latest",
        workspace_view: Optional[str] = None,
        viewer_id: Optional[UUID] = None,
        hide_assigned_from_all: bool = False,
        project_format: str = "submission",
        push_unread_threshold: int = 1,
        use_confidence_score: bool = True,
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
            current_step_id=current_step_id,
            workspace_view=workspace_view,
            viewer_id=viewer_id,
            hide_assigned_from_all=hide_assigned_from_all,
            project_format=project_format,
            push_unread_threshold=push_unread_threshold,
            use_confidence_score=use_confidence_score,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def workspace_counts(
        self,
        *,
        project_id: UUID,
        viewer_id: UUID,
        hide_assigned_from_all: bool,
        project_format: str = "submission",
        push_unread_threshold: int = 1,
        use_confidence_score: bool = True,
        bot_id: UUID | None = None,
        bot_ids: Sequence[UUID] | None = None,
    ) -> dict[str, int]:
        all_filter = Lead.manager_id.is_(None)
        if hide_assigned_from_all:
            all_filter = or_(all_filter, Lead.manager_id == viewer_id)

        all_count = func.count(Chat.id)
        if hide_assigned_from_all:
            all_count = all_count.filter(all_filter)

        stmt = (
            select(
                func.count(Chat.id)
                .filter(
                    self._workspace_unread_expr(
                        project_format=project_format,
                        push_unread_threshold=push_unread_threshold,
                        use_confidence_score=use_confidence_score,
                    )
                )
                .label("unread"),
                func.count(Chat.id)
                .filter(self._unanswered_expr())
                .label("unanswered"),
                func.count(Chat.id)
                .filter(Lead.manager_id == viewer_id)
                .label("mine"),
                all_count.label("all"),
                func.count(Chat.id)
                .filter(Chat.is_favorite.is_(True))
                .label("favorites"),
            )
            .select_from(Chat)
            .outerjoin(
                Lead,
                and_(
                    Lead.chat_id == Chat.id,
                    Lead.is_deleted.is_(False),
                ),
            )
            .where(
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
            )
        )
        if bot_id is not None:
            stmt = stmt.where(Chat.bot_id == bot_id)
        if bot_ids:
            stmt = stmt.where(Chat.bot_id.in_(bot_ids))

        row = (await self.db.execute(stmt)).one()._mapping
        return {
            "unread": int(row["unread"] or 0),
            "unanswered": int(row["unanswered"] or 0),
            "mine": int(row["mine"] or 0),
            "all": int(row["all"] or 0),
            "favorites": int(row["favorites"] or 0),
        }

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
            values["unanswered_push_count"] = 0
        elif sender_type == SenderType.MANAGER:
            values["last_manager_reply_at"] = ts
            values["last_operator_message_at"] = ts
            values["last_read_at"] = ts
            values["is_read"] = True
            values["unanswered_minutes"] = 0
            values["has_restarted_bot"] = False
            values["unanswered_push_count"] = 0
            values["has_out_of_scenario_message"] = False
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
            .values(
                last_read_at=now,
                is_read=True,
                has_out_of_scenario_message=False,
                updated_at=now,
            )
        )

    async def mark_as_unread(self, chat_id: UUID) -> None:
        await self.db.execute(
            update(Chat)
            .where(
                Chat.id == chat_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
            )
            .values(is_read=False, updated_at=func.now())
        )

    async def set_favorite(
        self,
        *,
        chat_id: UUID,
        project_id: UUID,
        is_favorite: bool,
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
            .values(is_favorite=is_favorite, updated_at=now)
        )
        if result.rowcount == 0:
            return None
        return await self.get_active(chat_id, project_id)

    async def set_assignment_expires_at(
        self,
        *,
        chat_id: UUID,
        project_id: UUID,
        assignment_expires_at: datetime | None,
    ) -> bool:
        result = await self.db.execute(
            update(Chat)
            .where(
                Chat.id == chat_id,
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
            )
            .values(
                assignment_expires_at=assignment_expires_at,
                updated_at=func.now(),
            )
        )
        return bool(result.rowcount)

    async def renew_assignment_on_incoming(
        self,
        *,
        chat_id: UUID,
        project_id: UUID,
        assignment_expires_at: datetime,
    ) -> bool:
        assigned_lead = (
            select(Lead.id)
            .where(
                Lead.chat_id == Chat.id,
                Lead.is_deleted.is_(False),
                Lead.manager_id.isnot(None),
            )
            .exists()
        )
        result = await self.db.execute(
            update(Chat)
            .where(
                Chat.id == chat_id,
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                assigned_lead,
            )
            .values(
                assignment_expires_at=assignment_expires_at,
                updated_at=func.now(),
            )
        )
        return bool(result.rowcount)

    async def mark_out_of_scenario_message(
        self,
        *,
        chat_id: UUID,
        project_id: UUID,
    ) -> bool:
        result = await self.db.execute(
            update(Chat)
            .where(
                Chat.id == chat_id,
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
            )
            .values(
                has_out_of_scenario_message=True,
                is_read=False,
                updated_at=func.now(),
            )
        )
        return bool(result.rowcount)

    async def increment_unanswered_push_count(
        self,
        *,
        chat_id: UUID,
    ) -> bool:
        next_push_count = Chat.unanswered_push_count + 1
        project_format = (
            select(Project.project_format)
            .where(Project.id == Chat.project_id)
            .scalar_subquery()
        )
        push_unread_threshold = (
            select(Project.push_unread_threshold)
            .where(Project.id == Chat.project_id)
            .scalar_subquery()
        )
        result = await self.db.execute(
            update(Chat)
            .where(
                Chat.id == chat_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
            )
            .values(
                unanswered_push_count=next_push_count,
                is_read=case(
                    (
                        and_(
                            project_format == "gambling",
                            next_push_count >= func.coalesce(push_unread_threshold, 1),
                        ),
                        False,
                    ),
                    else_=Chat.is_read,
                ),
                updated_at=func.now(),
            )
        )
        return bool(result.rowcount)

    async def release_expired_assignments(
        self,
        *,
        project_id: UUID,
        expires_before: datetime,
        chat_id: UUID | None = None,
    ) -> list[tuple[UUID, UUID, UUID]]:
        stmt = (
            select(Chat.id, Lead.id, Lead.manager_id)
            .join(Lead, Lead.chat_id == Chat.id)
            .where(
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                Chat.assignment_expires_at.isnot(None),
                Chat.assignment_expires_at < expires_before,
                Lead.is_deleted.is_(False),
                Lead.manager_id.isnot(None),
            )
            .with_for_update(skip_locked=True)
        )
        if chat_id is not None:
            stmt = stmt.where(Chat.id == chat_id)
        result = await self.db.execute(stmt)
        rows = list(result.all())
        if not rows:
            return []

        chat_ids = [row[0] for row in rows]
        lead_ids = [row[1] for row in rows]
        await self.db.execute(
            update(Lead)
            .where(Lead.id.in_(lead_ids))
            .values(manager_id=None, updated_at=expires_before)
        )
        await self.db.execute(
            update(Chat)
            .where(Chat.id.in_(chat_ids))
            .values(
                assignment_expires_at=None,
                is_read=False,
                updated_at=expires_before,
            )
        )
        return [(row[0], row[1], row[2]) for row in rows if row[2] is not None]

    async def mark_bot_restarted(
        self,
        *,
        chat_id: UUID,
        project_id: UUID,
    ) -> bool:
        result = await self.db.execute(
            update(Chat)
            .where(
                Chat.id == chat_id,
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
            )
            .values(has_restarted_bot=True, updated_at=func.now())
        )
        return bool(result.rowcount)

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
                assignment_expires_at=None,
                has_restarted_bot=False,
                unanswered_push_count=0,
                has_out_of_scenario_message=False,
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
                assignment_expires_at=None,
                has_restarted_bot=False,
                unanswered_push_count=0,
                has_out_of_scenario_message=False,
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
