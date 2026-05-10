"""
TelegramService — processes incoming Telegram webhook updates.

Responsibilities:
  1. parse_update()     — validate raw payload into TelegramUpdate.
  2. extract_message()  — pull the TelegramMessage out (None for non-message updates).
  3. handle_update()    — orchestrate chat/lead creation and message persistence.

Design constraints (enforced throughout):
  - No replies to the Telegram user.
  - No GPT / AI processing.
  - No bulk sends / broadcasts.
  - No alert / stats business logic.
  - project_id is ALWAYS taken from TELEGRAM_PROJECT_ID env var, never from
    the incoming payload.

Idempotency / race-condition safety:
  - Chat find-or-create uses a SAVEPOINT (begin_nested). If two concurrent
    webhook deliveries for the same chat arrive simultaneously, only one
    INSERT wins; the loser catches IntegrityError, rolls back the savepoint,
    and re-fetches the winner's row.
  - Lead find-or-create uses the same pattern. A debug log is emitted on
    the conflict path (not a warning — it is an expected concurrent race, not
    a data error).
  - Message creation is delegated to MessageService.create_message(), which
    already contains its own SAVEPOINT + idempotency logic.

Error handling:
  - If TELEGRAM_PROJECT_ID is not set, the update is logged and silently
    discarded. Returning without raising ensures the webhook endpoint can
    still return 200 to Telegram (preventing retries for a misconfiguration
    that affects every request equally).
  - All unexpected exceptions propagate to the caller (the router), which
    logs them and returns 200 to Telegram anyway (Telegram must not retry).
"""
import logging
from typing import Optional
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AuditAction, EntityType, LeadStatusCode, MessageType, SenderType
from app.models.chat import Chat
from app.repositories.chat_repository import ChatRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.tracking_repository import TrackingRepository
from app.schemas.message import MessageCreate, MessageOut
from app.schemas.telegram import TelegramMessage, TelegramUpdate
from app.services.audit_service import AuditService
from app.services.bot_engine_service import BotEngineService
from app.services.message_service import MessageService

logger = logging.getLogger(__name__)


