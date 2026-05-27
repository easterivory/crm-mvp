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
from datetime import date
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
    has_unanswered_incoming: Optional[bool] = Query(default=None),
    is_red: Optional[bool] = Query(default=None),
    manager_id: Optional[UUID] = Query(default=None),
    assigned_user_id: Optional[UUID] = Query(default=None),
    unassigned: Optional[bool] = Query(default=None),
    bot_id: Optional[UUID] = Query(default=None),
    bot_ids: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=255),
    tracking_link_id: Optional[UUID] = Query(default=None),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    tag_ids: Optional[str] = Query(default=None),
    tag_mode: str = Query(default="any", pattern="^(any|all)$"),
    lead_statuses: Optional[str] = Query(default=None),
    funnel_state: Optional[str] = Query(
        default=None,
        pattern="^(in_funnel|waiting_for_answer|completed|manual)$",
    ),
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
      - assigned_user_id=<uuid> — same as manager_id, preferred frontend name
      - unassigned=true — only chats without manager
      - bot_id=<uuid>    — only chats for one bot
      - bot_ids=<csv>    — only chats for multiple bots
      - q=<text>         — search lead/chat/tracking/message fields
      - tracking_link_id=<uuid> — only chats attributed to a link
      - date_from/date_to — filter by current_cycle_started_at, fallback created_at
      - tag_ids=<csv>    — only chats whose lead has selected tags
      - tag_mode=any|all — tag matching mode
      - lead_statuses=<csv> — only chats whose lead status code matches
      - funnel_state=in_funnel|waiting_for_answer|completed|manual

    Sort order (fixed): is_red DESC → unanswered DESC → last_message_at DESC
    """
    date_from_dt, date_to_dt = ChatService.date_range_to_datetimes(date_from, date_to)
    filters = ChatFilters(
        q=q,
        unread=unread,
        unanswered=unanswered,
        has_unanswered_incoming=has_unanswered_incoming,
        is_red=is_red,
        manager_id=manager_id,
        assigned_user_id=assigned_user_id,
        unassigned=unassigned,
        bot_id=bot_id,
        bot_ids=_parse_bot_ids(bot_ids),
        tracking_link_id=tracking_link_id,
        date_from=date_from_dt,
        date_to=date_to_dt,
        tag_ids=_parse_uuid_csv(tag_ids, "tag_ids"),
        tag_mode=tag_mode,
        lead_statuses=_parse_string_csv(lead_statuses),
        funnel_state=funnel_state,
    )
    items, total = await ChatService(db).get_chat_list(
        project_id=project_id,
        filters=filters,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


def _parse_bot_ids(value: Optional[str]) -> list[UUID]:
    return _parse_uuid_csv(value, "bot_ids")


def _parse_uuid_csv(value: Optional[str], field_name: str) -> list[UUID]:
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
                detail=f"{field_name} must be a comma-separated list of UUIDs",
            ) from exc
    return ids


def _parse_string_csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


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
