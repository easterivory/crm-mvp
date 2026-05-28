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
from urllib.parse import quote
from uuid import UUID

from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse
import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.core.constants import MessageType, SenderType
from app.repositories.bot_repository import BotRepository
from app.repositories.chat_repository import ChatRepository
from app.repositories.message_repository import MessageRepository
from app.schemas.message import MessageCreate, MessageOut
from app.services.chat_service import ChatService
from app.services.telegram_sender import TelegramSenderService


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

        messages = await self.message_repo.list_by_chat(
            chat_id,
            limit=limit,
            offset=offset,
            since=chat.current_cycle_started_at,
        )
        total = await self.message_repo.count_by_chat(
            chat_id,
            since=chat.current_cycle_started_at,
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
