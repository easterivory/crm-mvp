"""
ChatService — chat listing, filtering, sorting, and timestamp management.

Computed flags contract:
  is_red and unanswered are computed. unread reflects the persisted
  Chat.is_read acknowledgement state.

  In bulk queries (get_chat_list):
    - SQL expressions in ChatRepository filter and sort rows inside the DB.
    - _compute_flags() is called in Python for each returned Chat to populate
      the output schema. This is safe because timestamps are already loaded;
      no additional DB round-trips occur.

  In single-object queries (get_chat):
    - Same _compute_flags() logic, same cost.

  The two computation paths (SQL + Python) are intentionally kept in sync.
  If SLA logic changes, update both _is_red_expr() in ChatRepository and
  _compute_flags() here.

Sorting order is selected by the caller:
  - latest: last_message_at DESC NULLS LAST
  - priority: is_red DESC, unanswered DESC, last_message_at DESC NULLS LAST
"""
import re
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AuditAction, EntityType, RoleName, SenderType
from app.models.chat import Chat
from app.models.message import Message
from app.models.user import User
from app.repositories.bot_repository import BotRepository
from app.repositories.chat_repository import ChatRepository
from app.repositories.funnel_repository import FunnelRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.chat import (
    ChatCreate,
    ChatFilters,
    ChatLanguageUpdate,
    ChatLeadStatusOut,
    ChatOut,
    ChatTagOut,
    ChatWorkspaceCountsOut,
)
from app.services.assignment_service import AssignmentService
from app.services.audit_service import AuditService
from app.services.chat_lease_service import ChatLeaseService
from app.services.funnel_runtime_service import FunnelRuntimeService


