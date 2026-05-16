"""
/api/v1/chats/{chat_id}/messages — message creation and listing.

Project-bound users receive project_id from their authenticated context.
super_admin users pass project_id as a query parameter for scoped requests.
MessageService.create_message() validates that chat_id belongs to project_id —
the router does not repeat that check.

Endpoints implemented:
  POST /chats/{chat_id}/messages — create_message

Endpoints stubbed (Phase 3):
  GET  /chats/{chat_id}/messages — list_messages
    Requires a count_by_chat() on MessageRepository for correct pagination totals.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_db
from app.schemas.common import PaginatedResponse
from app.schemas.message import MessageCreate, MessageOut
from app.services.message_service import MessageService

router = APIRouter(prefix="/chats/{chat_id}/messages", tags=["messages"])


@router.post("", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def create_message(
    chat_id: UUID,
    data: MessageCreate,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    """
    Creates a message in the given chat.

    Validates:
      - chat_id belongs to the current project (404 otherwise)
      - sender_type is one of: user, manager, system
      - message_type is one of: text, image, video, audio, file, sticker, system

    Idempotent: if external_message_id already exists for this chat, returns
    the existing record without creating a duplicate (safe for webhook retries).

    Atomically updates chat.last_message_at and the sender-specific timestamp.
    """
    return await MessageService(db).create_message(
        chat_id=chat_id,
        project_id=project_id,
        data=data,
    )


# ── Stub (Phase 3) ─────────────────────────────────────────────────────────────

@router.get("", response_model=PaginatedResponse[MessageOut])
async def list_messages(
    chat_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[MessageOut]:
    items, total = await MessageService(db).list_messages(
        chat_id=chat_id,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)
