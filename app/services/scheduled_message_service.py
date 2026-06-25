from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import MessageType, RoleName
from app.models.scheduled_message import ScheduledMessage
from app.models.user import User
from app.repositories.chat_repository import ChatRepository
from app.repositories.scheduled_message_repository import ScheduledMessageRepository
from app.schemas.scheduled_message import ScheduledMessageOut
from app.services.access_control import require_project_access
from app.services.message_service import MessageService


class ScheduledMessageService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ScheduledMessageRepository(db)
        self.chat_repo = ChatRepository(db)
        self.message_service = MessageService(db)

    async def schedule_message(
        self,
        *,
        project_id: UUID,
        chat_id: UUID,
        actor: User,
        scheduled_at: datetime,
        text: str | None,
        original_text: str | None,
        media_type: str,
        auto_translate: bool,
        file_id: str | None = None,
        file_bytes: bytes | None = None,
        file_name: str | None = None,
        mime_type: str | None = None,
    ) -> ScheduledMessageOut:
        await self.message_service._ensure_operator_can_send(actor.id, project_id)
        chat = await self.chat_repo.get_active(chat_id, project_id)
        if chat is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found in this project")
        if scheduled_at.tzinfo is None or scheduled_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=422, detail="scheduled_at must be in the future")

        normalized_type = self.message_service._normalize_outgoing_media_type(media_type)
        if normalized_type not in self.message_service._operator_send_media_types() | {MessageType.TEXT}:
            raise HTTPException(status_code=422, detail="Unsupported scheduled media type")
        normalized_text = (text or "").strip() or None
        normalized_original_text = (original_text or "").strip() or None
        if normalized_type == MessageType.TEXT and not normalized_text:
            raise HTTPException(status_code=422, detail="Text message cannot be empty")
        if normalized_type != MessageType.TEXT and not file_id and not file_bytes:
            raise HTTPException(status_code=422, detail="Media message requires an attachment")
        if file_id and file_bytes:
            raise HTTPException(status_code=422, detail="Media message cannot include both file_id and file bytes")

        storage_path: str | None = None
        safe_file_name = os.path.basename(file_name or "attachment")
        if file_bytes is not None:
            max_size = self._max_media_size(normalized_type)
            if len(file_bytes) > max_size:
                raise HTTPException(status_code=413, detail="Файл слишком большой.")
            storage_dir = Path(settings.CHAT_ATTACHMENT_STORAGE_PATH) / str(project_id) / "scheduled"
            storage_dir.mkdir(parents=True, exist_ok=True)
            path = storage_dir / f"{uuid4().hex}{Path(safe_file_name).suffix or '.bin'}"
            path.write_bytes(file_bytes)
            storage_path = str(path)

        try:
            scheduled = await self.repo.create_scheduled_message(
                project_id=project_id,
                chat_id=chat_id,
                created_by_user_id=actor.id,
                scheduled_at=scheduled_at,
                text=normalized_text,
                original_text=normalized_original_text,
                media_type=normalized_type,
                file_id=file_id,
                storage_path=storage_path,
                file_name=safe_file_name if file_bytes is not None else None,
                mime_type=(mime_type or "application/octet-stream") if file_bytes is not None else None,
                file_size=len(file_bytes) if file_bytes is not None else None,
                auto_translate=auto_translate,
            )
        except Exception:
            if storage_path:
                Path(storage_path).unlink(missing_ok=True)
            raise
        return ScheduledMessageOut.model_validate(scheduled)

    async def list_messages(
        self,
        *,
        project_id: UUID,
        chat_id: UUID,
        actor: User,
    ) -> list[ScheduledMessageOut]:
        require_project_access(actor, project_id)
        return [
            ScheduledMessageOut.model_validate(item)
            for item in await self.repo.list_for_chat(chat_id, project_id)
        ]

    async def cancel_message(
        self,
        *,
        project_id: UUID,
        chat_id: UUID,
        scheduled_message_id: UUID,
        actor: User,
    ) -> None:
        item = await self.repo.get_in_project(scheduled_message_id, project_id)
        if item is None or item.chat_id != chat_id:
            raise HTTPException(status_code=404, detail="Scheduled message not found")
        await self.message_service._ensure_operator_can_send(actor.id, project_id)
        if actor.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN} and item.created_by_user_id != actor.id:
            raise HTTPException(status_code=403, detail="You can cancel only your scheduled messages")
        if not await self.repo.cancel(item.id, project_id):
            raise HTTPException(status_code=422, detail="Scheduled message cannot be cancelled")
        if item.storage_path:
            Path(item.storage_path).unlink(missing_ok=True)

    async def process_due_messages(self, *, limit: int = 100) -> int:
        processed = 0
        for item in await self.repo.list_due(datetime.now(timezone.utc), limit=limit):
            await self.repo.mark_running(item.id)
            try:
                file_bytes = Path(item.storage_path).read_bytes() if item.storage_path else None
                sent = await self.message_service.send_message_to_client(
                    chat_id=item.chat_id,
                    project_id=item.project_id,
                    operator_id=item.created_by_user_id,
                    text=item.text,
                    media_type=item.media_type,
                    file_id=item.file_id,
                    file_bytes=file_bytes,
                    file_name=item.file_name,
                    mime_type=item.mime_type,
                    original_text=item.original_text,
                    auto_translate=item.auto_translate,
                )
            except Exception as exc:
                await self.repo.mark_failed(item.id, str(exc))
                continue

            await self.repo.mark_sent(item.id, sent.id)
            if item.storage_path:
                Path(item.storage_path).unlink(missing_ok=True)
            processed += 1
        return processed

    @staticmethod
    def _max_media_size(media_type: str) -> int:
        if media_type == MessageType.PHOTO:
            return settings.CHAT_PHOTO_MAX_MB * 1024 * 1024
        if media_type in {MessageType.VIDEO, MessageType.VIDEO_NOTE}:
            return settings.CHAT_VIDEO_MAX_MB * 1024 * 1024
        return settings.CHAT_DOCUMENT_MAX_MB * 1024 * 1024