class ChatService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.bot_repo = BotRepository(db)
        self.chat_repo = ChatRepository(db)
        self.funnel_repo = FunnelRepository(db)
        self.lead_repo = LeadRepository(db)
        self.project_repo = ProjectRepository(db)
        self.audit = AuditService(db)
        self.chat_lease = ChatLeaseService(db)

    # ── Public methods ─────────────────────────────────────────────────────────

    async def get_chat_list(
        self,
        project_id: UUID,
        filters: ChatFilters,
        limit: int,
        offset: int,
        actor: User | None = None,
    ) -> tuple[list[ChatOut], int]:
        """
        Returns a paginated, filtered, and sorted list of chats together with
        the total count (for the caller to build PaginatedResponse).

        Filter semantics:
          - filters.unread / unanswered / is_red — if True, keep only matching
            chats; if None or False, no restriction on that dimension.
          - filters.is_hot_lead — if True, keep only sales-hot leads. This is
            intentionally separate from SLA-red unanswered chats.
          - filters.manager_id — if set, restrict to chats whose lead is
            assigned to that manager (JOIN with leads table).
        """
        project = await self.project_repo.get_active(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        sla = project.sla_threshold_minutes
        await self.chat_lease.release_expired(project_id=project_id)

        # 3.1 Use `is True` instead of `bool()` so that None and False are both
        # treated as "no filter". bool(None) == False is incidentally the same
        # result, but `is True` makes the intent explicit and avoids accidental
        # truthy coercion of unexpected values (e.g. 0, empty string).
        filter_kwargs: dict = dict(
            project_id=project_id,
            search_query=(filters.q or "").strip() or None,
            only_unread=filters.unread is True,
            only_unanswered=filters.unanswered is True
            or filters.has_unanswered_incoming is True,
            only_red=filters.is_red is True,
            only_hot_lead=filters.is_hot_lead is True,
            sla_threshold_minutes=sla,
            manager_id=filters.manager_id,
            assigned_user_id=filters.assigned_user_id,
            unassigned=filters.unassigned is True,
            bot_id=filters.bot_id,
            bot_ids=filters.bot_ids,
            tracking_link_id=filters.tracking_link_id,
            date_from=filters.date_from,
            date_to=filters.date_to,
            tag_ids=filters.tag_ids,
            tag_mode=filters.tag_mode,
            lead_statuses=filters.lead_statuses,
            funnel_state=filters.funnel_state,
            current_step_id=filters.current_step_id,
            sort_by=filters.sort_by,
            workspace_view=filters.workspace_view,
            viewer_id=actor.id if actor is not None else None,
            hide_assigned_from_all=(
                bool(project.hide_assigned_chats_from_all)
                if filters.workspace_view == "all"
                else False
            ),
            project_format=project.project_format,
            push_unread_threshold=project.push_unread_threshold,
            use_confidence_score=project.use_confidence_score,
        )

        # Sequential — AsyncSession does not support concurrent operations.
        chats = await self.chat_repo.list(limit=limit, offset=offset, **filter_kwargs)
        total = await self.chat_repo.count(**filter_kwargs)
        chat_ids = [chat.id for chat in chats]

        contexts = await self.funnel_repo.get_chat_funnel_contexts(
            project_id=project_id,
            chat_ids=chat_ids,
        )
        latest_messages = await self.chat_repo.latest_messages_for_chats(chat_ids)
        search_hits = await self.chat_repo.search_hit_messages_for_chats(
            chat_ids,
            filters.q,
        )
        tags_by_chat = await self.chat_repo.lead_tags_for_chats(chat_ids)
        statuses_by_chat = await self.chat_repo.lead_statuses_for_chats(chat_ids)
        hot_leads_by_chat = await self.chat_repo.hot_lead_flags_for_chats(chat_ids)
        items = [
            self._chat_out(
                chat,
                sla,
                contexts.get(chat.id),
                latest_message=latest_messages.get(chat.id),
                search_hit=search_hits.get(chat.id),
                search_query=filters.q,
                tags=tags_by_chat.get(chat.id, []),
                lead_status=statuses_by_chat.get(chat.id),
                is_hot_lead=hot_leads_by_chat.get(chat.id, False),
            )
            for chat in chats
        ]
        return items, total

    async def get_chat(
        self,
        chat_id: UUID,
        project_id: UUID,
        actor: User | None = None,
    ) -> ChatOut:
        """Returns a single chat with computed flags populated."""
        project = await self.project_repo.get_active(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        await self.chat_lease.release_expired(project_id=project_id, chat_id=chat_id)
        chat = await self.chat_repo.get_active(chat_id, project_id)
        if chat is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found",
            )

        if actor is not None and actor.role_name == RoleName.MANAGER:
            lead = await self.lead_repo.get_existing_by_chat(chat_id, project_id)
            if lead is not None and lead.manager_id is None:
                try:
                    await AssignmentService(self.db).assign_manager(
                        lead_id=lead.id,
                        project_id=project_id,
                        manager_id=actor.id,
                        actor_id=actor.id,
                    )
                except HTTPException as exc:
                    if exc.status_code != status.HTTP_409_CONFLICT:
                        raise
                chat = await self.chat_repo.get_active(chat_id, project_id)
                if chat is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Chat not found",
                    )

        contexts = await self.funnel_repo.get_chat_funnel_contexts(
            project_id=project_id,
            chat_ids=[chat.id],
        )
        latest_messages = await self.chat_repo.latest_messages_for_chats([chat.id])
        tags_by_chat = await self.chat_repo.lead_tags_for_chats([chat.id])
        statuses_by_chat = await self.chat_repo.lead_statuses_for_chats([chat.id])
        hot_leads_by_chat = await self.chat_repo.hot_lead_flags_for_chats([chat.id])
        return self._chat_out(
            chat,
            project.sla_threshold_minutes,
            contexts.get(chat.id),
            latest_message=latest_messages.get(chat.id),
            tags=tags_by_chat.get(chat.id, []),
            lead_status=statuses_by_chat.get(chat.id),
            is_hot_lead=hot_leads_by_chat.get(chat.id, False),
        )

    async def get_workspace_counts(
        self,
        *,
        project_id: UUID,
        actor: User,
        bot_id: UUID | None = None,
        bot_ids: list[UUID] | None = None,
    ) -> ChatWorkspaceCountsOut:
        project = await self.project_repo.get_active(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        await self.chat_lease.release_expired(project_id=project_id)
        counts = await self.chat_repo.workspace_counts(
            project_id=project_id,
            viewer_id=actor.id,
            hide_assigned_from_all=project.hide_assigned_chats_from_all,
            project_format=project.project_format,
            push_unread_threshold=project.push_unread_threshold,
            use_confidence_score=project.use_confidence_score,
            bot_id=bot_id,
            bot_ids=bot_ids,
        )
        return ChatWorkspaceCountsOut(
            **counts,
            hide_assigned_chats_from_all=project.hide_assigned_chats_from_all,
            chat_lease_minutes=project.chat_lease_minutes,
            project_format=project.project_format,
            push_unread_threshold=project.push_unread_threshold,
        )

    async def set_favorite(
        self,
        *,
        chat_id: UUID,
        project_id: UUID,
        is_favorite: bool,
    ) -> ChatOut:
        updated = await self.chat_repo.set_favorite(
            chat_id=chat_id,
            project_id=project_id,
            is_favorite=is_favorite,
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found",
            )
        return await self.get_chat(chat_id=chat_id, project_id=project_id)

    async def update_language(
        self,
        *,
        chat_id: UUID,
        project_id: UUID,
        data: ChatLanguageUpdate,
    ) -> ChatOut:
        project = await self.project_repo.get_active(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        client_lang = self._normalize_language_code(data.client_lang)
        chat = await self.chat_repo.update_client_lang(
            chat_id=chat_id,
            project_id=project_id,
            client_lang=client_lang,
        )
        if chat is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found",
            )
        return self._chat_out(chat, project.sla_threshold_minutes, None)

    async def create_chat(self, project_id: UUID, data: ChatCreate) -> ChatOut:
        project = await self.project_repo.get_active(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        external_chat_id = self._normalize_required(
            data.external_chat_id,
            field_name="external_chat_id",
        )
        external_user_id = self._normalize_required(
            data.external_user_id,
            field_name="external_user_id",
        )
        contact_name = self._normalize_optional(data.contact_name)
        if data.bot_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="bot_id is required for new chats",
            )
        bot = await self.bot_repo.get_by_id_in_project(data.bot_id, project_id)
        if bot is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Bot does not exist in this project",
            )

        existing = await self.chat_repo.get_any_by_external(
            project_id,
            external_chat_id,
            bot_id=data.bot_id,
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Chat with this external_chat_id already exists in this project",
            )

        try:
            async with self.db.begin_nested():
                chat = await self.chat_repo.create(
                    project_id=project_id,
                    bot_id=data.bot_id,
                    external_chat_id=external_chat_id,
                    external_user_id=external_user_id,
                    contact_name=contact_name,
                )
        except IntegrityError:
            existing = await self.chat_repo.get_any_by_external(
                project_id,
                external_chat_id,
                bot_id=data.bot_id,
            )
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Chat with this external_chat_id already exists "
                        "in this project"
                    ),
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not create chat",
            )

        return self._chat_out(chat, project.sla_threshold_minutes, None)

    async def update_timestamps(
        self, chat_id: UUID, sender_type: str, ts: datetime
    ) -> None:
        """
        Called by MessageService inside the same DB transaction.
        Delegates straight to the repository — no business logic here.
        """
        await self.chat_repo.update_timestamps(chat_id, sender_type, ts)
        if sender_type == SenderType.USER:
            chat = await self.chat_repo.get_by_id(chat_id)
            if chat is not None:
                await self.chat_lease.renew_from_client_message(
                    project_id=chat.project_id,
                    chat_id=chat_id,
                )

    async def mark_as_read(self, chat_id: UUID, project_id: UUID) -> None:
        chat = await self.chat_repo.get_active(chat_id, project_id)
        if chat is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found",
            )
        await self.chat_repo.mark_as_read(chat_id)

    async def reset_chat(
        self,
        chat_id: UUID,
        project_id: UUID,
        actor_id: UUID,
    ) -> ChatOut:
        chat = await self.chat_repo.get_active(chat_id, project_id)
        if chat is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found",
            )

        lead = await self.lead_repo.get_existing_by_chat(chat_id, project_id)
        if lead is not None:
            await self.lead_repo.clear_tags(lead.id)
            lead = await self.lead_repo.mark_deleted_for_chat(chat_id, project_id)

        await self.bot_repo.reset_chat_state(chat_id)
        await FunnelRuntimeService(self.db).reset_chat_state(chat_id)
        updated = await self.chat_repo.reset_chat(chat_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Chat was already reset or changed by another request",
            )

        await self.audit.log(
            project_id=project_id,
            action=AuditAction.CHAT_RESET,
            entity_type=EntityType.CHAT,
            entity_id=chat_id,
            actor_id=actor_id,
            meta={
                "external_chat_id": chat.external_chat_id,
                "bot_id": str(chat.bot_id) if chat.bot_id else None,
                "lead_id": str(lead.id) if lead else None,
            },
        )

        return self._chat_out(updated, 0, None)

    async def set_chat_blocked(
        self,
        *,
        chat_id: UUID,
        project_id: UUID,
        actor_id: UUID,
        is_blocked: bool,
    ) -> ChatOut:
        project = await self.project_repo.get_active(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        chat = await self.chat_repo.get_active(chat_id, project_id)
        if chat is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found",
            )
        if chat.is_blocked == is_blocked:
            return self._chat_out(chat, project.sla_threshold_minutes, None)

        updated = await self.chat_repo.set_blocked(
            chat_id=chat_id,
            project_id=project_id,
            is_blocked=is_blocked,
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Chat was changed by another request",
            )
        await self.audit.log(
            project_id=project_id,
            action=AuditAction.CHAT_BLOCKED if is_blocked else AuditAction.CHAT_UNBLOCKED,
            entity_type=EntityType.CHAT,
            entity_id=chat_id,
            actor_id=actor_id,
            meta={
                "external_chat_id": chat.external_chat_id,
                "bot_id": str(chat.bot_id) if chat.bot_id else None,
            },
        )
        return self._chat_out(updated, project.sla_threshold_minutes, None)

    async def count_red(self, project_id: UUID) -> int:
        project = await self.project_repo.get_active(project_id)
        if project is None:
            return 0
        return await self.chat_repo.count_red(project_id, project.sla_threshold_minutes)

    async def count_unanswered(self, project_id: UUID) -> int:
        return await self.chat_repo.count_unanswered(project_id)

    # ── Internal ───────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_flags(chat: Chat, sla_threshold_minutes: int) -> dict:
        """
        Python-side flag computation from already-loaded Chat timestamps.

        CRITICAL: must stay logically identical to the SQL expressions in
        ChatRepository (_unanswered_expr, _is_red_expr, _unread_expr).
        If the SLA logic or any flag definition changes, update BOTH places.
        The SQL path controls DB-side filtering and ordering; this path
        controls what appears in the API response.

        Called once per Chat after it is fetched — no extra DB queries.
        """
        now = datetime.now(timezone.utc)
        last_client_message_at = (
            getattr(chat, "last_client_message_at", None)
            or chat.last_user_message_at
        )
        last_outgoing_message_at = chat.last_manager_reply_at

        unread: bool = bool(
            chat.last_message_at
            and (
                chat.last_read_at is None
                or chat.last_message_at > chat.last_read_at
            )
        )

        unanswered: bool = bool(
            not chat.is_blocked
            and not chat.is_blocked_by_user
            and last_client_message_at
            and (
                last_outgoing_message_at is None
                or last_client_message_at > last_outgoing_message_at
            )
        )

        is_red: bool = bool(
            unanswered
            and last_client_message_at
            and (now - last_client_message_at).total_seconds() / 60
            > sla_threshold_minutes
        )

        return {
            "unread": unread,
            "unanswered": unanswered,
            "is_red": is_red,
            "last_incoming_at": last_client_message_at,
            "last_outgoing_at": last_outgoing_message_at,
            "has_unanswered_incoming": unanswered,
        }

    def _chat_out(
        self,
        chat: Chat,
        sla_threshold_minutes: int,
        funnel_context: dict | None,
        *,
        latest_message: Message | None = None,
        search_hit: Message | None = None,
        search_query: str | None = None,
        tags: list[dict] | None = None,
        lead_status: dict | None = None,
        is_hot_lead: bool = False,
    ) -> ChatOut:
        flags = self._compute_flags(chat, sla_threshold_minutes)
        context = dict(funnel_context or {})
        context.pop("chat_id", None)
        context["waiting_for_answer"] = bool(context.get("waiting_for_answer"))
        context["lifecycle_status"] = self._lifecycle_status(chat, context)
        preview_context = self._message_preview_context(latest_message, prefix="last_message")
        search_context = self._message_preview_context(
            search_hit,
            prefix="search_hit",
            search_query=search_query,
        )
        return ChatOut.model_validate(chat).model_copy(
            update={
                **flags,
                **context,
                **preview_context,
                **search_context,
                "is_hot_lead": is_hot_lead,
                "tags": [ChatTagOut.model_validate(tag) for tag in tags or []],
                "lead_status": (
                    ChatLeadStatusOut.model_validate(lead_status)
                    if lead_status is not None
                    else None
                ),
            }
        )

    @classmethod
    def _message_preview_context(
        cls,
        message: Message | None,
        *,
        prefix: str,
        search_query: str | None = None,
    ) -> dict:
        if message is None:
            return {}
        text = message.body or message.caption or ""
        if prefix == "search_hit":
            return {
                "search_hit_message_id": message.id,
                "search_hit_text": cls._snippet(text, search_query),
                "search_hit_created_at": message.created_at,
                "search_hit_sender_type": message.sender_type,
            }
        return {
            "last_message_text": message.body,
            "last_message_type": message.message_type,
            "last_message_caption": message.caption,
            "last_message_sender_type": message.sender_type,
            "last_message_created_at": message.created_at,
            "last_message_file_name": message.file_name,
        }

    @staticmethod
    def _snippet(text: str, search_query: str | None, radius: int = 48) -> str:
        if not text:
            return ""
        query = (search_query or "").strip().lower()
        lowered = text.lower()
        index = lowered.find(query) if query else -1
        if index < 0:
            return text[: radius * 2].strip()
        start = max(0, index - radius)
        end = min(len(text), index + len(query) + radius)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(text) else ""
        return f"{prefix}{text[start:end].strip()}{suffix}"

    @staticmethod
    def _lifecycle_status(chat: Chat, funnel_context: dict) -> str:
        if not funnel_context.get("active_funnel_version_id"):
            return "manual"
        if funnel_context.get("is_paused"):
            return "paused"
        completed_at = funnel_context.get("completed_at")
        if completed_at is not None:
            if chat.last_user_message_at and chat.last_user_message_at > completed_at:
                return "manual"
            return "completed"
        if funnel_context.get("waiting_for_answer"):
            return "waiting_for_answer"
        if funnel_context.get("current_step_id"):
            return "in_progress"
        return "manual"

    @staticmethod
    def date_range_to_datetimes(
        date_from: date | None,
        date_to: date | None,
        *,
        timezone_offset_minutes: int = 0,
    ) -> tuple[datetime | None, datetime | None]:
        # JavaScript Date#getTimezoneOffset returns UTC - local time. Adding
        # that offset to local midnight converts the browser date boundary to
        # UTC without assuming a server-side timezone.
        utc_shift = timedelta(minutes=timezone_offset_minutes)
        start = (
            datetime.combine(date_from, time.min, tzinfo=timezone.utc) + utc_shift
            if date_from is not None
            else None
        )
        end = (
            datetime.combine(
                date_to + timedelta(days=1),
                time.min,
                tzinfo=timezone.utc,
            )
            + utc_shift
            if date_to is not None
            else None
        )
        return start, end

    @staticmethod
    def _normalize_required(value: str, *, field_name: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field_name} must not be empty",
            )
        return normalized

    @staticmethod
    def _normalize_optional(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _normalize_language_code(value: str | None) -> str | None:
        normalized = ChatService._normalize_optional(value)
        if normalized is None:
            return None
        normalized = normalized.replace("_", "-").lower()
        if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})?", normalized):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="client_lang must be a valid language code",
            )
        return normalized
