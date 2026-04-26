"""
ChatService — chat listing, filtering, sorting, and timestamp management.

Computed flags contract:
  is_red, unanswered, unread are NEVER stored in the DB.

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

Sorting order (enforced by repository):
  1. is_red DESC   — SLA breached chats always on top
  2. unanswered DESC
  3. last_message_at DESC NULLS LAST
"""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat
from app.repositories.chat_repository import ChatRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.chat import ChatCreate, ChatFilters, ChatOut


class ChatService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.chat_repo = ChatRepository(db)
        self.project_repo = ProjectRepository(db)

    # ── Public methods ─────────────────────────────────────────────────────────

    async def get_chat_list(
        self,
        project_id: UUID,
        filters: ChatFilters,
        limit: int,
        offset: int,
    ) -> tuple[list[ChatOut], int]:
        """
        Returns a paginated, filtered, and sorted list of chats together with
        the total count (for the caller to build PaginatedResponse).

        Filter semantics:
          - filters.unread / unanswered / is_red — if True, keep only matching
            chats; if None or False, no restriction on that dimension.
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

        # 3.1 Use `is True` instead of `bool()` so that None and False are both
        # treated as "no filter". bool(None) == False is incidentally the same
        # result, but `is True` makes the intent explicit and avoids accidental
        # truthy coercion of unexpected values (e.g. 0, empty string).
        filter_kwargs: dict = dict(
            project_id=project_id,
            only_unread=filters.unread is True,
            only_unanswered=filters.unanswered is True,
            only_red=filters.is_red is True,
            sla_threshold_minutes=sla,
            manager_id=filters.manager_id,
        )

        # Sequential — AsyncSession does not support concurrent operations.
        chats = await self.chat_repo.list(limit=limit, offset=offset, **filter_kwargs)
        total = await self.chat_repo.count(**filter_kwargs)

        items = [
            ChatOut.model_validate(chat).model_copy(
                update=self._compute_flags(chat, sla)
            )
            for chat in chats
        ]
        return items, total

    async def get_chat(self, chat_id: UUID, project_id: UUID) -> ChatOut:
        """Returns a single chat with computed flags populated."""
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

        flags = self._compute_flags(chat, project.sla_threshold_minutes)
        return ChatOut.model_validate(chat).model_copy(update=flags)

    async def create_chat(self, project_id: UUID, data: ChatCreate) -> ChatOut:
        raise NotImplementedError

    async def update_timestamps(
        self, chat_id: UUID, sender_type: str, ts: datetime
    ) -> None:
        """
        Called by MessageService inside the same DB transaction.
        Delegates straight to the repository — no business logic here.
        """
        await self.chat_repo.update_timestamps(chat_id, sender_type, ts)

    async def mark_as_read(self, chat_id: UUID, project_id: UUID) -> None:
        raise NotImplementedError

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

        unread: bool = bool(
            chat.last_message_at
            and (
                chat.last_read_at is None
                or chat.last_message_at > chat.last_read_at
            )
        )

        unanswered: bool = bool(
            chat.last_user_message_at
            and (
                chat.last_manager_reply_at is None
                or chat.last_user_message_at > chat.last_manager_reply_at
            )
        )

        is_red: bool = bool(
            unanswered
            and chat.last_user_message_at
            and (now - chat.last_user_message_at).total_seconds() / 60
            > sla_threshold_minutes
        )

        return {"unread": unread, "unanswered": unanswered, "is_red": is_red}