class TelegramService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.chat_repo = ChatRepository(db)
        self.lead_repo = LeadRepository(db)
        self.tracking_repo = TrackingRepository(db)
        self.message_service = MessageService(db)
        self.bot_engine = BotEngineService(db)
        self.audit = AuditService(db)

    # ── Parsing ────────────────────────────────────────────────────────────────

    @staticmethod
    def parse_update(payload: dict) -> Optional[TelegramUpdate]:
        """
        Validate raw JSON payload into a TelegramUpdate.

        Returns None on validation error — the caller should treat this as a
        malformed request (400). We return None instead of raising so the
        router can decide the HTTP status code.
        """
        try:
            return TelegramUpdate.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Malformed Telegram payload: %s", exc)
            return None

    @staticmethod
    def extract_message(update: TelegramUpdate) -> Optional[TelegramMessage]:
        """
        Return the message field from the update, or None if this update
        type does not contain a message (e.g. edited_message, callback_query).
        """
        return update.message

    # ── Orchestration ──────────────────────────────────────────────────────────

    async def handle_update(self, update: TelegramUpdate, project_id: UUID) -> None:
        """
        Entry point for processing a single Telegram update.

        Steps:
          1. Ignore non-message updates silently.
          2. Find or create the Chat row for this external_chat_id.
          3. Call MessageService.create_message() to persist the message.
          4. Find or create the Lead row for this chat.

        All writes happen in the caller's transaction; the caller (router)
        owns the commit.
        """
        message = self.extract_message(update)
        if message is None:
            logger.debug(
                "update_id=%s: not a message update — skipping",
                update.update_id,
            )
            return

        tracking_link_id = await self._resolve_tracking_link_id(message, project_id)
        chat, was_created = await self._find_or_create_chat(
            message,
            project_id,
            tracking_link_id=tracking_link_id,
        )
        msg = await self._create_message(chat.id, project_id, message)
        await self._find_or_create_lead(chat.id, project_id, message)
        if was_created:
            await self.bot_engine.initialize_chat(chat.id, project_id)
        else:
            await self.bot_engine.process_chat(chat.id, user_message=msg)

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _find_or_create_chat(
        self,
        message: TelegramMessage,
        project_id: UUID,
        tracking_link_id: Optional[UUID] = None,
    ) -> tuple[Chat, bool]:
        """
        Return the Chat for this external_chat_id, creating it if absent.

        SAVEPOINT pattern: INSERT inside begin_nested() so that an
        IntegrityError from a concurrent insert rolls back only the savepoint,
        not the outer transaction. The loser then re-fetches the winner's row.
        """
        external_chat_id = str(message.chat.id)
        external_user_id = str(message.from_user.id) if message.from_user else external_chat_id

        # Fast path: chat already exists
        chat = await self.chat_repo.get_by_external(project_id, external_chat_id)
        if chat is not None:
            return chat, False

        # Build a human-readable contact name from available sender fields
        contact_name: Optional[str] = None
        if message.from_user:
            parts = [
                p
                for p in [
                    message.from_user.first_name,
                    f"@{message.from_user.username}" if message.from_user.username else None,
                ]
                if p
            ]
            contact_name = " ".join(parts) or None

        try:
            async with self.db.begin_nested():
                chat = await self.chat_repo.create(
                    project_id=project_id,
                    tracking_link_id=tracking_link_id,
                    external_chat_id=external_chat_id,
                    external_user_id=external_user_id,
                    contact_name=contact_name,
                )
            logger.info(
                "Created chat id=%s external_chat_id=%s project_id=%s",
                chat.id,
                external_chat_id,
                project_id,
            )
        except IntegrityError:
            # Concurrent insert won the race — re-fetch the winner's row.
            logger.debug(
                "Concurrent chat create for external_chat_id=%s project_id=%s — re-fetching",
                external_chat_id,
                project_id,
            )
            chat = await self.chat_repo.get_by_external(project_id, external_chat_id)
            if chat is None:
                # Should never happen: IntegrityError means the row exists.
                raise RuntimeError(
                    f"Chat row missing after IntegrityError for "
                    f"external_chat_id={external_chat_id}"
                )
            return chat, False

        return chat, True

    async def _resolve_tracking_link_id(
        self,
        message: TelegramMessage,
        project_id: UUID,
    ) -> Optional[UUID]:
        ref_code = self._extract_start_ref_code(message.text)
        if ref_code is None:
            return None

        link = await self.tracking_repo.get_by_ref_code(ref_code, project_id)
        if link is None:
            logger.info(
                "Telegram /start ref_code=%s was not found for project_id=%s",
                ref_code,
                project_id,
            )
            return None
        return link.id

    @staticmethod
    def _extract_start_ref_code(text: Optional[str]) -> Optional[str]:
        if not text:
            return None

        parts = text.strip().split(maxsplit=1)
        if not parts:
            return None

        command = parts[0]
        if command != "/start" and not command.startswith("/start@"):
            return None
        if len(parts) == 1:
            return None

        ref_code = parts[1].strip().split(maxsplit=1)[0]
        return ref_code or None

    async def _create_message(
        self,
        chat_id: UUID,
        project_id: UUID,
        message: TelegramMessage,
    ) -> MessageOut:
        """
        Persist the Telegram message via MessageService (includes idempotency,
        SAVEPOINT, and chat timestamp update).

        message.text may be None for stickers, photos, etc. We store body=None
        in that case and tag message_type appropriately.
        """
        message_type = MessageType.TEXT if message.text is not None else MessageType.FILE

        data = MessageCreate(
            external_message_id=str(message.message_id),
            message_type=message_type,
            sender_type=SenderType.USER,
            sender_id=None,  # Telegram users are not CRM users
            body=message.text,
        )
        return await self.message_service.create_message(
            chat_id=chat_id,
            project_id=project_id,
            data=data,
        )

    async def _find_or_create_lead(
        self,
        chat_id: UUID,
        project_id: UUID,
        message: TelegramMessage,
    ) -> None:
        """
        Ensure a Lead exists for this chat. If the chat already has a lead,
        this is a no-op. If not, create one with status=new.

        SAVEPOINT pattern mirrors _find_or_create_chat().
        """
        # Fast path: lead already exists for this chat
        existing = await self.lead_repo.get_by_chat(chat_id, project_id)
        if existing is not None:
            return

        # Resolve the 'new' status — must exist in the reference table
        new_status = await self.lead_repo.get_status_by_code(LeadStatusCode.NEW)
        if new_status is None:
            logger.error(
                "Lead status '%s' not found in lead_statuses — "
                "cannot create lead for chat_id=%s. "
                "Run seed migrations to populate the lead_statuses table.",
                LeadStatusCode.NEW,
                chat_id,
            )
            return

        username: Optional[str] = None
        if message.from_user and message.from_user.username:
            username = message.from_user.username

        try:
            async with self.db.begin_nested():
                lead = await self.lead_repo.create(
                    project_id=project_id,
                    chat_id=chat_id,
                    status_id=new_status.id,
                    username=username,
                )
            logger.info(
                "Created lead id=%s chat_id=%s project_id=%s",
                lead.id,
                chat_id,
                project_id,
            )
            await self.audit.log(
                project_id=project_id,
                action=AuditAction.LEAD_CREATED,
                entity_type=EntityType.LEAD,
                entity_id=lead.id,
                actor_id=None,
                meta={
                    "source": "telegram_webhook",
                    "external_chat_id": str(message.chat.id),
                },
            )
        except IntegrityError:
            # Concurrent webhook delivery created the lead first — that's fine.
            logger.debug(
                "Concurrent lead create for chat_id=%s project_id=%s — already exists",
                chat_id,
                project_id,
            )
