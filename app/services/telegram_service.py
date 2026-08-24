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
  - project_id is resolved from the webhook bot_id, never from the incoming
    payload.

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
  - All unexpected exceptions propagate to the caller (the router), which
    logs them and returns 200 to Telegram anyway (Telegram must not retry).
"""
from hashlib import sha256
import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import (
    AuditAction,
    ChatEventType,
    EntityType,
    LeadStatusCode,
    MessageType,
    SenderType,
)
from app.core.lead_names import compose_lead_name, normalize_name_part, resolve_lead_names
from app.core.telegram_commands import extract_telegram_command
from app.models.chat import Chat
from app.models.lead import Lead
from app.repositories.bot_repository import BotRepository
from app.repositories.chat_repository import ChatRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.tracking_repository import TrackingRepository
from app.schemas.message import MessageCreate, MessageOut
from app.schemas.telegram import (
    TelegramCallbackQuery,
    TelegramChatMemberUpdated,
    TelegramMessage,
    TelegramUpdate,
)
from app.services.audit_service import AuditService
from app.services.bot_engine_service import BotEngineService
from app.services.broadcast_service import BroadcastService
from app.services.chat_user_block_service import ChatUserBlockService
from app.services.channel_subscription_service import (
    ChannelSubscriptionService,
    ChannelTrackingAttribution,
)
from app.services.channel_join_request_queue import (
    enqueue_channel_join_request_action,
)
from app.services.chat_audit_service import ChatAuditService
from app.services.chat_lease_service import ChatLeaseService
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.facebook_campaign_service import FacebookCampaignService
from app.services.funnel_start_queue import enqueue_funnel_start
from app.services.message_service import MessageService
from app.services.telegram_sender import TelegramSenderService
from app.services.utm_bridge_service import UtmBridgeService
from app.services.user_input_queue import enqueue_user_input

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramStartPayload:
    ref_code: str | None = None
    utm_key: str | None = None
    start_key: str | None = None
    tracking_link_id: UUID | None = None
    utm_data: dict[str, Any] | None = None


@dataclass(frozen=True)
class TelegramHistoryImportResult:
    chat_id: UUID
    lead_id: UUID | None
    chat_created: bool


class TelegramService:
    START_UTM_SUFFIX_RE = re.compile(r"^(?P<ref_code>.+)_(?P<utm_key>utm_[0-9a-fA-F]{8})$")

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.bot_repo = BotRepository(db)
        self.chat_repo = ChatRepository(db)
        self.lead_repo = LeadRepository(db)
        self.message_repo = MessageRepository(db)
        self.tracking_repo = TrackingRepository(db)
        self.project_repo = ProjectRepository(db)
        self.message_service = MessageService(db)
        self.bot_engine = BotEngineService(db)
        self.broadcasts = BroadcastService(db)
        self.funnel_runtime = FunnelRuntimeService(db)
        self.telegram_sender = TelegramSenderService(db)
        self.audit = AuditService(db)
        self.chat_audit = ChatAuditService(db)
        self.chat_lease = ChatLeaseService(db)
        self.utm_bridge = UtmBridgeService()
        self._pending_channel_join_request_actions: list[UUID] = []

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

    async def handle_webhook_update(
        self,
        update: TelegramUpdate,
        bot_id: UUID,
    ) -> None:
        """
        Resolve webhook bot context and process the Telegram update.

        Unknown or deleted bots are ignored so Telegram receives 200 and does
        not retry an update for a webhook that points at stale state.
        """
        bot = await self.bot_repo.get_active(bot_id)
        if bot is None:
            logger.warning(
                "Telegram webhook: unknown bot_id=%s update_id=%s",
                bot_id,
                update.update_id,
            )
            return

        await self.handle_update(
            update=update,
            project_id=bot.project_id,
            bot_id=bot.id,
            source_transport="bot_api",
        )

    async def handle_update(
        self,
        update: TelegramUpdate,
        project_id: UUID,
        bot_id: UUID,
        source_transport: str = "bot_api",
    ) -> None:
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
        if update.my_chat_member is not None:
            if await ChannelSubscriptionService(self.db).handle_tracker_membership(
                bot_id=bot_id,
                event=update.my_chat_member,
            ):
                return
            await self._handle_my_chat_member(
                update.my_chat_member,
                project_id=project_id,
                bot_id=bot_id,
            )
            return

        chat_member_update = getattr(update, "chat_member", None)
        if chat_member_update is not None:
            await ChannelSubscriptionService(self.db).handle_chat_member_update(
                update_id=update.update_id,
                bot_id=bot_id,
                event=chat_member_update,
            )
            return

        join_request_update = getattr(update, "chat_join_request", None)
        if join_request_update is not None:
            action = await ChannelSubscriptionService(self.db).handle_join_request(
                update_id=update.update_id,
                bot_id=bot_id,
                event=join_request_update,
            )
            if action is not None:
                self._pending_channel_join_request_actions.append(action.event_id)
            return

        message = self.extract_message(update)
        if message is None:
            if update.callback_query is not None:
                await self._handle_callback_query(
                    update.callback_query,
                    project_id=project_id,
                    bot_id=bot_id,
                )
                return
            logger.debug("update_id=%s: unsupported update — skipping", update.update_id)
            return

        is_bot_api = source_transport == "bot_api"
        start_payload = (
            await self._hydrate_start_payload(self._extract_start_payload(message.text))
            if is_bot_api
            else TelegramStartPayload()
        )
        has_explicit_start_attribution = self._has_explicit_start_attribution(
            start_payload
        )
        explicit_tracking_link_id = await self._resolve_tracking_link_id(
            start_payload,
            project_id,
            bot_id,
        )
        tracking_link_id = explicit_tracking_link_id
        channel_attribution: ChannelTrackingAttribution | None = None
        if (
            tracking_link_id is None
            and not has_explicit_start_attribution
            and message.from_user is not None
            and is_bot_api
            and self._is_start_command(message.text)
        ):
            channel_attribution = await self._resolve_channel_tracking_attribution(
                project_id=project_id,
                telegram_user_id=message.from_user.id,
            )
            tracking_link_id = (
                channel_attribution.tracking_link_id
                if channel_attribution is not None
                else None
            )
        chat, should_start_runtime, is_reactivated_cycle = await self._find_or_create_chat(
            message,
            project_id,
            bot_id=bot_id,
            tracking_link_id=tracking_link_id,
            replace_existing_channel_attribution=tracking_link_id is not None,
        )
        chat_lease = getattr(self, "chat_lease", None)
        if chat_lease is not None:
            await chat_lease.release_expired(
                project_id=project_id,
                chat_id=chat.id,
            )
        # MessageService updates Chat via a SQL expression, which can expire
        # attributes on an already loaded ORM instance. Keep primitives before
        # that update and never rely on lazy ORM reads after an explicit commit.
        chat_id = chat.id
        external_chat_id = chat.external_chat_id
        chat_is_blocked = chat.is_blocked
        chat_is_imported = bool(getattr(chat, "is_imported", False))
        chat_lead_import_id = getattr(chat, "lead_import_id", None)
        start_tracking_link_id: UUID | None = None
        if is_bot_api and self._is_start_command(message.text):
            start_tracking_link_id = (
                explicit_tracking_link_id
                if has_explicit_start_attribution
                else getattr(chat, "tracking_link_id", None)
            )
        msg = await self._create_message(
            chat_id,
            project_id,
            message,
            tracking_link_id=start_tracking_link_id,
            source_transport=source_transport,
        )
        message_id = msg.id
        event_reference = msg.external_message_id or str(message_id)
        persisted_message = await self.message_repo.get_by_id(msg.id)
        if persisted_message is not None and persisted_message.funnel_processed_at is not None:
            logger.info(
                "Duplicate Telegram message already processed chat_id=%s message_id=%s",
                chat_id,
                message_id,
            )
            return
        logger.info(
            "Incoming Telegram message persisted bot_id=%s project_id=%s chat_id=%s "
            "message_id=%s text=%s",
            bot_id,
            project_id,
            chat_id,
            message_id,
            message.text,
        )
        if chat_is_blocked:
            await self.message_repo.claim_funnel_processing([message_id])
            logger.info(
                "Ignored blocked Telegram chat bot_id=%s project_id=%s chat_id=%s",
                bot_id,
                project_id,
                chat_id,
            )
            return
        lead = await self._find_or_create_lead(
            chat_id,
            project_id,
            message,
            reset_existing=is_reactivated_cycle,
        )
        lead_id = lead.id if lead is not None else None
        contact_saved = await self._save_shared_contact(
            lead=lead,
            project_id=project_id,
            message=message,
        )
        if contact_saved:
            await self._clear_latest_contact_button(
                chat_id=chat_id,
                external_chat_id=external_chat_id,
                project_id=project_id,
                bot_id=bot_id,
            )
        channel_attribution_applies = bool(
            channel_attribution is not None
            and tracking_link_id
            == channel_attribution.tracking_link_id
            and getattr(chat, "tracking_link_id", None) == tracking_link_id
        )
        await self._attach_utm_bridge_data(
            lead,
            start_payload.utm_key,
            (
                start_payload.utm_data
                if start_payload.utm_data is not None
                else channel_attribution.attribution_data
                if channel_attribution_applies and channel_attribution is not None
                else None
            ),
        )
        is_start_command = is_bot_api and self._is_start_command(message.text)
        custom_command = extract_telegram_command(message.text)
        if (
            custom_command is not None
            and custom_command != "start"
            and await self._has_active_custom_command(
                project_id=project_id,
                bot_id=bot_id,
                command=custom_command,
            )
        ):
            await self.db.commit()
            queued = await enqueue_funnel_start(
                chat_id,
                message_id,
                fresh_lifecycle=False,
            )
            if queued:
                logger.info(
                    "Custom funnel command queued chat_id=%s message_id=%s command=/%s",
                    chat_id,
                    message_id,
                    custom_command,
                )
            else:
                result = await self.process_queued_funnel_start(
                    chat_id=chat_id,
                    trigger_message_id=message_id,
                    fresh_lifecycle=False,
                )
                logger.warning(
                    "Funnel queue unavailable; custom command processed inline "
                    "chat_id=%s message_id=%s command=/%s result=%s",
                    chat_id,
                    message_id,
                    custom_command,
                    result,
                )
            return
        if is_start_command and not should_start_runtime:
            await self.chat_repo.mark_bot_restarted(
                chat_id=chat_id,
                project_id=project_id,
            )
            await self.chat_audit.log_event(
                chat_id=chat_id,
                project_id=project_id,
                user_id=None,
                event_type=ChatEventType.NOTE_ADDED,
                new_value="Пользователь повторно запустил бота",
            )
            await self.message_repo.claim_funnel_processing([message_id])
            logger.info(
                "Repeated Telegram /start recorded without restarting funnel "
                "project_id=%s bot_id=%s chat_id=%s message_id=%s",
                project_id,
                bot_id,
                chat_id,
                message_id,
            )
            return

        should_start_imported_account_runtime = bool(
            not is_bot_api
            and not should_start_runtime
            and await self._should_start_imported_mtproto_runtime(
                chat_id=chat_id,
                project_id=project_id,
                bot_id=bot_id,
                chat_is_imported=chat_is_imported,
                lead_import_id=chat_lead_import_id,
            )
        )
        start_requested = should_start_runtime or should_start_imported_account_runtime
        if start_requested:
            # Make the chat and lead visible before Telegram network calls made by the funnel.
            await self.db.commit()
            queued = await enqueue_funnel_start(
                chat_id,
                message_id,
                fresh_lifecycle=True,
            )
            if queued:
                logger.info(
                    "Funnel start queued chat_id=%s message_id=%s fresh_lifecycle=%s "
                    "source_transport=%s imported_account_start=%s",
                    chat_id,
                    message_id,
                    True,
                    source_transport,
                    should_start_imported_account_runtime,
                )
            else:
                result = await self.process_queued_funnel_start(
                    chat_id=chat_id,
                    trigger_message_id=message_id,
                    fresh_lifecycle=True,
                )
                logger.warning(
                    "Funnel start queue unavailable; processed inline chat_id=%s "
                    "message_id=%s result=%s",
                    chat_id,
                    message_id,
                    result,
                )
            if lead_id is not None and should_start_runtime and is_bot_api:
                await self._enqueue_facebook_event_safely(
                    lead_id=lead_id,
                    source_event="bot_start",
                    event_reference=f"telegram_start:{bot_id}:{event_reference}",
                    extra_custom_data={"content_name": "Telegram bot start"},
                )
            return

        await self._mark_gambling_out_of_scenario_activity(
            chat_id=chat_id,
            project_id=project_id,
        )

        if message.contact is not None:
            if not await self.message_repo.claim_funnel_processing([message_id]):
                logger.info(
                    "Skipped duplicate Telegram contact processing chat_id=%s message_id=%s",
                    chat_id,
                    message_id,
                )
                return
            runtime_chat = await self._reload_chat_for_runtime(chat_id)
            await self._process_runtime_or_legacy(
                chat=runtime_chat,
                project_id=project_id,
                bot_id=bot_id,
                user_message=msg,
                start_requested=False,
                fresh_lifecycle=False,
            )
            await self._enqueue_facebook_event_safely(
                lead_id=lead_id,
                source_event="contact",
                event_reference=f"telegram_contact:{bot_id}:{event_reference}",
                extra_custom_data={"content_name": "Telegram contact"},
            )
            logger.info(
                "Telegram contact processed immediately chat_id=%s message_id=%s",
                chat_id,
                message_id,
            )
            return

        queued = await enqueue_user_input(chat_id, message_id)
        if queued:
            logger.info(
                "Incoming Telegram input deferred chat_id=%s message_id=%s delay_seconds=%s",
                chat_id,
                message_id,
                settings.TELEGRAM_INPUT_DEBOUNCE_SECONDS,
            )
            return

        logger.warning(
            "Debounce queue unavailable; processing input immediately chat_id=%s message_id=%s",
            chat_id,
            message_id,
        )
        if not await self.message_repo.claim_funnel_processing([message_id]):
            return
        runtime_chat = await self._reload_chat_for_runtime(chat_id)
        await self._process_runtime_or_legacy(
            chat=runtime_chat,
            project_id=project_id,
            bot_id=bot_id,
            user_message=msg,
            start_requested=False,
            fresh_lifecycle=False,
        )

    async def handle_mtproto_outgoing_message(
        self,
        *,
        update: TelegramUpdate,
        project_id: UUID,
        bot_id: UUID,
        manual_outgoing: bool = True,
    ) -> None:
        """Persist a message sent manually from the connected Telegram client."""

        message = self.extract_message(update)
        if message is None:
            return
        chat, _, is_reactivated_cycle = await self._find_or_create_chat(
            message,
            project_id,
            bot_id=bot_id,
        )
        await self._find_or_create_lead(
            chat.id,
            project_id,
            message,
            reset_existing=is_reactivated_cycle,
        )
        data = self._telegram_message_to_create(
            message,
            source_transport="user_mtproto",
        )
        raw_payload = dict(data.raw_payload_json or {})
        raw_payload["mtproto_manual_outgoing"] = manual_outgoing
        data = data.model_copy(
            update={
                "sender_type": SenderType.BOT,
                "sender_id": None,
                "operator_id": None,
                "raw_payload_json": raw_payload,
            }
        )
        if message.reply_to_message is not None:
            reply_target = await self.message_repo.get_by_external_id(
                chat.id,
                str(message.reply_to_message.message_id),
            )
            if reply_target is not None:
                data = data.model_copy(update={"reply_to_message_id": reply_target.id})
        await self.message_service.create_message(
            chat_id=chat.id,
            project_id=project_id,
            data=data,
            send_to_telegram=False,
        )
        if manual_outgoing:
            await self.bot_repo.disable_bot_for_chat(chat.id)
            await self.funnel_runtime.pause_for_external_account_message(
                chat_id=chat.id,
                project_id=project_id,
            )

    async def handle_mtproto_history_message(
        self,
        *,
        update: TelegramUpdate,
        project_id: UUID,
        bot_id: UUID,
        sent_at: datetime,
        outgoing: bool,
    ) -> TelegramHistoryImportResult | None:
        """Import MTProto history without replaying old input through a funnel."""

        message = self.extract_message(update)
        if message is None:
            return None
        chat, chat_created, is_reactivated_cycle = await self._find_or_create_chat(
            message,
            project_id,
            bot_id=bot_id,
        )
        lead = await self._find_or_create_lead(
            chat.id,
            project_id,
            message,
            reset_existing=is_reactivated_cycle,
        )
        data = self._telegram_message_to_create(
            message,
            source_transport="user_mtproto",
        )
        raw_payload = dict(data.raw_payload_json or {})
        raw_payload["mtproto_history_import"] = True
        if outgoing:
            raw_payload["mtproto_manual_outgoing"] = True
        data = data.model_copy(
            update={
                "sender_type": SenderType.BOT if outgoing else SenderType.USER,
                "sender_id": None,
                "operator_id": None,
                "raw_payload_json": raw_payload,
                "created_at": sent_at,
            }
        )
        if message.reply_to_message is not None:
            reply_target = await self.message_repo.get_by_external_id(
                chat.id,
                str(message.reply_to_message.message_id),
            )
            if reply_target is not None:
                data = data.model_copy(update={"reply_to_message_id": reply_target.id})
        persisted = await self.message_service.create_message(
            chat_id=chat.id,
            project_id=project_id,
            data=data,
            send_to_telegram=False,
            translate_incoming=False,
        )
        if not outgoing:
            # Recovery jobs only consider unclaimed incoming messages. Claiming
            # imported history prevents an old reply from starting a funnel.
            await self.message_repo.claim_funnel_processing([persisted.id])

        if chat_created:
            now = datetime.now(timezone.utc)
            await self.chat_repo.update_by_id(
                chat.id,
                is_imported=True,
                imported_at=now,
                created_at=sent_at,
            )
            if lead is not None:
                await self.lead_repo.update_by_id(lead.id, created_at=sent_at)

        return TelegramHistoryImportResult(
            chat_id=chat.id,
            lead_id=lead.id if lead is not None else None,
            chat_created=chat_created,
        )

    async def finalize_mtproto_history_dialog(
        self,
        *,
        chat_id: UUID,
        is_read: bool,
    ) -> None:
        if is_read:
            await self.chat_repo.mark_as_read(chat_id)
        else:
            await self.chat_repo.mark_as_unread(chat_id)

    async def handle_mtproto_message_edit(
        self,
        *,
        external_chat_id: str,
        external_message_id: str,
        project_id: UUID,
        bot_id: UUID,
        text: str,
        is_caption: bool,
        edited_at: datetime,
    ) -> bool:
        chat = await self.chat_repo.get_by_external(
            project_id,
            external_chat_id,
            bot_id=bot_id,
        )
        if chat is None:
            return False
        message = await self.message_repo.get_by_external_id(
            chat.id,
            external_message_id,
        )
        if message is None:
            return False
        await self.message_repo.mark_edited(
            message_id=message.id,
            text=text,
            is_caption=is_caption,
            edited_at=edited_at,
        )
        return True

    async def handle_mtproto_message_delete(
        self,
        *,
        external_chat_id: str,
        external_message_ids: list[str],
        project_id: UUID,
        bot_id: UUID,
        deleted_at: datetime,
    ) -> int:
        chat = await self.chat_repo.get_by_external(
            project_id,
            external_chat_id,
            bot_id=bot_id,
        )
        if chat is None:
            return 0
        deleted = 0
        for external_message_id in external_message_ids:
            message = await self.message_repo.get_by_external_id(
                chat.id,
                external_message_id,
            )
            if message is None:
                continue
            await self.message_repo.mark_deleted(
                message_id=message.id,
                deleted_at=deleted_at,
            )
            deleted += 1
        return deleted

    async def handle_mtproto_message_delete_without_peer(
        self,
        *,
        external_message_ids: list[str],
        bot_id: UUID,
        deleted_at: datetime,
    ) -> int:
        messages = await self.message_repo.list_by_external_ids_for_bot(
            bot_id=bot_id,
            external_message_ids=external_message_ids,
        )
        for message in messages:
            await self.message_repo.mark_deleted(
                message_id=message.id,
                deleted_at=deleted_at,
            )
        return len(messages)

    async def dispatch_post_commit_actions(self) -> None:
        pending = tuple(self._pending_channel_join_request_actions)
        self._pending_channel_join_request_actions.clear()
        for event_id in pending:
            job_id = await enqueue_channel_join_request_action(event_id)
            if job_id is None:
                logger.error(
                    "Channel join-request action was persisted but not queued event_id=%s",
                    event_id,
                )

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _mark_gambling_out_of_scenario_activity(
        self,
        *,
        chat_id: UUID,
        project_id: UUID,
    ) -> None:
        project = await self.project_repo.get_active(project_id)
        if project is None or project.project_format != "gambling":
            return
        state = await self.funnel_runtime.repo.get_chat_funnel_state(chat_id)
        if (
            state is None
            or state.completed_at is not None
            or state.is_paused
            or not state.waiting_for_answer
        ):
            await self.chat_repo.mark_out_of_scenario_message(
                chat_id=chat_id,
                project_id=project_id,
            )

    async def _handle_my_chat_member(
        self,
        event: TelegramChatMemberUpdated,
        *,
        project_id: UUID,
        bot_id: UUID,
    ) -> None:
        status = str(event.new_chat_member.status or "").strip().lower()
        if status not in {"kicked", "member"}:
            logger.debug(
                "Telegram my_chat_member ignored project_id=%s bot_id=%s chat_id=%s status=%s",
                project_id,
                bot_id,
                event.chat.id,
                status,
            )
            return

        is_blocked = status == "kicked"
        chat = await ChatUserBlockService(self.db).set_blocked_by_user(
            project_id=project_id,
            bot_id=bot_id,
            external_chat_id=str(event.chat.id),
            is_blocked_by_user=is_blocked,
        )
        if chat is None:
            logger.info(
                "Telegram my_chat_member received for unknown chat project_id=%s "
                "bot_id=%s external_chat_id=%s status=%s",
                project_id,
                bot_id,
                event.chat.id,
                status,
            )
            return

        if is_blocked:
            logger.info(
                "Telegram user blocked bot project_id=%s bot_id=%s chat_id=%s external_chat_id=%s",
                project_id,
                bot_id,
                chat.id,
                chat.external_chat_id,
            )
        else:
            logger.info(
                "Telegram user unblocked bot project_id=%s bot_id=%s chat_id=%s external_chat_id=%s",
                project_id,
                bot_id,
                chat.id,
                chat.external_chat_id,
            )

    async def _save_shared_contact(
        self,
        *,
        lead: Optional[Lead],
        project_id: UUID,
        message: TelegramMessage,
    ) -> bool:
        if lead is None or message.contact is None:
            return False
        await self.lead_repo.update_contact(
            lead.id,
            project_id,
            phone=message.contact.phone_number,
            name=" ".join(
                part
                for part in [message.contact.first_name, message.contact.last_name]
                if part
            ).strip()
            or lead.name,
        )
        # The phone must be visible in CRM even if later funnel delivery fails.
        await self.db.commit()
        return True

    async def _clear_latest_contact_button(
        self,
        *,
        chat_id: UUID,
        external_chat_id: str,
        project_id: UUID,
        bot_id: UUID,
    ) -> None:
        outgoing = next(
            (
                message
                for message in await self.message_repo.list_recent_outgoing_with_buttons(chat_id)
                if self._has_contact_web_app(message.raw_payload_json)
            ),
            None,
        )
        if outgoing is None:
            return
        await self.telegram_sender.edit_message_reply_markup(
            project_id,
            bot_id,
            external_chat_id,
            int(outgoing.external_message_id),
        )

    async def _reload_chat_for_runtime(self, chat_id: UUID) -> Chat:
        chat = await self.chat_repo.get_by_id(chat_id)
        if chat is None or chat.is_deleted or chat.reset_at is not None:
            raise RuntimeError(f"Chat is unavailable for funnel runtime: {chat_id}")
        return chat

    async def _enqueue_facebook_event_safely(
        self,
        *,
        lead_id: UUID | None,
        source_event: str,
        event_reference: str,
        extra_custom_data: dict[str, Any] | None = None,
    ) -> None:
        if lead_id is None:
            return
        try:
            await FacebookCampaignService(self.db).enqueue_mapped_event(
                lead_id=lead_id,
                source_event=source_event,
                event_reference=event_reference,
                extra_custom_data=extra_custom_data,
            )
        except Exception:
            logger.exception(
                "Facebook event enqueue failed without blocking Telegram runtime "
                "lead_id=%s source_event=%s",
                lead_id,
                source_event,
            )

    @staticmethod
    def _has_contact_web_app(raw_payload: dict | None) -> bool:
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        reply_markup = payload.get("reply_markup")
        if not isinstance(reply_markup, dict):
            return False
        rows = reply_markup.get("inline_keyboard")
        if not isinstance(rows, list):
            return False
        return any(
            isinstance(button, dict)
            and isinstance(button.get("web_app"), dict)
            and str(button["web_app"].get("url") or "").endswith(
                "/telegram/contact-request"
            )
            for row in rows
            if isinstance(row, list)
            for button in row
        )

    async def _find_or_create_chat(
        self,
        message: TelegramMessage,
        project_id: UUID,
        bot_id: UUID,
        tracking_link_id: Optional[UUID] = None,
        replace_existing_channel_attribution: bool = False,
    ) -> tuple[Chat, bool, bool]:
        """
        Return the Chat for this external_chat_id, creating it if absent.

        SAVEPOINT pattern: INSERT inside begin_nested() so that an
        IntegrityError from a concurrent insert rolls back only the savepoint,
        not the outer transaction. The loser then re-fetches the winner's row.
        """
        external_chat_id = str(message.chat.id)
        external_user_id = str(message.from_user.id) if message.from_user else external_chat_id

        # Fast path: chat already exists
        chat = await self.chat_repo.get_by_external(
            project_id,
            external_chat_id,
            bot_id=bot_id,
        )
        if chat is not None:
            contact_name = self._contact_name_from_message(message)
            updates: dict[str, Any] = {}
            if (
                message.chat.access_hash is not None
                and message.chat.access_hash != chat.external_access_hash
            ):
                updates["external_access_hash"] = message.chat.access_hash
            is_imported = bool(getattr(chat, "is_imported", False))
            identity_pending = bool(
                getattr(chat, "import_identity_pending", False)
            )
            if (
                contact_name
                and contact_name != chat.contact_name
                and (not is_imported or not chat.contact_name)
            ):
                updates["contact_name"] = contact_name
            if is_imported and identity_pending:
                updates["external_user_id"] = external_user_id
                updates["import_identity_pending"] = False
            current_tracking_link_id = getattr(chat, "tracking_link_id", None)
            should_replace_channel_attribution = (
                replace_existing_channel_attribution
                and tracking_link_id is not None
                and current_tracking_link_id is not None
                and current_tracking_link_id != tracking_link_id
                and await self._is_channel_tracking_link(current_tracking_link_id)
            )
            if tracking_link_id is not None and (
                current_tracking_link_id is None
                or should_replace_channel_attribution
            ):
                updates["tracking_link_id"] = tracking_link_id
            if updates:
                updated_chat = await self.chat_repo.update_by_id(
                    chat.id,
                    **updates,
                )
                if updated_chat is not None:
                    chat = updated_chat
            return chat, False, False

        # A join-request bot may create the CRM chat through Telegram's
        # temporary user_chat_id before the user's first private message. Match
        # that row by the stable Telegram user id and bind the real chat id.
        identity_chat = await self.chat_repo.get_by_external_user(
            project_id=project_id,
            bot_id=bot_id,
            external_user_id=external_user_id,
        )
        if identity_chat is not None:
            contact_name = self._contact_name_from_message(message)
            updates = {"external_chat_id": external_chat_id}
            if contact_name and not identity_chat.contact_name:
                updates["contact_name"] = contact_name
            if tracking_link_id is not None and identity_chat.tracking_link_id is None:
                updates["tracking_link_id"] = tracking_link_id
            rebound = await self.chat_repo.update_by_id(identity_chat.id, **updates)
            return rebound or identity_chat, False, False

        username_key = self._telegram_username_key(message)
        if username_key:
            try:
                async with self.db.begin_nested():
                    imported_chat = await self.chat_repo.claim_pending_import_identity(
                        project_id=project_id,
                        bot_id=bot_id,
                        username_key=username_key,
                        external_chat_id=external_chat_id,
                        external_user_id=external_user_id,
                        contact_name=self._contact_name_from_message(message),
                    )
            except IntegrityError:
                imported_chat = await self.chat_repo.get_by_external(
                    project_id,
                    external_chat_id,
                    bot_id=bot_id,
                )
            if imported_chat is not None:
                logger.info(
                    "Claimed imported Telegram chat by username project_id=%s "
                    "bot_id=%s chat_id=%s external_chat_id=%s",
                    project_id,
                    bot_id,
                    imported_chat.id,
                    external_chat_id,
                )
                return imported_chat, False, False

        # Build a human-readable contact name from available sender fields
        contact_name = self._contact_name_from_message(message)

        reset_chat = await self.chat_repo.get_reset_by_external(
            project_id,
            external_chat_id,
            bot_id=bot_id,
        )
        if reset_chat is not None:
            reactivated = await self.chat_repo.reactivate_reset_chat(
                reset_chat.id,
                tracking_link_id=tracking_link_id,
                contact_name=contact_name,
            )
            if reactivated is None:
                raise RuntimeError(
                    f"Reset chat row missing during reactivation for "
                    f"external_chat_id={external_chat_id}"
                )
            logger.info(
                "Reactivated reset chat id=%s external_chat_id=%s project_id=%s bot_id=%s",
                reactivated.id,
                external_chat_id,
                project_id,
                bot_id,
            )
            return reactivated, True, True

        try:
            async with self.db.begin_nested():
                chat = await self.chat_repo.create(
                    project_id=project_id,
                    bot_id=bot_id,
                    tracking_link_id=tracking_link_id,
                    external_chat_id=external_chat_id,
                    external_user_id=external_user_id,
                    external_access_hash=message.chat.access_hash,
                    contact_name=contact_name,
                )
            logger.info(
                "Created chat id=%s external_chat_id=%s project_id=%s bot_id=%s",
                chat.id,
                external_chat_id,
                project_id,
                bot_id,
            )
        except IntegrityError:
            # Concurrent insert won the race — re-fetch the winner's row.
            logger.debug(
                "Concurrent chat create for external_chat_id=%s project_id=%s — re-fetching",
                external_chat_id,
                project_id,
            )
            chat = await self.chat_repo.get_by_external(
                project_id,
                external_chat_id,
                bot_id=bot_id,
            )
            if chat is None:
                # Should never happen: IntegrityError means the row exists.
                raise RuntimeError(
                    f"Chat row missing after IntegrityError for "
                    f"external_chat_id={external_chat_id}"
                )
            return chat, False, False

        return chat, True, False

    async def _is_channel_tracking_link(self, tracking_link_id: UUID) -> bool:
        tracking_repo = getattr(self, "tracking_repo", None)
        if tracking_repo is None:
            return False
        link = await tracking_repo.get_link_by_id(tracking_link_id)
        return bool(
            link is not None
            and getattr(link, "destination_type", "bot") == "channel"
        )

    async def _process_runtime_or_legacy(
        self,
        *,
        chat: Chat,
        project_id: UUID,
        bot_id: UUID,
        user_message: MessageOut,
        start_requested: bool,
        fresh_lifecycle: bool,
    ) -> None:
        chat_id = chat.id
        bot = await self.bot_repo.get_active(bot_id)
        has_active_pointer = bool(
            bot is not None
            and bot.active_funnel_id is not None
            and bot.active_funnel_version_id is not None
        )
        active_funnel, active_version = await self.funnel_runtime.get_active_published_funnel_for_bot(
            bot_id,
            project_id,
        )

        if active_version is not None and active_funnel is not None:
            active_funnel_id = active_funnel.id
            active_version_id = active_version.id
            logger.info(
                "Using active funnel runtime bot_id=%s project_id=%s chat_id=%s "
                "funnel_id=%s funnel_version_id=%s start_requested=%s",
                bot_id,
                project_id,
                chat_id,
                active_funnel_id,
                active_version_id,
                start_requested,
            )
            try:
                await self._run_active_funnel_runtime(
                    chat=chat,
                    active_funnel_id=active_funnel_id,
                    active_funnel_version_id=active_version_id,
                    user_message=user_message,
                    start_requested=start_requested,
                    fresh_lifecycle=fresh_lifecycle,
                )
            except Exception:
                logger.exception(
                    "Active funnel runtime failed bot_id=%s project_id=%s chat_id=%s "
                    "funnel_id=%s funnel_version_id=%s",
                    bot_id,
                    project_id,
                    chat_id,
                    active_funnel_id,
                    active_version_id,
                )
                raise
            return

        if has_active_pointer:
            logger.error(
                "Active funnel pointer exists but no published runnable version was found; "
                "legacy fallback is disabled bot_id=%s project_id=%s chat_id=%s "
                "active_funnel_id=%s active_funnel_version_id=%s",
                bot_id,
                project_id,
                chat.id,
                bot.active_funnel_id if bot else None,
                bot.active_funnel_version_id if bot else None,
            )
            return

        logger.info(
            "No active funnel, using legacy bot_engine fallback bot_id=%s project_id=%s "
            "chat_id=%s start_requested=%s",
            bot_id,
            project_id,
            chat.id,
            start_requested,
        )
        if start_requested:
            await self.bot_engine.initialize_chat(chat.id, project_id)
        else:
            await self.bot_engine.process_chat(chat.id, user_message=user_message)

    async def process_debounced_user_input(
        self,
        *,
        chat_id: UUID,
        trigger_message_id: UUID,
    ) -> str:
        chat = await self.chat_repo.get_by_id(chat_id)
        if chat is None or chat.is_deleted or chat.reset_at is not None or chat.bot_id is None:
            return "chat_unavailable"

        latest = await self.message_repo.get_latest_user_message(chat_id)
        if latest is None:
            return "no_input"
        if latest.id != trigger_message_id:
            return "superseded"

        created_at = latest.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        quiet_seconds = (datetime.now(timezone.utc) - created_at).total_seconds()
        if quiet_seconds < max(settings.TELEGRAM_INPUT_QUIET_SECONDS, 1):
            return "still_typing"

        batch = await self.message_repo.list_unprocessed_user_input_batch(
            chat_id,
            through_message=latest,
        )
        if not batch:
            return "already_processed"

        batch_ids = [item.id for item in batch]
        if not await self.message_repo.claim_funnel_processing(batch_ids):
            return "already_processing"

        if chat.is_blocked:
            return "blocked"

        if (
            getattr(latest, "transport_source", "bot_api") == "user_mtproto"
            and await self._should_start_imported_mtproto_runtime(
                chat_id=chat.id,
                project_id=chat.project_id,
                bot_id=chat.bot_id,
                chat_is_imported=bool(getattr(chat, "is_imported", False)),
                lead_import_id=getattr(chat, "lead_import_id", None),
            )
        ):
            representative = MessageOut.model_validate(batch[-1])
            await self._process_runtime_or_legacy(
                chat=chat,
                project_id=chat.project_id,
                bot_id=chat.bot_id,
                user_message=representative,
                start_requested=True,
                fresh_lifecycle=True,
            )
            logger.warning(
                "Recovered first live MTProto input for imported dialog chat_id=%s "
                "messages=%s",
                chat_id,
                len(batch),
            )
            return "processed"

        start_index = next(
            (
                index
                for index, item in enumerate(batch)
                if getattr(item, "transport_source", "bot_api") == "bot_api"
                and self._is_start_command(item.body)
            ),
            None,
        )
        input_batch = batch
        if start_index is not None:
            start_message = batch[start_index]
            await self._process_runtime_or_legacy(
                chat=chat,
                project_id=chat.project_id,
                bot_id=chat.bot_id,
                user_message=MessageOut.model_validate(start_message),
                start_requested=True,
                fresh_lifecycle=True,
            )
            input_batch = batch[start_index + 1 :]
            logger.warning(
                "Recovered pending /start from debounced input chat_id=%s "
                "start_message_id=%s trailing_messages=%s",
                chat_id,
                start_message.id,
                len(input_batch),
            )

        if not input_batch:
            return "processed"

        chunks = [
            str(item.body or item.caption or item.message_type).strip()
            for item in input_batch
            if str(item.body or item.caption or item.message_type).strip()
        ]
        combined_text = "\n".join(chunks)
        representative = MessageOut.model_validate(input_batch[-1]).model_copy(
            update={"body": combined_text, "caption": None},
        )
        await self._process_runtime_or_legacy(
            chat=chat,
            project_id=chat.project_id,
            bot_id=chat.bot_id,
            user_message=representative,
            start_requested=False,
            fresh_lifecycle=False,
        )
        logger.info(
            "Debounced Telegram input processed chat_id=%s messages=%s chars=%s",
            chat_id,
            len(input_batch),
            len(combined_text),
        )
        return "processed"

    async def process_queued_funnel_start(
        self,
        *,
        chat_id: UUID,
        trigger_message_id: UUID,
        fresh_lifecycle: bool,
    ) -> str:
        chat = await self.chat_repo.get_by_id(chat_id)
        message = await self.message_repo.get_by_id(trigger_message_id)
        if (
            chat is None
            or message is None
            or chat.is_deleted
            or chat.reset_at is not None
            or chat.bot_id is None
        ):
            return "unavailable"
        inferred_command = extract_telegram_command(getattr(message, "body", None))
        requested_command = inferred_command
        if requested_command and requested_command != "start":
            active_funnel, active_version = (
                await self.funnel_runtime.get_active_published_funnel_for_bot(
                    chat.bot_id,
                    chat.project_id,
                )
            )
            if active_funnel is None or active_version is None:
                if not fresh_lifecycle:
                    await self.message_repo.claim_funnel_processing([message.id])
                    return "command_unavailable"
            else:
                trigger = await self.funnel_runtime.get_custom_command_trigger(
                    funnel_version_id=active_version.id,
                    command=requested_command,
                )
                if trigger is None:
                    if not fresh_lifecycle:
                        await self.message_repo.claim_funnel_processing([message.id])
                        return "command_unavailable"
                else:
                    if not await self.message_repo.claim_funnel_processing([message.id]):
                        return "already_processed"
                    await self.bot_repo.reset_chat_state(chat.id)
                    started = await self.funnel_runtime.execute_custom_command_for_chat(
                        chat_id=chat.id,
                        funnel_id=active_funnel.id,
                        funnel_version_id=active_version.id,
                        command=requested_command,
                    )
                    return "processed" if started is not None else "command_unavailable"
        if not await self.message_repo.claim_funnel_processing([message.id]):
            return "already_processed"
        await self._process_runtime_or_legacy(
            chat=chat,
            project_id=chat.project_id,
            bot_id=chat.bot_id,
            user_message=MessageOut.model_validate(message),
            start_requested=True,
            fresh_lifecycle=fresh_lifecycle,
        )
        return "processed"

    async def _has_active_custom_command(
        self,
        *,
        project_id: UUID,
        bot_id: UUID,
        command: str,
    ) -> bool:
        active_funnel, active_version = (
            await self.funnel_runtime.get_active_published_funnel_for_bot(
                bot_id,
                project_id,
            )
        )
        if active_funnel is None or active_version is None:
            return False
        trigger = await self.funnel_runtime.get_custom_command_trigger(
            funnel_version_id=active_version.id,
            command=command,
        )
        return trigger is not None

    async def _should_start_imported_mtproto_runtime(
        self,
        *,
        chat_id: UUID,
        project_id: UUID,
        bot_id: UUID,
        chat_is_imported: bool,
        lead_import_id: UUID | None,
    ) -> bool:
        """Start automation on the first live input after MTProto history import."""

        # Spreadsheet/CRM transfers are intentionally inert: an imported lead
        # must never be replayed through the funnel. Only the technical history
        # sync performed when a named Telegram account is connected can start
        # on its first subsequent live input.
        if not chat_is_imported or lead_import_id is not None:
            return False

        latest_outgoing = await self.message_repo.get_latest_outgoing_message(chat_id)
        if latest_outgoing is not None:
            payload = (
                latest_outgoing.raw_payload_json
                if isinstance(latest_outgoing.raw_payload_json, dict)
                else {}
            )
            is_live_manual_message = (
                latest_outgoing.sender_type == SenderType.MANAGER
                or (
                    latest_outgoing.is_external_account_message
                    and not bool(payload.get("mtproto_history_import"))
                )
            )
            if is_live_manual_message:
                logger.info(
                    "MTProto funnel auto-start suppressed after a live manual "
                    "message chat_id=%s message_id=%s",
                    chat_id,
                    latest_outgoing.id,
                )
                return False

        active_funnel, active_version = (
            await self.funnel_runtime.get_active_published_funnel_for_bot(
                bot_id,
                project_id,
            )
        )
        if active_funnel is None or active_version is None:
            return False

        status_name, _ = await self.funnel_runtime.get_state_status(
            chat_id=chat_id,
            active_funnel_version_id=active_version.id,
        )
        return status_name == "not_started"

    async def _run_active_funnel_runtime(
        self,
        *,
        chat: Chat,
        active_funnel_id: UUID,
        active_funnel_version_id: UUID,
        user_message: MessageOut,
        start_requested: bool,
        fresh_lifecycle: bool,
    ) -> None:
        if not await self.funnel_runtime.lock_chat_for_runtime(chat.id):
            logger.warning("Funnel runtime skipped because chat does not exist chat_id=%s", chat.id)
            return
        status_name, state = await self.funnel_runtime.get_state_status(
            chat_id=chat.id,
            active_funnel_version_id=active_funnel_version_id,
        )
        logger.info(
            "Active funnel state bot_id=%s chat_id=%s funnel_version_id=%s state=%s "
            "fresh_lifecycle=%s start_requested=%s",
            chat.bot_id,
            chat.id,
            active_funnel_version_id,
            status_name,
            fresh_lifecycle,
            start_requested,
        )
        target_step_key = await self._tracking_target_step_key(
            chat=chat,
            active_funnel_id=active_funnel_id,
        )

        if fresh_lifecycle:
            previous_cycle_state = self._is_completed_state_from_previous_cycle(
                state=state,
                cycle_started_at=chat.current_cycle_started_at,
            )
            if status_name != "not_started" and not previous_cycle_state:
                logger.info(
                    "Ignoring duplicate fresh lifecycle request because the current cycle "
                    "already has funnel state chat_id=%s funnel_version_id=%s state=%s",
                    chat.id,
                    active_funnel_version_id,
                    status_name,
                )
                return
            await self.bot_repo.reset_chat_state(chat.id)
            await self.funnel_runtime.reset_chat_state(chat.id)
            await self.funnel_runtime.start_funnel_for_chat(
                chat_id=chat.id,
                funnel_id=active_funnel_id,
                funnel_version_id=active_funnel_version_id,
                start_step_key=target_step_key,
            )
            return

        if start_requested:
            if status_name == "not_started":
                await self.bot_repo.reset_chat_state(chat.id)
                await self.funnel_runtime.start_funnel_for_chat(
                    chat_id=chat.id,
                    funnel_id=active_funnel_id,
                    funnel_version_id=active_funnel_version_id,
                    start_step_key=target_step_key,
                )
                return

            logger.info(
                "Ignoring repeated /start because funnel is %s chat_id=%s "
                "funnel_version_id=%s",
                status_name,
                chat.id,
                active_funnel_version_id,
            )
            return

        if status_name == "completed":
            logger.info(
                "No auto response after completed funnel chat_id=%s funnel_version_id=%s",
                chat.id,
                active_funnel_version_id,
            )
            return

        if status_name == "not_started":
            logger.info(
                "No auto response before funnel start chat_id=%s funnel_version_id=%s",
                chat.id,
                active_funnel_version_id,
            )
            return

        handled = await self.funnel_runtime.process_incoming_message(
            chat_id=chat.id,
            text=user_message.body or user_message.caption or user_message.message_type,
            message_type=user_message.message_type,
        )
        if not handled:
            logger.error(
                "Active funnel runtime did not handle in-progress message chat_id=%s "
                "funnel_version_id=%s",
                chat.id,
                active_funnel_version_id,
            )

    @staticmethod
    def _is_completed_state_from_previous_cycle(
        *,
        state: Any,
        cycle_started_at: datetime | None,
    ) -> bool:
        completed_at = getattr(state, "completed_at", None)
        if completed_at is None or cycle_started_at is None:
            return False
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=timezone.utc)
        if cycle_started_at.tzinfo is None:
            cycle_started_at = cycle_started_at.replace(tzinfo=timezone.utc)
        return completed_at < cycle_started_at

    async def _tracking_target_step_key(
        self,
        *,
        chat: Chat,
        active_funnel_id: UUID,
    ) -> str | None:
        if chat.tracking_link_id is None:
            return None
        link = await self.tracking_repo.get_link_by_id(chat.tracking_link_id)
        if (
            link is None
            or link.target_funnel_id != active_funnel_id
            or not link.target_funnel_step_key
        ):
            return None
        return link.target_funnel_step_key

    async def _process_callback_runtime_or_legacy(
        self,
        *,
        chat: Chat,
        project_id: UUID,
        bot_id: UUID,
        callback_query: TelegramCallbackQuery,
        user_message: MessageOut,
        fallback_text: str,
    ) -> None:
        bot = await self.bot_repo.get_active(bot_id)
        has_active_pointer = bool(
            bot is not None
            and bot.active_funnel_id is not None
            and bot.active_funnel_version_id is not None
        )
        active_funnel, active_version = await self.funnel_runtime.get_active_published_funnel_for_bot(
            bot_id,
            project_id,
        )

        if active_version is not None and active_funnel is not None:
            status_name, _ = await self.funnel_runtime.get_state_status(
                chat_id=chat.id,
                active_funnel_version_id=active_version.id,
            )
            logger.info(
                "Using active funnel runtime for callback bot_id=%s project_id=%s "
                "chat_id=%s funnel_id=%s funnel_version_id=%s state=%s",
                bot_id,
                project_id,
                chat.id,
                active_funnel.id,
                active_version.id,
                status_name,
            )
            if status_name in {"not_started", "completed"}:
                logger.info(
                    "Ignoring callback because funnel is %s chat_id=%s funnel_version_id=%s",
                    status_name,
                    chat.id,
                    active_version.id,
                )
                return
            try:
                handled = await self.funnel_runtime.process_incoming_button(
                    chat_id=chat.id,
                    callback_data=callback_query.data,
                    fallback_text=fallback_text,
                )
                if not handled:
                    logger.error(
                        "Active funnel runtime did not handle callback chat_id=%s "
                        "funnel_version_id=%s",
                        chat.id,
                        active_version.id,
                    )
            except Exception:
                logger.exception(
                    "Active funnel runtime failed for callback bot_id=%s project_id=%s "
                    "chat_id=%s funnel_id=%s funnel_version_id=%s",
                    bot_id,
                    project_id,
                    chat.id,
                    active_funnel.id,
                    active_version.id,
                )
            return

        if has_active_pointer:
            logger.error(
                "Active funnel pointer exists but no published runnable version was found "
                "for callback; legacy fallback is disabled bot_id=%s project_id=%s chat_id=%s "
                "active_funnel_id=%s active_funnel_version_id=%s",
                bot_id,
                project_id,
                chat.id,
                bot.active_funnel_id if bot else None,
                bot.active_funnel_version_id if bot else None,
            )
            return

        logger.info(
            "No active funnel, using legacy bot_engine fallback for callback "
            "bot_id=%s project_id=%s chat_id=%s",
            bot_id,
            project_id,
            chat.id,
        )
        await self.bot_engine.process_chat(chat.id, user_message=user_message)

    async def _handle_callback_query(
        self,
        callback_query: TelegramCallbackQuery,
        *,
        project_id: UUID,
        bot_id: UUID,
    ) -> None:
        if callback_query.message is None:
            return

        chat = await self.chat_repo.get_by_external(
            project_id,
            str(callback_query.message.chat.id),
            bot_id=bot_id,
        )
        if chat is None and callback_query.from_user is not None:
            username_key = self._normalize_username_key(
                callback_query.from_user.username
            )
            if username_key:
                external_chat_id = str(callback_query.message.chat.id)
                external_user_id = str(callback_query.from_user.id)
                try:
                    async with self.db.begin_nested():
                        chat = await self.chat_repo.claim_pending_import_identity(
                            project_id=project_id,
                            bot_id=bot_id,
                            username_key=username_key,
                            external_chat_id=external_chat_id,
                            external_user_id=external_user_id,
                            contact_name=compose_lead_name(
                                callback_query.from_user.first_name,
                                callback_query.from_user.last_name,
                            ),
                        )
                except IntegrityError:
                    chat = await self.chat_repo.get_by_external(
                        project_id,
                        external_chat_id,
                        bot_id=bot_id,
                    )
        if chat is None:
            logger.info(
                "Telegram callback for unknown chat project_id=%s bot_id=%s chat_id=%s",
                project_id,
                bot_id,
                callback_query.message.chat.id,
            )
            return

        token = await self.bot_repo.get_bot_token_by_id(bot_id, project_id)
        if token:
            await self.telegram_sender.answer_callback_query(token, callback_query.id)

        if chat.is_blocked:
            logger.info(
                "Ignored callback from blocked Telegram chat bot_id=%s project_id=%s chat_id=%s",
                bot_id,
                project_id,
                chat.id,
            )
            return

        active_funnel, active_version = await self.funnel_runtime.get_active_published_funnel_for_bot(
            bot_id,
            project_id,
        )
        selected_button = (
            await self.funnel_runtime.resolve_callback_button(
                chat_id=chat.id,
                callback_data=callback_query.data,
            )
            if active_version is not None and active_funnel is not None
            else None
        )
        selected_value = (selected_button or {}).get("value")
        body = selected_value or callback_query.data or "Нажата кнопка"
        msg = await self.message_service.create_message(
            chat_id=chat.id,
            project_id=project_id,
            data=MessageCreate(
                external_message_id=self._callback_message_external_id(callback_query),
                message_type=MessageType.TEXT,
                sender_type=SenderType.USER,
                sender_id=None,
                body=body,
                raw_payload_json=callback_query.model_dump(
                    mode="json",
                    by_alias=True,
                    exclude_none=True,
                ),
            ),
        )
        if not await self.message_repo.claim_funnel_processing([msg.id]):
            logger.info(
                "Ignored repeated Telegram callback chat_id=%s callback_data=%s",
                chat.id,
                callback_query.data,
            )
            return

        if callback_query.data and callback_query.data.startswith("bcf:"):
            handled = await self.broadcasts.process_start_funnel_callback(
                project_id=project_id,
                bot_id=bot_id,
                chat_id=chat.id,
                callback_data=callback_query.data,
            )
            if handled:
                return

        if selected_button and selected_button.get("hide_after_click") is True:
            await self.telegram_sender.edit_message_reply_markup(
                project_id,
                bot_id,
                chat.external_chat_id,
                callback_query.message.message_id,
            )

        await self._process_callback_runtime_or_legacy(
            chat=chat,
            project_id=project_id,
            bot_id=bot_id,
            callback_query=callback_query,
            user_message=msg,
            fallback_text=body,
        )

    @staticmethod
    def _callback_message_external_id(callback_query: TelegramCallbackQuery) -> str:
        source_message_id = (
            callback_query.message.message_id if callback_query.message is not None else 0
        )
        source = callback_query.data or callback_query.id
        digest = sha256(source.encode("utf-8")).hexdigest()[:24]
        return f"callback:{source_message_id}:{digest}"

    @classmethod
    def _telegram_username_key(cls, message: TelegramMessage) -> str | None:
        return cls._normalize_username_key(
            message.from_user.username if message.from_user is not None else None
        )

    @staticmethod
    def _normalize_username_key(value: str | None) -> str | None:
        normalized = str(value or "").strip().removeprefix("@").lower()
        return normalized or None

    @staticmethod
    def _contact_name_from_message(message: TelegramMessage) -> Optional[str]:
        if not message.from_user:
            return None
        return compose_lead_name(
            message.from_user.first_name,
            message.from_user.last_name,
        )

    @staticmethod
    def _telegram_profile_fields(message: TelegramMessage) -> tuple[str | None, str | None]:
        if message.from_user is None:
            return None, None
        return (
            normalize_name_part(message.from_user.first_name),
            normalize_name_part(message.from_user.last_name),
        )

    async def _resolve_tracking_link_id(
        self,
        start_payload: TelegramStartPayload,
        project_id: UUID,
        bot_id: UUID,
    ) -> Optional[UUID]:
        if start_payload.tracking_link_id is not None:
            link = await self.tracking_repo.get_link_by_id(start_payload.tracking_link_id)
            source = f"tracking_link_id={start_payload.tracking_link_id}"
        else:
            ref_code = start_payload.ref_code
            if ref_code is None:
                return None
            link = await self.tracking_repo.get_by_ref_code(ref_code, project_id)
            source = f"ref_code={ref_code}"
        if link is None:
            logger.info(
                "Telegram /start %s was not found for project_id=%s",
                source,
                project_id,
            )
            return None
        if link.project_id != project_id:
            logger.info(
                "Telegram /start %s belongs to project_id=%s, but update arrived for project_id=%s",
                source,
                link.project_id,
                project_id,
            )
            return None
        if getattr(link, "destination_type", "bot") != "bot":
            logger.info(
                "Telegram /start %s points to a non-bot destination",
                source,
            )
            return None
        if link.bot_id != bot_id:
            logger.info(
                "Telegram /start %s belongs to bot_id=%s, "
                "but update arrived for bot_id=%s",
                source,
                link.bot_id,
                bot_id,
            )
            return None
        return link.id

    async def _resolve_channel_tracking_link_id(
        self,
        *,
        project_id: UUID,
        telegram_user_id: int,
    ) -> UUID | None:
        attribution = await self._resolve_channel_tracking_attribution(
            project_id=project_id,
            telegram_user_id=telegram_user_id,
        )
        return attribution.tracking_link_id if attribution is not None else None

    async def _resolve_channel_tracking_attribution(
        self,
        *,
        project_id: UUID,
        telegram_user_id: int,
    ) -> ChannelTrackingAttribution | None:
        db = getattr(self, "db", None)
        if db is None or not hasattr(db, "execute"):
            return None
        return await ChannelSubscriptionService(db).resolve_latest_attribution(
            project_id=project_id,
            telegram_user_id=telegram_user_id,
        )

    @staticmethod
    def _has_explicit_start_attribution(payload: TelegramStartPayload) -> bool:
        return bool(
            getattr(payload, "tracking_link_id", None) is not None
            or getattr(payload, "ref_code", None) is not None
            or getattr(payload, "start_key", None) is not None
            or getattr(payload, "utm_key", None) is not None
        )

    @staticmethod
    def _extract_start_ref_code(text: Optional[str]) -> Optional[str]:
        return TelegramService._extract_start_payload(text).ref_code

    @classmethod
    def _extract_start_payload(cls, text: Optional[str]) -> TelegramStartPayload:
        if not text:
            return TelegramStartPayload()

        parts = text.strip().split(maxsplit=1)
        if not parts:
            return TelegramStartPayload()

        command = parts[0]
        if not cls._is_start_command(command):
            return TelegramStartPayload()
        if len(parts) == 1:
            return TelegramStartPayload()

        ref_code = parts[1].strip().split(maxsplit=1)[0]
        lander_payload = UtmBridgeService.parse_lander_start_payload(ref_code)
        if lander_payload is not None:
            tracking_link_id, start_key = lander_payload
            return TelegramStartPayload(
                tracking_link_id=tracking_link_id,
                start_key=start_key,
            )

        start_key = UtmBridgeService.normalize_start_key(ref_code)
        if start_key is not None:
            return TelegramStartPayload(start_key=start_key)
        if ref_code.startswith("ref_"):
            ref_code = ref_code.removeprefix("ref_")

        utm_key = None
        match = cls.START_UTM_SUFFIX_RE.match(ref_code)
        if match:
            ref_code = match.group("ref_code")
            utm_key = UtmBridgeService.normalize_utm_key(match.group("utm_key"))

        return TelegramStartPayload(ref_code=ref_code or None, utm_key=utm_key)

    async def _hydrate_start_payload(self, payload: TelegramStartPayload) -> TelegramStartPayload:
        if payload.start_key is None:
            return payload
        try:
            bridge = await self.utm_bridge.load_lander_start(payload.start_key)
        except Exception:
            logger.exception("Could not load landing start bridge key=%s", payload.start_key)
            return payload
        if bridge is None:
            logger.info("Landing start bridge data not found key=%s", payload.start_key)
            return payload
        ref_code, utm_data = bridge
        return replace(payload, ref_code=ref_code, utm_data=utm_data)

    @staticmethod
    def _is_start_command(text: Optional[str]) -> bool:
        if not text:
            return False
        command = text.strip().split(maxsplit=1)[0]
        return command == "/start" or command.startswith("/start@")

    async def _create_message(
        self,
        chat_id: UUID,
        project_id: UUID,
        message: TelegramMessage,
        *,
        tracking_link_id: UUID | None = None,
        source_transport: str = "bot_api",
    ) -> MessageOut:
        """
        Persist the Telegram message via MessageService (includes idempotency,
        SAVEPOINT, and chat timestamp update).

        message.text may be None for stickers, photos, etc. Media metadata is
        stored for lazy proxy access; files are not downloaded here.
        """
        data = self._telegram_message_to_create(
            message,
            source_transport=source_transport,
        ).model_copy(
            update={"tracking_link_id": tracking_link_id}
        )
        if message.reply_to_message is not None:
            reply_target = await self.message_repo.get_by_external_id(
                chat_id,
                str(message.reply_to_message.message_id),
            )
            if reply_target is not None:
                data = data.model_copy(
                    update={"reply_to_message_id": reply_target.id}
                )
        return await self.message_service.create_message(
            chat_id=chat_id,
            project_id=project_id,
            data=data,
        )

    @staticmethod
    def _telegram_message_to_create(
        message: TelegramMessage,
        *,
        source_transport: str = "bot_api",
    ) -> MessageCreate:
        raw_payload = message.model_dump(mode="json", by_alias=True, exclude_none=True)
        raw_payload["_transport"] = source_transport
        base = {
            "external_message_id": str(message.message_id),
            "sender_type": SenderType.USER,
            "sender_id": None,
            "raw_payload_json": raw_payload,
        }

        if message.text is not None:
            return MessageCreate(
                **base,
                message_type=MessageType.TEXT,
                body=message.text,
            )

        if message.contact is not None:
            return MessageCreate(
                **base,
                message_type=MessageType.CONTACT,
                body=message.contact.phone_number,
            )

        if message.photo:
            photo = max(message.photo, key=lambda item: item.file_size or 0)
            if photo.local_path:
                raw_payload["mtproto_media_path"] = photo.local_path
            return MessageCreate(
                **base,
                message_type=MessageType.PHOTO,
                body=None,
                caption=message.caption,
                telegram_file_id=photo.file_id,
                file_unique_id=photo.file_unique_id,
                file_size=photo.file_size,
                media_group_id=message.media_group_id,
            )

        media_specs = [
            (MessageType.VIDEO, message.video),
            (MessageType.VOICE, message.voice),
            (MessageType.VIDEO_NOTE, message.video_note),
            (MessageType.DOCUMENT, message.document),
            (MessageType.AUDIO, message.audio),
            (MessageType.STICKER, message.sticker),
            (MessageType.ANIMATION, message.animation),
        ]
        for message_type, media in media_specs:
            if media is None:
                continue
            if media.local_path:
                raw_payload["mtproto_media_path"] = media.local_path
            return MessageCreate(
                **base,
                message_type=message_type,
                body=None,
                caption=message.caption,
                telegram_file_id=media.file_id,
                file_unique_id=media.file_unique_id,
                file_name=getattr(media, "file_name", None),
                mime_type=getattr(media, "mime_type", None),
                file_size=media.file_size,
                media_group_id=message.media_group_id,
            )

        return MessageCreate(
            **base,
            message_type=MessageType.UNKNOWN,
            body=None,
        )

    async def _find_or_create_lead(
        self,
        chat_id: UUID,
        project_id: UUID,
        message: TelegramMessage,
        *,
        reset_existing: bool = False,
    ) -> Optional[Lead]:
        """
        Ensure a Lead exists for this chat. If the chat already has a lead,
        this is a no-op. If not, create one with status=new.

        SAVEPOINT pattern mirrors _find_or_create_chat().
        """
        # Fast path: lead already exists for this chat
        existing = (
            await self.lead_repo.get_any_by_chat(chat_id, project_id)
            if reset_existing
            else await self.lead_repo.get_by_chat(chat_id, project_id)
        )
        if existing is not None:
            if reset_existing:
                username = (
                    message.from_user.username
                    if message.from_user and message.from_user.username
                    else None
                )
                first_name, last_name = self._telegram_profile_fields(message)
                profile_custom_fields = {
                    key: value
                    for key, value in {
                        "first_name": first_name,
                        "last_name": last_name,
                    }.items()
                    if value
                }
                if (existing.custom_fields or {}).get("__crm_name_override") is True:
                    first_name, last_name = resolve_lead_names(existing)
                    profile_custom_fields = {
                        "__crm_name_override": True,
                        **{
                            key: value
                            for key, value in {
                                "first_name": first_name,
                                "last_name": last_name,
                            }.items()
                            if value
                        },
                    }
                reset_lead = await self.lead_repo.reset_existing_for_new_cycle(
                    existing.id,
                    project_id,
                    username=username,
                    name=compose_lead_name(first_name, last_name),
                    custom_fields=profile_custom_fields,
                )
                if reset_lead is None:
                    logger.error(
                        "Could not reset lead for new Telegram cycle chat_id=%s project_id=%s",
                        chat_id,
                        project_id,
                    )
                    return existing
                return reset_lead
            return await self._sync_lead_telegram_profile(existing, message, project_id)

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
            return None

        username: Optional[str] = None
        if message.from_user and message.from_user.username:
            username = message.from_user.username
        first_name, last_name = self._telegram_profile_fields(message)
        custom_fields = {
            key: value
            for key, value in {
                "first_name": first_name,
                "last_name": last_name,
            }.items()
            if value
        }

        try:
            async with self.db.begin_nested():
                lead = await self.lead_repo.create(
                    project_id=project_id,
                    chat_id=chat_id,
                    status_id=new_status.id,
                    name=compose_lead_name(first_name, last_name),
                    username=username,
                    custom_fields=custom_fields,
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
            return lead
        except IntegrityError:
            # Concurrent webhook delivery created the lead first — that's fine.
            logger.debug(
                "Concurrent lead create for chat_id=%s project_id=%s — already exists",
                chat_id,
                project_id,
            )
            return await self.lead_repo.get_by_chat(chat_id, project_id)

    async def _sync_lead_telegram_profile(
        self,
        lead: Lead,
        message: TelegramMessage,
        project_id: UUID,
    ) -> Lead:
        first_name, last_name = self._telegram_profile_fields(message)
        if not first_name and not last_name:
            return lead

        custom_fields = dict(lead.custom_fields or {})
        if custom_fields.get("__crm_name_override") is True:
            return lead
        changed = False
        if first_name and not normalize_name_part(custom_fields.get("first_name")):
            custom_fields["first_name"] = first_name
            changed = True
        if last_name and not normalize_name_part(custom_fields.get("last_name")):
            custom_fields["last_name"] = last_name
            changed = True
        if not changed:
            return lead

        updated = await self.lead_repo.update_contact(
            lead.id,
            project_id,
            name=compose_lead_name(
                custom_fields.get("first_name"),
                custom_fields.get("last_name"),
            ),
            custom_fields=custom_fields,
        )
        return updated or lead

    async def _attach_utm_bridge_data(
        self,
        lead: Optional[Lead],
        utm_key: Optional[str],
        utm_data: Optional[dict[str, Any]] = None,
    ) -> None:
        if lead is None:
            return

        fb_data = utm_data
        if fb_data is None and utm_key is not None:
            try:
                fb_data = await self.utm_bridge.load_query_params(utm_key)
            except Exception:
                logger.exception("Could not load UTM bridge data key=%s", utm_key)
                return
        if not fb_data:
            logger.info("UTM bridge data not found or empty lead_id=%s", lead.id)
            return

        custom_fields = dict(lead.custom_fields or {})
        custom_fields["fb_data"] = fb_data
        await self.lead_repo.update_contact(
            lead.id,
            lead.project_id,
            custom_fields=custom_fields,
        )
        logger.info("Attached UTM bridge data key=%s lead_id=%s", utm_key, lead.id)
