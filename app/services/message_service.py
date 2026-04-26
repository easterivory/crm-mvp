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
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.core.constants import MessageType, SenderType
from app.repositories.chat_repository import ChatRepository
from app.repositories.message_repository import MessageRepository
from app.schemas.message import MessageCreate, MessageOut
from app.services.chat_service import ChatService


class MessageService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.message_repo = MessageRepository(db)
        self.chat_repo = ChatRepository(db)
        self.chat_service = ChatService(db)

    async def create_message(
        self,
        chat_id: UUID,
        project_id: UUID,
        data: MessageCreate,
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
                    return MessageOut.model_validate(existing)
            # If we cannot find the conflicting row (should not happen), re-raise.
            raise

        # ── Update chat timestamps ─────────────────────────────────────────────
        # Use the DB-assigned created_at so chat timestamps are always consistent
        # with what is stored, regardless of application-server clock skew.
        await self.chat_service.update_timestamps(
            chat_id, data.sender_type, message.created_at
        )

        return MessageOut.model_validate(message)

    async def list_messages(
        self,
        chat_id: UUID,
        limit: int,
        offset: int,
    ) -> list[MessageOut]:
        """
        Returns messages for a chat in chronological order (oldest first).
        Caller is responsible for verifying that chat_id belongs to the
        current project before calling this method.
        """
        messages = await self.message_repo.list_by_chat(
            chat_id, limit=limit, offset=offset
        )
        return [MessageOut.model_validate(m) for m in messages]
