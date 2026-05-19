"""
/api/v1/chats — chat listing and retrieval.

Project-bound users receive project_id from their authenticated context.
super_admin users pass project_id as a query parameter for scoped requests.

Endpoints implemented:
  GET  /chats              — list_chats  (filtered, paginated)
  GET  /chats/{chat_id}    — get_chat

Endpoints stubbed (Phase 3):
  POST /chats              — create_chat
  POST /chats/{chat_id}/read — mark_as_read
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.schemas.chat import ChatCreate, ChatFilters, ChatOut
from app.schemas.common import PaginatedResponse
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("", response_model=PaginatedResponse[ChatOut])
async def list_chats(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    unread: Optional[bool] = Query(default=None),
    unanswered: Optional[bool] = Query(default=None),
    is_red: Optional[bool] = Query(default=None),
    manager_id: Optional[UUID] = Query(default=None),
    bot_id: Optional[UUID] = Query(default=None),
    bot_ids: Optional[str] = Query(default=None),
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ChatOut]:
    """
    Returns a paginated list of chats for the current project.

    Filters (all optional, additive):
      - unread=true      — only chats with unread messages
      - unanswered=true  — only chats waiting for a manager reply
      - is_red=true      — only chats that breached the SLA threshold
      - manager_id=<uuid> — only chats whose lead is assigned to this manager
      - bot_id=<uuid>    — only chats for one bot
      - bot_ids=<csv>    — only chats for multiple bots

    Sort order (fixed): is_red DESC → unanswered DESC → last_message_at DESC
    """
    filters = ChatFilters(
        unread=unread,
        unanswered=unanswered,
        is_red=is_red,
        manager_id=manager_id,
        bot_id=bot_id,
        bot_ids=_parse_bot_ids(bot_ids),
    )
    items, total = await ChatService(db).get_chat_list(
        project_id=project_id,
        filters=filters,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


def _parse_bot_ids(value: Optional[str]) -> list[UUID]:
    if not value:
        return []

    ids: list[UUID] = []
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        try:
            ids.append(UUID(item))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="bot_ids must be a comma-separated list of UUIDs",
            ) from exc
    return ids


@router.get("/{chat_id}", response_model=ChatOut)
async def get_chat(
    chat_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> ChatOut:
    """Returns a single chat with computed flags (unread, unanswered, is_red)."""
    return await ChatService(db).get_chat(chat_id=chat_id, project_id=project_id)


# ── Stubs (Phase 3) ────────────────────────────────────────────────────────────

@router.post("", response_model=ChatOut, status_code=status.HTTP_201_CREATED)
async def create_chat(
    data: ChatCreate,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> ChatOut:
    return await ChatService(db).create_chat(project_id=project_id, data=data)


@router.post("/{chat_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_as_read(
    chat_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Sets last_read_at = now(). Clears the computed unread flag."""
    await ChatService(db).mark_as_read(chat_id=chat_id, project_id=project_id)


@router.post("/{chat_id}/reset", response_model=ChatOut)
async def reset_chat(
    chat_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatOut:
    """Soft-clears the active dialog cycle without deleting Telegram history."""
    return await ChatService(db).reset_chat(
        chat_id=chat_id,
        project_id=project_id,
        actor_id=current_user.id,
    )
