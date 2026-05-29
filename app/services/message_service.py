"""
MessageService — writes messages and keeps chat timestamp fields in sync.

Transaction contract:
  Both the message INSERT and the chat UPDATE execute in the caller's
  DB session. get_db() issues a single commit at the end of the request.

Idempotency (race-condition safe):
  1. Pre-check: if external_message_id already exists, return immediately.
  2. Insert inside a SAVEPOINT (begin_nested). If a concurrent request
     inserted the same external_message_id between our check and our INSERT,
     the SAVEPOINT is rolled back (not the outer transaction) and we
     re-fetch the existing record. This handles the duplicate-webhook case
     without aborting the entire request transaction.

Security:
  create_message() verifies that chat_id belongs to project_id before any
  write. A client that passes an arbitrary chat_id from another project is
  rejected with 404.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import MessageType, SenderType
from app.models.message import MessageUpload
from app.models.user import User
from app.repositories.bot_repository import BotRepository
from app.repositories.chat_repository import ChatRepository
from app.repositories.message_repository import MessageRepository
from app.schemas.message import MessageCreate, MessageOut, MessageUploadOut
from app.services.chat_service import ChatService
from app.services.telegram_sender import TelegramSenderService

logger = logging.getLogger(__name__)

MESSAGE_CYCLE_START_TOLERANCE = timedelta(seconds=1)

ALLOWED_CHAT_MEDIA: dict[str, str] = {
    "image/jpeg": MessageType.PHOTO,
    "image/png": MessageType.PHOTO,
    "image/webp": MessageType.PHOTO,
    "video/mp4": MessageType.VIDEO,
    "video/quicktime": MessageType.VIDEO,
    "application/pdf": MessageType.DOCUMENT,
    "text/plain": MessageType.DOCUMENT,
    "application/msword": MessageType.DOCUMENT,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": MessageType.DOCUMENT,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": MessageType.DOCUMENT,
    "application/zip": MessageType.DOCUMENT,
}

DANGEROUS_EXTENSIONS = {
    ".exe",
    ".bat",
    ".cmd",
    ".com",
    ".scr",
    ".js",
    ".jar",
    ".sh",
    ".php",
    ".py",
}


class MessageService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.message_repo = MessageRepository(db)
        self.chat_repo = ChatRepository(db)
        self.bot_repo = BotRepository(db)
        self.chat_service = ChatService(db)
        self.telegram_sender = TelegramSenderService(db)

    async def create_message(
        self,
        chat_id: UUID,
        project_id: UUID,
        data: MessageCreate,
        *,
        send_to_telegram: bool = True,
    ) -> MessageOut:
        """
        Atomically (within one DB transaction):
          1. Validate sender_type / message_type.
          2. Verify chat belongs to project_id.
          3. Return existing record if external_message_id is a duplicate.
          4. INSERT message row inside a SAVEPOINT.
          5. UPDATE chat timestamp fields.
        """
        # ── Validation ────────────────────────────────────────────────────────
        if data.sender_type not in SenderType.ALL:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Invalid sender_type '{data.sender_type}'. "
                    f"Allowed: {sorted(SenderType.ALL)}"
                ),
            )
        if data.message_type not in MessageType.ALL:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Invalid message_type '{data.message_type}'. "
                    f"Allowed: {sorted(MessageType.ALL)}"
                ),
            )

        # ── 1.1 Verify chat belongs to this project ───────────────────────────
        chat = await self.chat_repo.get_active(chat_id, project_id)
        if chat is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found in this project",
            )

        # ── Pre-check idempotency ─────────────────────────────────────────────
        if data.external_message_id is not None:
            existing = await self.message_repo.get_by_external_id(
                chat_id, data.external_message_id
            )
            if existing is not None:
                if data.sender_type == SenderType.MANAGER:
                    await self.bot_repo.disable_bot_for_chat(chat_id)
                return MessageOut.model_validate(existing)

        upload_id_for_sent_mark = data.upload_id
        if send_to_telegram and self._is_outgoing_media_upload(data):
            data = await self._send_media_upload_to_telegram(
                project_id=project_id,
                chat=chat,
                data=data,
            )

        # ── 1.2 Insert inside SAVEPOINT — race-condition safe idempotency ─────
        # If a concurrent request inserted the same external_message_id between
        # our pre-check and this INSERT, the partial UNIQUE index fires and raises
        # IntegrityError. Rolling back only the SAVEPOINT (not the outer
        # transaction) lets us re-fetch the winner's record and return it.
        message = None
        try:
            async with self.db.begin_nested():
                message = await self.message_repo.create(
                    chat_id=chat_id,
                    external_message_id=data.external_message_id,
                    message_type=data.message_type,
                    sender_type=data.sender_type,
                    sender_id=data.sender_id,
                    body=data.body,
                    caption=data.caption,
                    telegram_file_id=data.telegram_file_id,
                    file_unique_id=data.file_unique_id,
                    file_name=data.file_name,
                    mime_type=data.mime_type,
                    file_size=data.file_size,
                    media_group_id=data.media_group_id,
                    raw_payload_json=data.raw_payload_json,
                )
        except IntegrityError:
            # SAVEPOINT was rolled back. Re-fetch the row that caused the conflict.
            logger.warning(
                "Duplicate message detected — concurrent insert for "
                "chat_id=%s external_message_id=%s. Returning existing record.",
                chat_id,
                data.external_message_id,
            )
            if data.external_message_id is not None:
                existing = await self.message_repo.get_by_external_id(
                    chat_id, data.external_message_id
                )
                if existing is not None:
                    if data.sender_type == SenderType.MANAGER:
                        await self.bot_repo.disable_bot_for_chat(chat_id)
                    return MessageOut.model_validate(existing)
            # If we cannot find the conflicting row (should not happen), re-raise.
            raise

        # ── Update chat timestamps ─────────────────────────────────────────────
        # Use the DB-assigned created_at so chat timestamps are always consistent
        # with what is stored, regardless of application-server clock skew.
        await self.chat_service.update_timestamps(
            chat_id, data.sender_type, message.created_at
        )

        if upload_id_for_sent_mark is not None and self._is_outgoing_media_type(data.message_type):
            await self.message_repo.mark_upload_sent(upload_id_for_sent_mark, project_id, message.id)

        if data.sender_type == SenderType.MANAGER:
            await self.bot_repo.disable_bot_for_chat(chat_id)

        if send_to_telegram:
            await self._send_to_telegram_if_needed(
                project_id=project_id,
                bot_id=chat.bot_id,
                external_chat_id=chat.external_chat_id,
                data=data,
            )

        return MessageOut.model_validate(message)

    async def upload_attachment(
        self,
        *,
        chat_id: UUID,
        project_id: UUID,
        actor: User,
        file: UploadFile,
    ) -> MessageUploadOut:
        chat = await self.chat_repo.get_active(chat_id, project_id)
        if chat is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found in this project")

        file_name = os.path.basename(file.filename or "attachment")
        suffix = Path(file_name).suffix.lower()
        if suffix in DANGEROUS_EXTENSIONS:
            raise HTTPException(status_code=422, detail="Этот тип файла нельзя отправлять.")

        mime_type = file.content_type or "application/octet-stream"
        media_type = ALLOWED_CHAT_MEDIA.get(mime_type)
        if media_type is None:
            raise HTTPException(status_code=422, detail="Неподдерживаемый тип файла.")

        max_size = self._max_upload_size(media_type)
        storage_root = Path(settings.CHAT_ATTACHMENT_STORAGE_PATH)
        storage_root.mkdir(parents=True, exist_ok=True)
        project_dir = storage_root / str(project_id) / str(chat_id)
        project_dir.mkdir(parents=True, exist_ok=True)

        temp_path = project_dir / f"tmp_{uuid4().hex}{suffix or '.bin'}"
        upload_id: UUID | None = None
        size = 0
        try:
            with temp_path.open("wb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_size:
                        raise HTTPException(status_code=413, detail="Файл слишком большой.")
                    output.write(chunk)

            expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.CHAT_ATTACHMENT_TTL_HOURS)
            upload = await self.message_repo.create_upload(
                project_id=project_id,
                chat_id=chat_id,
                created_by_user_id=actor.id,
                file_name=file_name,
                mime_type=mime_type,
                file_size=size,
                media_type=media_type,
                storage_path="",
                expires_at=expires_at,
            )
            upload_id = upload.id
            final_path = project_dir / f"{upload.id.hex}{suffix or '.bin'}"
            temp_path.replace(final_path)
            upload = await self.message_repo.update_upload_path(upload.id, project_id, str(final_path))
            assert upload is not None
            return MessageUploadOut(
                upload_id=upload.id,
                chat_id=upload.chat_id,
                project_id=upload.project_id,
                file_name=upload.file_name,
                mime_type=upload.mime_type,
                file_size=upload.file_size,
                media_type=upload.media_type,
                status=upload.status,
                expires_at=upload.expires_at,
            )
        finally:
            if upload_id is None and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    async def cleanup_expired_uploads(self) -> int:
        uploads = await self.message_repo.mark_expired_uploads(datetime.now(timezone.utc))
        removed = 0
        for upload in uploads:
            try:
                path = Path(upload.storage_path)
                if path.exists():
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        return removed

    async def _send_to_telegram_if_needed(
        self,
        *,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
        data: MessageCreate,
    ) -> None:
        if data.sender_type not in {SenderType.MANAGER, SenderType.BOT}:
            return
        if data.message_type != MessageType.TEXT:
            return
        if data.body is None:
            return

        await self.telegram_sender.send_message(
            project_id=project_id,
            bot_id=bot_id,
            external_chat_id=external_chat_id,
            text=data.body,
            reply_markup=data.reply_markup,
        )

    async def _send_media_upload_to_telegram(
        self,
        *,
        project_id: UUID,
        chat,
        data: MessageCreate,
    ) -> MessageCreate:
        assert data.upload_id is not None
        if chat.bot_id is None:
            raise HTTPException(status_code=422, detail="У чата не настроен бот для отправки.")

        upload = await self.message_repo.get_upload_for_send(
            upload_id=data.upload_id,
            chat_id=chat.id,
            project_id=project_id,
        )
        if upload is None:
            raise HTTPException(status_code=404, detail="Вложение не найдено или уже отправлено.")
        if upload.expires_at is not None and upload.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=422, detail="Вложение устарело. Загрузите файл заново.")
        if upload.media_type != self._normalize_outgoing_media_type(data.message_type):
            raise HTTPException(status_code=422, detail="Тип вложения не совпадает с типом сообщения.")
        path = Path(upload.storage_path)
        if not upload.storage_path or not path.exists():
            raise HTTPException(status_code=404, detail="Файл вложения не найден в private storage.")

        caption = data.caption or data.body
        result = await self._send_upload_by_type(
            upload=upload,
            path=path,
            project_id=project_id,
            bot_id=chat.bot_id,
            external_chat_id=chat.external_chat_id,
            caption=caption,
        )
        if result is None:
            await self.message_repo.mark_upload_failed(upload.id, project_id)
            raise HTTPException(status_code=502, detail="Telegram не принял медиа-сообщение.")

        telegram_file_id, file_unique_id, file_size = self._extract_telegram_media_metadata(
            upload.media_type,
            result,
        )
        return data.model_copy(
            update={
                "message_type": upload.media_type,
                "body": None,
                "caption": caption,
                "telegram_file_id": telegram_file_id,
                "file_unique_id": file_unique_id,
                "file_name": upload.file_name,
                "mime_type": upload.mime_type,
                "file_size": file_size or upload.file_size,
                "raw_payload_json": {
                    "telegram_result": result,
                    "upload_id": str(upload.id),
                },
            }
        )

    async def _send_upload_by_type(
        self,
        *,
        upload: MessageUpload,
        path: Path,
        project_id: UUID,
        bot_id: UUID,
        external_chat_id: str,
        caption: str | None,
    ) -> dict | None:
        if upload.media_type == MessageType.PHOTO:
            return await self.telegram_sender.send_photo(
                project_id=project_id,
                bot_id=bot_id,
                external_chat_id=external_chat_id,
                photo=path,
                caption=caption,
                file_name=upload.file_name,
                mime_type=upload.mime_type,
            )
        if upload.media_type == MessageType.VIDEO:
            return await self.telegram_sender.send_video(
                project_id=project_id,
                bot_id=bot_id,
                external_chat_id=external_chat_id,
                video=path,
                caption=caption,
                file_name=upload.file_name,
                mime_type=upload.mime_type,
            )
        return await self.telegram_sender.send_document(
            project_id=project_id,
            bot_id=bot_id,
            external_chat_id=external_chat_id,
            document=path,
            caption=caption,
            file_name=upload.file_name,
            mime_type=upload.mime_type,
        )

    @staticmethod
    def _is_outgoing_media_upload(data: MessageCreate) -> bool:
        return (
            data.upload_id is not None
            and data.sender_type in {SenderType.MANAGER, SenderType.BOT}
            and MessageService._is_outgoing_media_type(data.message_type)
        )

    @staticmethod
    def _is_outgoing_media_type(message_type: str) -> bool:
        return MessageService._normalize_outgoing_media_type(message_type) in {
            MessageType.PHOTO,
            MessageType.VIDEO,
            MessageType.DOCUMENT,
        }

    @staticmethod
    def _normalize_outgoing_media_type(message_type: str) -> str:
        return MessageType.DOCUMENT if message_type == MessageType.FILE else message_type

    @staticmethod
    def _extract_telegram_media_metadata(
        message_type: str,
        result: dict,
    ) -> tuple[str | None, str | None, int | None]:
        payload = None
        if message_type == MessageType.PHOTO:
            photos = result.get("photo")
            if isinstance(photos, list) and photos:
                payload = photos[-1]
        else:
            candidate = result.get(message_type)
            if isinstance(candidate, dict):
                payload = candidate
        if not isinstance(payload, dict):
            return None, None, None
        file_size = payload.get("file_size")
        return (
            payload.get("file_id"),
            payload.get("file_unique_id"),
            int(file_size) if isinstance(file_size, int) else None,
        )

    @staticmethod
    def _max_upload_size(media_type: str) -> int:
        if media_type == MessageType.PHOTO:
            return settings.CHAT_PHOTO_MAX_MB * 1024 * 1024
        if media_type == MessageType.VIDEO:
            return settings.CHAT_VIDEO_MAX_MB * 1024 * 1024
        return settings.CHAT_DOCUMENT_MAX_MB * 1024 * 1024

    async def list_messages(
        self,
        chat_id: UUID,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[MessageOut], int]:
        """
        Returns messages for a chat in chronological order (oldest first).
        Verifies that chat_id belongs to the current project before reading.
        """
        chat = await self.chat_repo.get_active(chat_id, project_id)
        if chat is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found in this project",
            )

        since = (
            chat.current_cycle_started_at - MESSAGE_CYCLE_START_TOLERANCE
            if chat.current_cycle_started_at is not None
            else None
        )
        messages = await self.message_repo.list_by_chat(
            chat_id,
            limit=limit,
            offset=offset,
            since=since,
        )
        total = await self.message_repo.count_by_chat(
            chat_id,
            since=since,
        )
        return [MessageOut.model_validate(m) for m in messages], total

    async def media_response(self, message_id: UUID, project_id: UUID) -> StreamingResponse:
        message = await self.message_repo.get_by_id_in_project(message_id, project_id)
        if message is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found",
            )
        if not message.telegram_file_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message has no Telegram media file",
            )

        chat = await self.chat_repo.get_active(message.chat_id, project_id)
        if chat is None or chat.bot_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found in this project",
            )

        token = await self.bot_repo.get_bot_token_by_id(chat.bot_id, project_id)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Bot token is not configured",
            )

        try:
            file_info = await self.telegram_sender.get_file(token, message.telegram_file_id)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Telegram getFile request failed: {exc}",
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

        file_path = file_info.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Telegram getFile response did not include file_path",
            )

        media_type = self._media_content_type(message.message_type, message.mime_type)
        file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        headers = {
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": self._content_disposition(message.message_type, message.file_name),
        }
        return StreamingResponse(
            self._iter_telegram_file(file_url),
            media_type=media_type,
            headers=headers,
        )

    @staticmethod
    async def _iter_telegram_file(file_url: str):
        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream("GET", file_url) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk

    @staticmethod
    def _media_content_type(message_type: str, mime_type: str | None) -> str:
        if mime_type:
            return mime_type
        if message_type in {MessageType.PHOTO, MessageType.IMAGE, MessageType.STICKER}:
            return "image/jpeg"
        if message_type == MessageType.VIDEO:
            return "video/mp4"
        if message_type == MessageType.VOICE:
            return "audio/ogg"
        if message_type == MessageType.AUDIO:
            return "audio/mpeg"
        return "application/octet-stream"

    @staticmethod
    def _content_disposition(message_type: str, file_name: str | None) -> str:
        disposition = "attachment" if message_type == MessageType.DOCUMENT else "inline"
        if not file_name:
            return disposition
        return f"{disposition}; filename*=UTF-8''{quote(file_name)}"
