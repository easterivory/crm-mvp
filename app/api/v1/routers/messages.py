"""Message creation, listing, upload staging, and Telegram media proxying."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.core.constants import MessageType, SenderType
from app.core.config import settings
from app.schemas.common import PaginatedResponse
from app.schemas.message import (
    MessageCreate,
    MessageOut,
    MessageTranslationPreviewOut,
    MessageTranslationPreviewRequest,
    MessageUploadOut,
)
from app.schemas.scheduled_message import ScheduledMessageOut
from app.services.message_service import MessageService
from app.services.project_snippet_service import ProjectSnippetService
from app.services.scheduled_message_service import ScheduledMessageService

router = APIRouter(prefix="/chats/{chat_id}/messages", tags=["messages"])
media_router = APIRouter(prefix="/messages", tags=["messages"])
attachments_router = APIRouter(prefix="/chats/{chat_id}/attachments", tags=["messages"])
scheduled_router = APIRouter(prefix="/chats/{chat_id}/scheduled-messages", tags=["messages"])


@router.post("", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def create_message(
    chat_id: UUID,
    request: Request,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    payload, upload = await _read_message_request(request)
    message_service = MessageService(db)
    auto_translate = _optional_bool(
        request.query_params.get("auto_translate", payload.get("auto_translate")),
        default=True,
    )

    upload_id = _optional_uuid(payload.get("upload_id"), "upload_id")
    if upload_id is not None:
        legacy_data = MessageCreate(
            message_type=str(payload.get("message_type") or payload.get("media_type") or MessageType.DOCUMENT),
            sender_type=SenderType.MANAGER,
            sender_id=current_user.id,
            operator_id=current_user.id,
            body=_optional_text(payload.get("body")),
            caption=_optional_text(payload.get("caption") or payload.get("text")),
            upload_id=upload_id,
        )
        return await message_service.create_message(
            chat_id=chat_id,
            project_id=project_id,
            data=legacy_data,
            auto_translate=auto_translate,
        )

    snippet_id = _optional_uuid(payload.get("snippet_id"), "snippet_id")
    if snippet_id is not None:
        if upload is not None:
            raise HTTPException(status_code=422, detail="snippet_id cannot be combined with file upload")
        snippet_service = ProjectSnippetService(db)
        snippet = await snippet_service.get_snippet_for_send(
            project_id=project_id,
            snippet_id=snippet_id,
            actor=current_user,
        )
        has_text_override = any(key in payload for key in ("text", "caption", "body"))
        override_text = _optional_text(payload.get("text") or payload.get("caption") or payload.get("body"))
        text = override_text if has_text_override else snippet.content
        return await message_service.send_message_to_client(
            chat_id=chat_id,
            project_id=project_id,
            operator_id=current_user.id,
            text=text,
            media_type=snippet.type,
            file_id=snippet.file_id,
            file_bytes=await snippet_service.snippet_file_bytes(snippet),
            file_name=snippet.file_name,
            mime_type=snippet.mime_type,
            original_text=_optional_text(payload.get("original_text")),
            auto_translate=auto_translate,
        )

    media_type = str(payload.get("media_type") or payload.get("message_type") or MessageType.TEXT)
    text = _optional_text(payload.get("text") or payload.get("caption") or payload.get("body"))
    original_text = _optional_text(payload.get("original_text"))
    file_id = _optional_text(payload.get("file_id") or payload.get("telegram_file_id"))
    if upload is not None:
        if file_id is not None:
            raise HTTPException(status_code=422, detail="file upload cannot be combined with file_id")
        file_bytes = await _read_upload_bytes(upload, media_type)
        return await message_service.send_message_to_client(
            chat_id=chat_id,
            project_id=project_id,
            operator_id=current_user.id,
            text=text,
            media_type=media_type,
            file_bytes=file_bytes,
            file_name=upload.filename,
            mime_type=upload.content_type,
            original_text=original_text,
            auto_translate=auto_translate,
        )

    return await message_service.send_message_to_client(
        chat_id=chat_id,
        project_id=project_id,
        operator_id=current_user.id,
        text=text,
        media_type=media_type,
        file_id=file_id,
        original_text=original_text,
        auto_translate=auto_translate,
    )


@router.post("/translate-preview", response_model=MessageTranslationPreviewOut)
async def preview_outgoing_translation(
    chat_id: UUID,
    data: MessageTranslationPreviewRequest,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageTranslationPreviewOut:
    return await MessageService(db).preview_outgoing_translation(
        chat_id=chat_id,
        project_id=project_id,
        operator_id=current_user.id,
        text=data.text,
    )


@router.post("/{message_id}/translate", response_model=MessageOut)
async def translate_message(
    chat_id: UUID,
    message_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    return await MessageService(db).translate_message_on_demand(
        chat_id=chat_id,
        project_id=project_id,
        message_id=message_id,
    )


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


@media_router.get("/{message_id}/media", response_class=StreamingResponse)
async def get_message_media(
    message_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    return await MessageService(db).media_response(
        message_id=message_id,
        project_id=project_id,
    )


@attachments_router.post("", response_model=MessageUploadOut, status_code=status.HTTP_201_CREATED)
async def upload_chat_attachment(
    chat_id: UUID,
    file: UploadFile = File(...),
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageUploadOut:
    return await MessageService(db).upload_attachment(
        chat_id=chat_id,
        project_id=project_id,
        actor=current_user,
        file=file,
    )


@scheduled_router.post("", response_model=ScheduledMessageOut, status_code=status.HTTP_201_CREATED)
async def schedule_chat_message(
    chat_id: UUID,
    request: Request,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScheduledMessageOut:
    payload, upload = await _read_message_request(request)
    raw_scheduled_at = str(payload.get("scheduled_at") or "").strip()
    try:
        scheduled_at = datetime.fromisoformat(raw_scheduled_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="scheduled_at must be an ISO datetime") from exc

    media_type = str(payload.get("media_type") or MessageType.TEXT)
    file_id = None
    file_bytes = await _read_upload_bytes(upload, media_type) if upload is not None else None
    file_name = upload.filename if upload is not None else None
    mime_type = upload.content_type if upload is not None else None
    snippet_id = _optional_uuid(payload.get("snippet_id"), "snippet_id")
    if snippet_id is not None:
        if upload is not None:
            raise HTTPException(status_code=422, detail="snippet_id cannot be combined with file upload")
        snippet = await ProjectSnippetService(db).get_snippet_for_send(
            project_id=project_id,
            snippet_id=snippet_id,
            actor=current_user,
        )
        if snippet.type == MessageType.TEXT:
            raise HTTPException(status_code=422, detail="Text snippets should be scheduled as text")
        has_text_override = any(key in payload for key in ("text", "caption", "body"))
        text_override = _optional_text(payload.get("text") or payload.get("caption") or payload.get("body"))
        media_type = snippet.type
        file_id = snippet.file_id
        file_bytes = await ProjectSnippetService(db).snippet_file_bytes(snippet)
        file_name = snippet.file_name
        mime_type = snippet.mime_type
        if not has_text_override:
            payload["text"] = snippet.content
        else:
            payload["text"] = text_override

    return await ScheduledMessageService(db).schedule_message(
        project_id=project_id,
        chat_id=chat_id,
        actor=current_user,
        scheduled_at=scheduled_at,
        text=_optional_text(payload.get("text") or payload.get("caption") or payload.get("body")),
        original_text=_optional_text(payload.get("original_text")),
        media_type=media_type,
        auto_translate=_optional_bool(payload.get("auto_translate"), default=True),
        file_id=file_id,
        file_bytes=file_bytes,
        file_name=file_name,
        mime_type=mime_type,
    )


@scheduled_router.get("", response_model=list[ScheduledMessageOut])
async def list_scheduled_chat_messages(
    chat_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ScheduledMessageOut]:
    return await ScheduledMessageService(db).list_messages(
        project_id=project_id,
        chat_id=chat_id,
        actor=current_user,
    )


@scheduled_router.delete("/{scheduled_message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_scheduled_chat_message(
    chat_id: UUID,
    scheduled_message_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await ScheduledMessageService(db).cancel_message(
        project_id=project_id,
        chat_id=chat_id,
        scheduled_message_id=scheduled_message_id,
        actor=current_user,
    )


async def _read_message_request(request: Request) -> tuple[dict, StarletteUploadFile | None]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        try:
            payload = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid JSON body") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="JSON body must be an object")
        return payload, None

    if content_type.startswith("multipart/form-data") or content_type.startswith("application/x-www-form-urlencoded"):
        form = await request.form()
        upload = form.get("file")
        if upload is not None and not isinstance(upload, StarletteUploadFile):
            raise HTTPException(status_code=422, detail="file field must be an uploaded file")
        return {key: value for key, value in form.multi_items() if key != "file"}, upload

    if not content_type:
        return {}, None
    raise HTTPException(status_code=415, detail="Unsupported message request content type")


async def _read_upload_bytes(upload: StarletteUploadFile, media_type: str) -> bytes:
    max_size = _max_direct_upload_size(media_type)
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(1024 * 1024):
        size += len(chunk)
        if size > max_size:
            raise HTTPException(status_code=413, detail="Файл слишком большой.")
        chunks.append(chunk)
    if size == 0:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")
    return b"".join(chunks)


def _max_direct_upload_size(media_type: str) -> int:
    if media_type == MessageType.PHOTO:
        return settings.CHAT_PHOTO_MAX_MB * 1024 * 1024
    if media_type in {MessageType.VIDEO, MessageType.VIDEO_NOTE}:
        return settings.CHAT_VIDEO_MAX_MB * 1024 * 1024
    return settings.CHAT_DOCUMENT_MAX_MB * 1024 * 1024


def _optional_uuid(value, field_name: str) -> UUID | None:
    if value is None or value == "":
        return None
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field_name} must be a UUID") from exc


def _optional_text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise HTTPException(status_code=422, detail="auto_translate must be a boolean")
