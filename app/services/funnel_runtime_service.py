from __future__ import annotations

import logging
import re
from hashlib import sha256
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AuditAction, ChatEventType, EntityType, LeadStatusCode, MessageType, RoleName, SenderType
from app.models.user import User
from app.models.funnel import FunnelScheduledJob, FunnelStep, FunnelVersion
from app.repositories.bot_repository import BotRepository
from app.repositories.broadcast_repository import BroadcastRepository
from app.repositories.chat_repository import ChatRepository
from app.repositories.funnel_repository import FunnelRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.partner_repository import PartnerIntegrationRepository
from app.repositories.tag_repository import TagRepository
from app.repositories.tracking_repository import TrackingLinkRepository
from app.schemas.message import MessageCreate
from app.services.chat_audit_service import ChatAuditService
from app.services.audit_service import AuditService
from app.services.facebook_capi_queue import enqueue_facebook_capi_event
from app.services.facebook_capi_service import FacebookCAPIError, FacebookCAPIService
from app.services.funnel_block_registry import is_supported_lead_field_key
from app.services.funnel_job_queue import enqueue_funnel_scheduled_job
from app.services.lead_scoring_service import LeadScoringService
from app.services.telegram_sender import TelegramSenderService

logger = logging.getLogger(__name__)


DIRECT_LEAD_FIELDS = {
    "name",
    "phone",
    "username",
    "age",
    "country",
    "call_time_text",
    "preferred_call_time",
    "has_card",
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9\s().-]{8,24}$")
MANUAL_STATUS_CODE_CANDIDATES = (
    "manual_processing",
    "manual",
    "operator",
    "operator_required",
)


class FunnelRuntimeService:
    """
    Runtime foundation for published funnel execution.

    v1 deliberately does not replace Telegram webhook or bot_engine_service.
    It provides safe primitives for future worker/webhook integration:
    state start/read/move, field mappings, and stuck-chat lookup for push rules.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = FunnelRepository(db)
        self.broadcast_repo = BroadcastRepository(db)
        self.chat_repo = ChatRepository(db)
        self.bot_repo = BotRepository(db)
        self.lead_repo = LeadRepository(db)
        self.partner_repo = PartnerIntegrationRepository(db)
        self.tag_repo = TagRepository(db)
        self.tracking_link_repo = TrackingLinkRepository(db)
        from app.services.message_service import MessageService

        self.message_service = MessageService(db)
        self.scoring = LeadScoringService(db)
        self.chat_audit = ChatAuditService(db)
        self.telegram_sender = TelegramSenderService(db)
        self.audit = AuditService(db)

    async def get_published_funnel_for_bot(self, bot_id: UUID) -> Optional[FunnelVersion]:
        return await self.repo.get_published_for_bot(bot_id)

    async def get_active_published_funnel_for_bot(
        self,
        bot_id: UUID,
        project_id: UUID,
    ) -> tuple[Optional[Any], Optional[FunnelVersion]]:
        return await self.repo.get_active_published_funnel_for_bot(bot_id, project_id)

    async def reset_chat_state(self, chat_id: UUID) -> None:
        await self.repo.reset_chat_funnel_state(chat_id)

    async def get_state_status(
        self,
        *,
        chat_id: UUID,
        active_funnel_version_id: UUID,
    ) -> tuple[str, Any]:
        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None:
            return "not_started", state
        # A running chat is pinned to the version that started it. Switching a
        # bot's active funnel only affects fresh lifecycles, never a live dialog.
        if state.completed_at is not None:
            return "completed", state
        if state.is_paused:
            return "paused", state

        step = await self.repo.get_step(state.current_step_id)
        if state.waiting_for_answer or (step is not None and self._is_input_step(step)):
            return "waiting_for_answer", state
        return "in_progress", state

    async def start_funnel_for_chat(
        self,
        *,
        chat_id: UUID,
        funnel_id: UUID,
        funnel_version_id: UUID,
        start_step_key: str | None = None,
    ) -> Optional[FunnelStep]:
        existing = await self.repo.get_chat_funnel_state(chat_id)
        if existing is not None and existing.is_paused and existing.completed_at is None:
            return await self.repo.get_step(existing.current_step_id)

        steps = await self.repo.list_steps(funnel_version_id)
        trigger = next((step for step in steps if step.step_type == "trigger"), None)
        if trigger is None:
            logger.error(
                "Active funnel runtime cannot start: no trigger step "
                "chat_id=%s funnel_id=%s funnel_version_id=%s",
                chat_id,
                funnel_id,
                funnel_version_id,
            )
            return None
        initial_step = trigger
        if start_step_key:
            target_step = next((step for step in steps if step.key == start_step_key), None)
            if target_step is None:
                logger.warning(
                    "Tracking target step was not found; falling back to trigger chat_id=%s "
                    "funnel_id=%s funnel_version_id=%s target_step_key=%s",
                    chat_id,
                    funnel_id,
                    funnel_version_id,
                    start_step_key,
                )
            else:
                initial_step = target_step
        await self.repo.upsert_chat_funnel_state(
            chat_id=chat_id,
            funnel_id=funnel_id,
            funnel_version_id=funnel_version_id,
            current_step_id=initial_step.id,
            entered_step_at=datetime.now(timezone.utc),
            waiting_for_answer=False,
            is_paused=False,
            runtime_json={},
        )
        await self._log_runtime_step(chat_id=chat_id, step=initial_step, status="success")
        logger.info(
            "Starting active funnel chat_id=%s funnel_id=%s funnel_version_id=%s start_step_id=%s",
            chat_id,
            funnel_id,
            funnel_version_id,
            initial_step.id,
        )
        return await self._execute_from_step(chat_id=chat_id, step=initial_step)

    async def get_current_step(self, chat_id: UUID) -> Optional[FunnelStep]:
        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None or state.completed_at is not None:
            return None
        return await self.repo.get_step(state.current_step_id)

    async def pause_for_manager_assignment(
        self,
        *,
        chat_id: UUID,
        project_id: UUID,
        actor_id: UUID,
    ) -> bool:
        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None or state.completed_at is not None:
            return False
        if state.is_paused:
            return True

        await self.repo.cancel_scheduled_jobs_for_chat(chat_id=chat_id)
        await self.repo.set_chat_funnel_paused(
            chat_id=chat_id,
            is_paused=True,
            paused_at=datetime.now(timezone.utc),
            paused_by_user_id=actor_id,
        )
        await self.audit.log(
            project_id=project_id,
            action=AuditAction.CHAT_FUNNEL_PAUSED,
            entity_type=EntityType.CHAT,
            entity_id=chat_id,
            actor_id=actor_id,
            meta={"funnel_id": str(state.funnel_id), "step_id": str(state.current_step_id)},
        )
        return True

    async def get_manager_funnel_control(
        self,
        *,
        chat_id: UUID,
        project_id: UUID,
    ) -> dict[str, Any]:
        chat = await self.chat_repo.get_active(chat_id, project_id)
        if chat is None:
            return {"is_available": False, "is_paused": False, "steps": []}

        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None or state.completed_at is not None:
            return {"is_available": False, "is_paused": False, "steps": []}

        funnel = await self.repo.get_in_project(state.funnel_id, project_id)
        if funnel is None:
            return {"is_available": False, "is_paused": False, "steps": []}
        current_step = await self.repo.get_step(state.current_step_id)
        steps = await self.repo.list_steps(state.funnel_version_id)
        return {
            "is_available": True,
            "is_paused": state.is_paused,
            "funnel_id": state.funnel_id,
            "funnel_name": funnel.name,
            "current_step_id": state.current_step_id,
            "current_step_title": current_step.title if current_step is not None else None,
            "steps": [
                {
                    "id": step.id,
                    "title": step.title,
                    "step_type": step.step_type,
                    "block_type": step.block_type,
                }
                for step in steps
                if step.step_type != "trigger"
            ],
        }

    async def resume_from_manager_step(
        self,
        *,
        chat_id: UUID,
        project_id: UUID,
        step_id: UUID,
        actor: User,
    ) -> Optional[FunnelStep]:
        chat = await self.chat_repo.get_active(chat_id, project_id)
        if chat is None:
            return None
        lead = await self.repo.get_lead_by_chat(chat_id)
        if actor.role_name == RoleName.MANAGER and (lead is None or lead.manager_id != actor.id):
            raise PermissionError("Only the assigned manager can resume this funnel.")

        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None or state.completed_at is not None or not state.is_paused:
            return None
        step = await self.repo.get_step(step_id)
        if step is None or step.funnel_version_id != state.funnel_version_id:
            return None

        await self.repo.cancel_scheduled_jobs_for_chat(chat_id=chat_id)
        await self.repo.upsert_chat_funnel_state(
            chat_id=chat_id,
            funnel_id=state.funnel_id,
            funnel_version_id=state.funnel_version_id,
            current_step_id=step.id,
            entered_step_at=datetime.now(timezone.utc),
            waiting_for_answer=False,
            is_paused=False,
            runtime_json={},
        )
        await self.audit.log(
            project_id=project_id,
            action=AuditAction.CHAT_FUNNEL_RESUMED,
            entity_type=EntityType.CHAT,
            entity_id=chat_id,
            actor_id=actor.id,
            meta={"funnel_id": str(state.funnel_id), "step_id": str(step.id)},
        )
        return await self._execute_from_step(chat_id=chat_id, step=step)

    async def process_user_answer(
        self,
        *,
        chat_id: UUID,
        text: Optional[str] = None,
        button_payload: Optional[str] = None,
    ) -> Optional[FunnelStep]:
        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None or state.completed_at is not None or state.is_paused:
            return None

        answer = button_payload if button_payload is not None else text
        step = await self.repo.get_step(state.current_step_id)
        if step is not None and self._is_input_step(step):
            validation = self._validate_input_answer(step, answer)
            if not validation["valid"]:
                await self._create_outgoing_message(
                    chat_id=chat_id,
                    text=self._input_retry_message(step),
                    reply_markup=self._reply_markup_for_step(step),
                )
                return step
            await self._save_input_answer(chat_id=chat_id, step=step, answer=answer)
        await self.apply_field_mappings(
            chat_id=chat_id,
            step_id=state.current_step_id,
            answer=answer,
        )
        edge = await self.repo.first_edge_from_step(state.current_step_id)
        if edge is None:
            await self.repo.upsert_chat_funnel_state(
                chat_id=chat_id,
                funnel_id=state.funnel_id,
                funnel_version_id=state.funnel_version_id,
                current_step_id=state.current_step_id,
                entered_step_at=state.entered_step_at,
                completed_at=datetime.now(timezone.utc),
            )
            return None
        return await self.move_to_next_step(chat_id=chat_id, edge_id=edge.id)

    async def process_incoming_message(
        self,
        *,
        chat_id: UUID,
        text: Optional[str],
    ) -> bool:
        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None:
            return False
        if state.is_paused:
            return True
        if state.completed_at is not None:
            logger.info(
                "No auto response after completed funnel chat_id=%s funnel_id=%s "
                "funnel_version_id=%s",
                chat_id,
                state.funnel_id,
                state.funnel_version_id,
            )
            return True

        step = await self.repo.get_step(state.current_step_id)
        if step is None:
            return False

        if state.waiting_for_answer and self._is_message_step(step):
            message_index = self._waiting_message_index(step, state.runtime_json)
            messages = self._message_sequence(step)
            item = messages[message_index] if message_index is not None else None
            if item is not None and self._buttons_from_message_item(item):
                logger.info(
                    "Ignoring text while funnel message waits for button callback "
                    "chat_id=%s step_id=%s",
                    chat_id,
                    step.id,
                )
                return True
            if item is not None and self._message_item_waits_for_answer(item):
                await self.apply_field_mappings(chat_id=chat_id, step_id=step.id, answer=text)
                await self._log_step_event(chat_id=chat_id, step=step, event_type="answered")
                runtime_json = self._runtime_with_answer(
                    state.runtime_json,
                    step_id=step.id,
                    answer=text,
                )
                await self.repo.upsert_chat_funnel_state(
                    chat_id=chat_id,
                    funnel_id=state.funnel_id,
                    funnel_version_id=state.funnel_version_id,
                    current_step_id=step.id,
                    entered_step_at=state.entered_step_at,
                    waiting_for_answer=False,
                    runtime_json=runtime_json,
                )
                next_step = await self._execute_message_sequence(
                    chat_id=chat_id,
                    step=step,
                    start_index=(message_index or 0) + 1,
                    answer=text,
                )
                if next_step is not None:
                    if next_step.id != step.id:
                        await self._execute_from_step(chat_id=chat_id, step=next_step, answer=text)
                return True
            logger.info(
                "Ignoring text while funnel message is in waiting state without free-answer mode "
                "chat_id=%s step_id=%s",
                chat_id,
                step.id,
            )
            return True

        if state.waiting_for_answer or self._is_input_step(step):
            if self._is_input_prompt_pending(state.runtime_json, step):
                logger.info(
                    "Ignoring incoming text while input prompt is delayed chat_id=%s step_id=%s",
                    chat_id,
                    step.id,
                )
                return True
            if await self._should_override_call_time_for_hold(chat_id=chat_id, step=step):
                next_step = await self._apply_hold_call_time_override(
                    chat_id=chat_id,
                    step=step,
                    state=state,
                )
                if next_step is not None:
                    await self._execute_from_step(
                        chat_id=chat_id,
                        step=next_step,
                        answer=self._hold_call_time_answer(step),
                    )
                return True

            validation = self._validate_input_answer(step, text)
            if not validation["valid"]:
                retry_count = self._input_retry_count(state.runtime_json, step.id) + 1
                max_retries = self._input_max_retries(step)
                runtime_json = self._runtime_with_retry_count(
                    state.runtime_json,
                    step.id,
                    retry_count,
                )
                await self.repo.update_chat_funnel_runtime(
                    chat_id=chat_id,
                    runtime_json=runtime_json,
                )
                if retry_count <= max_retries:
                    await self._create_outgoing_message(
                        chat_id=chat_id,
                        text=self._input_retry_message(step),
                        reply_markup=self._reply_markup_for_step(step),
                    )
                    logger.info(
                        "Input validation failed; retrying chat_id=%s step_id=%s retry=%s",
                        chat_id,
                        step.id,
                        retry_count,
                    )
                    return True
                logger.info(
                    "Input validation retries exhausted chat_id=%s step_id=%s",
                    chat_id,
                    step.id,
                )
                await self.repo.upsert_chat_funnel_state(
                    chat_id=chat_id,
                    funnel_id=state.funnel_id,
                    funnel_version_id=state.funnel_version_id,
                    current_step_id=step.id,
                    entered_step_at=state.entered_step_at,
                    waiting_for_answer=False,
                    runtime_json=runtime_json,
                )
                next_step = await self._move_to_config_target_or_next(
                    chat_id=chat_id,
                    step=step,
                    target_key="timeout_target_step_id",
                    answer="timeout",
                )
                if next_step is not None:
                    await self._execute_from_step(chat_id=chat_id, step=next_step, answer=text)
                return True

            await self._save_input_answer(chat_id=chat_id, step=step, answer=text)
            await self.apply_field_mappings(chat_id=chat_id, step_id=step.id, answer=text)
            await self._log_step_event(chat_id=chat_id, step=step, event_type="answered")
            runtime_json = self._runtime_with_answer(
                state.runtime_json,
                step_id=step.id,
                answer=text,
            )
            await self.repo.upsert_chat_funnel_state(
                chat_id=chat_id,
                funnel_id=state.funnel_id,
                funnel_version_id=state.funnel_version_id,
                current_step_id=step.id,
                entered_step_at=state.entered_step_at,
                waiting_for_answer=False,
                runtime_json=runtime_json,
            )
            choice = self._choice_for_answer(step, text)
            if choice and choice.get("target_step_id"):
                next_step = await self._move_to_step_id(
                    chat_id=chat_id,
                    target_step_id=choice.get("target_step_id"),
                    from_step=step,
                )
            else:
                next_step = await self._move_from_step(
                    chat_id=chat_id,
                    step=step,
                    answer=text,
                )
            if next_step is not None:
                await self._execute_from_step(chat_id=chat_id, step=next_step, answer=text)
            return True

        if self._is_no_reply_delay_step(step):
            runtime_json = dict(state.runtime_json or {})
            runtime_json.setdefault("no_reply", {})[str(step.id)] = {"replied": True}
            await self.repo.update_chat_funnel_runtime(
                chat_id=chat_id,
                runtime_json=runtime_json,
            )
            logger.info(
                "No-reply timer received user message; pending job will be ignored chat_id=%s step_id=%s",
                chat_id,
                step.id,
            )
            return True

        if self._step_has_buttons(step):
            logger.info(
                "Ignoring text while funnel waits for button callback chat_id=%s step_id=%s",
                chat_id,
                step.id,
            )
            return True

        logger.info(
            "No auto response for in-progress funnel step that is not waiting "
            "chat_id=%s step_id=%s step_type=%s block_type=%s",
            chat_id,
            step.id,
            step.step_type,
            step.block_type,
        )
        return True

    async def process_incoming_button(
        self,
        *,
        chat_id: UUID,
        callback_data: Optional[str],
        fallback_text: Optional[str] = None,
    ) -> bool:
        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None:
            return False
        if state.is_paused:
            return True
        if state.completed_at is not None:
            logger.info(
                "No auto response after completed funnel callback chat_id=%s funnel_id=%s "
                "funnel_version_id=%s",
                chat_id,
                state.funnel_id,
                state.funnel_version_id,
            )
            return True

        step = await self.repo.get_step(state.current_step_id)
        if step is None:
            return False

        if self._is_input_step(step) and await self._should_override_call_time_for_hold(
            chat_id=chat_id,
            step=step,
        ):
            next_step = await self._apply_hold_call_time_override(
                chat_id=chat_id,
                step=step,
                state=state,
            )
            if next_step is not None:
                await self._execute_from_step(
                    chat_id=chat_id,
                    step=next_step,
                    answer=self._hold_call_time_answer(step),
                )
            return True

        payload_step_id, _, _ = self._parse_callback_data(callback_data)
        if payload_step_id is not None and payload_step_id != step.id:
            logger.info(
                "Ignoring stale funnel callback chat_id=%s state_step=%s payload_step=%s",
                chat_id,
                step.id,
                payload_step_id,
            )
            return True

        button = await self.resolve_callback_button(
            chat_id=chat_id,
            callback_data=callback_data,
        )
        answer = (button or {}).get("value") or fallback_text
        answer = answer or fallback_text

        if self._is_input_step(step):
            if self._is_input_prompt_pending(state.runtime_json, step):
                logger.info(
                    "Ignoring callback while input prompt is delayed chat_id=%s step_id=%s",
                    chat_id,
                    step.id,
                )
                return True
            validation = self._validate_input_answer(step, answer)
            if not validation["valid"]:
                await self._create_outgoing_message(
                    chat_id=chat_id,
                    text=self._input_retry_message(step),
                    reply_markup=self._reply_markup_for_step(step),
                )
                return True
            await self._save_input_answer(chat_id=chat_id, step=step, answer=answer)
            await self.apply_field_mappings(
                chat_id=chat_id,
                step_id=step.id,
                answer=answer,
            )
            await self._log_step_event(chat_id=chat_id, step=step, event_type="answered")
        runtime_json = self._runtime_with_answer(
            state.runtime_json,
            step_id=step.id,
            answer=answer,
            button=button,
        )
        await self.repo.upsert_chat_funnel_state(
            chat_id=chat_id,
            funnel_id=state.funnel_id,
            funnel_version_id=state.funnel_version_id,
            current_step_id=step.id,
            entered_step_at=state.entered_step_at,
            waiting_for_answer=False,
            runtime_json=runtime_json,
        )

        if button and button.get("target_step_id"):
            next_step = await self._move_to_step_id(
                chat_id=chat_id,
                target_step_id=button.get("target_step_id"),
                from_step=step,
            )
        else:
            next_step = await self._move_from_step(chat_id=chat_id, step=step, answer=answer)
        if next_step is not None:
            await self._execute_from_step(chat_id=chat_id, step=next_step, answer=answer)
        return True

    async def resolve_callback_value(
        self,
        *,
        chat_id: UUID,
        callback_data: Optional[str],
    ) -> Optional[str]:
        button = await self.resolve_callback_button(chat_id=chat_id, callback_data=callback_data)
        return button.get("value") if button else None

    async def resolve_callback_button(
        self,
        *,
        chat_id: UUID,
        callback_data: Optional[str],
    ) -> Optional[dict[str, Any]]:
        step_id, message_index, button_index = self._parse_callback_data(callback_data)
        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None or state.is_paused:
            return None
        step = await self.repo.get_step(step_id or state.current_step_id)
        if step is None:
            return None
        buttons = self._buttons_from_step(step, message_index=message_index)
        if button_index is None or button_index < 0 or button_index >= len(buttons):
            return None
        return buttons[button_index]

    async def apply_field_mappings(
        self,
        *,
        chat_id: UUID,
        step_id: UUID,
        answer: Any,
    ) -> None:
        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None:
            return
        mappings = await self.repo.list_field_mappings(state.funnel_version_id)
        relevant = [mapping for mapping in mappings if mapping.step_id == step_id]
        step = await self.repo.get_step(step_id)
        lead = await self.repo.get_lead_by_chat(chat_id)
        if lead is None:
            return

        direct_values: dict[str, Any] = {}
        custom_values: dict[str, Any] = {}
        if step is not None:
            save_to = self._normalize_field_key(step.config_json.get("save_to"))
            if save_to and is_supported_lead_field_key(save_to):
                value = self._transform_value(save_to, answer)
                if save_to in DIRECT_LEAD_FIELDS:
                    direct_values[save_to] = value
                else:
                    custom_values[save_to] = value

        for mapping in relevant:
            if not is_supported_lead_field_key(mapping.lead_field_key):
                continue
            value = self._transform_value(mapping.lead_field_key, answer)
            if value is None and mapping.is_required:
                continue
            if mapping.lead_field_key in DIRECT_LEAD_FIELDS:
                direct_values[mapping.lead_field_key] = value
            else:
                custom_values[mapping.lead_field_key] = value

        await self.repo.update_lead_mapped_fields(lead.id, direct_values, custom_values)
        if direct_values or custom_values:
            await self.scoring.update_lead_score(lead.id)

    async def move_to_next_step(self, *, chat_id: UUID, edge_id: UUID) -> Optional[FunnelStep]:
        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None:
            return None
        edges = await self.repo.list_edges(state.funnel_version_id)
        edge = next((item for item in edges if item.id == edge_id), None)
        if edge is None:
            return None
        next_step = await self.repo.get_step(edge.to_step_id)
        if next_step is None:
            return None

        completed_at = datetime.now(timezone.utc) if next_step.step_type == "finish" else None
        logger.info(
            "Moving funnel step chat_id=%s from_step_id=%s to_step_id=%s "
            "funnel_version_id=%s",
            chat_id,
            edge.from_step_id,
            next_step.id,
            state.funnel_version_id,
        )
        await self.repo.upsert_chat_funnel_state(
            chat_id=chat_id,
            funnel_id=state.funnel_id,
            funnel_version_id=state.funnel_version_id,
            current_step_id=next_step.id,
            entered_step_at=datetime.now(timezone.utc),
            waiting_for_answer=False,
            completed_at=completed_at,
        )
        await self._log_runtime_step(chat_id=chat_id, step=next_step, status="success")
        return next_step

    async def find_stuck_chats_for_push_rules(self):
        return await self.repo.find_stuck_chats_for_push_rules()

    async def mark_push_sent(self, *, chat_id: UUID, push_rule_id: UUID) -> None:
        # Placeholder for a future audit/event table. Keeping the method in place
        # lets the worker call a stable API without inventing runtime writes later.
        _ = (chat_id, push_rule_id)

    async def process_scheduled_job(self, job: FunnelScheduledJob) -> None:
        state = await self.repo.get_chat_funnel_state(job.chat_id)
        if (
            state is None
            or state.completed_at is not None
            or state.is_paused
            or state.funnel_version_id != job.funnel_version_id
            or state.current_step_id != job.step_id
        ):
            logger.info(
                "Ignoring stale funnel scheduled job job_id=%s job_type=%s chat_id=%s",
                job.id,
                job.job_type,
                job.chat_id,
            )
            return

        step = await self.repo.get_step(job.step_id)
        if step is None:
            logger.warning("Scheduled funnel job references missing step job_id=%s", job.id)
            return

        if job.job_type == "message_sequence":
            index = int((job.payload_json or {}).get("message_index") or 0)
            next_step = await self._execute_message_sequence(
                chat_id=job.chat_id,
                step=step,
                start_index=index,
                skip_delay_at_start=True,
            )
            if next_step is not None and next_step.id != step.id:
                await self._execute_from_step(chat_id=job.chat_id, step=next_step)
            return

        if job.job_type == "input_timeout":
            if not (state.waiting_for_answer or self._is_input_step(step)):
                logger.info("Ignoring input timeout; state is no longer waiting job_id=%s", job.id)
                return
            await self.repo.upsert_chat_funnel_state(
                chat_id=job.chat_id,
                funnel_id=state.funnel_id,
                funnel_version_id=state.funnel_version_id,
                current_step_id=step.id,
                entered_step_at=state.entered_step_at,
                waiting_for_answer=False,
            )
            next_step = await self._move_to_config_target_or_next(
                chat_id=job.chat_id,
                step=step,
                target_key="timeout_target_step_id",
                answer="timeout",
            )
            if next_step is not None:
                await self._execute_from_step(chat_id=job.chat_id, step=next_step, answer="timeout")
            return

        if job.job_type == "input_prompt":
            if not self._is_input_step(step):
                logger.info("Ignoring input prompt job for non-input step job_id=%s", job.id)
                return
            runtime_json = dict(state.runtime_json or {})
            runtime_json.pop("input_prompt_pending_step_id", None)
            await self.repo.upsert_chat_funnel_state(
                chat_id=job.chat_id,
                funnel_id=state.funnel_id,
                funnel_version_id=state.funnel_version_id,
                current_step_id=step.id,
                entered_step_at=state.entered_step_at,
                waiting_for_answer=True,
                runtime_json=runtime_json,
            )
            await self._send_input_prompt(chat_id=job.chat_id, step=step)
            await self._schedule_input_timeout(chat_id=job.chat_id, step=step)
            return

        if job.job_type == "delay_step":
            next_step = await self._move_to_config_target_or_next(
                chat_id=job.chat_id,
                step=step,
                target_key="target_step_id",
                answer="delay",
            )
            if next_step is not None:
                await self._execute_from_step(chat_id=job.chat_id, step=next_step, answer="delay")
            return

        if job.job_type == "no_reply_timeout":
            runtime_json = state.runtime_json or {}
            no_reply = runtime_json.get("no_reply") if isinstance(runtime_json, dict) else {}
            marker = no_reply.get(str(step.id)) if isinstance(no_reply, dict) else None
            if isinstance(marker, dict) and marker.get("replied"):
                logger.info("Ignoring no-reply timeout because user replied job_id=%s", job.id)
                return
            next_step = await self._move_to_config_target_or_next(
                chat_id=job.chat_id,
                step=step,
                target_key="target_step_id",
                answer="timeout",
            )
            if next_step is not None:
                await self._execute_from_step(chat_id=job.chat_id, step=next_step, answer="timeout")
            return

        logger.warning("Unsupported funnel scheduled job type job_id=%s job_type=%s", job.id, job.job_type)

    async def _execute_from_step(
        self,
        *,
        chat_id: UUID,
        step: FunnelStep,
        answer: Optional[str] = None,
    ) -> Optional[FunnelStep]:
        current = step
        guard = 0

        while guard < 32:
            guard += 1
            state = await self.repo.get_chat_funnel_state(chat_id)
            if state is None:
                return None
            if state.is_paused:
                return await self.repo.get_step(state.current_step_id)

            await self.repo.upsert_chat_funnel_state(
                chat_id=chat_id,
                funnel_id=state.funnel_id,
                funnel_version_id=state.funnel_version_id,
                current_step_id=current.id,
                entered_step_at=datetime.now(timezone.utc),
                waiting_for_answer=False,
            )
            await self._log_step_event(chat_id=chat_id, step=current, event_type="entered")

            if current.step_type == "trigger":
                next_step = await self._move_from_step(
                    chat_id=chat_id,
                    step=current,
                    answer=answer,
                )
                if next_step is None:
                    logger.error(
                        "Active funnel runtime cannot continue: trigger has no outgoing edge "
                        "chat_id=%s step_id=%s funnel_version_id=%s",
                        chat_id,
                        current.id,
                        state.funnel_version_id,
                    )
                    return None
                current = next_step
                continue

            if self._is_message_step(current):
                next_step = await self._execute_message_sequence(
                    chat_id=chat_id,
                    step=current,
                    start_index=0,
                    answer=answer,
                )
                if next_step is None or next_step.id == current.id:
                    return next_step
                current = next_step
                continue

            if self._is_input_step(current):
                if await self._should_override_call_time_for_hold(chat_id=chat_id, step=current):
                    next_step = await self._apply_hold_call_time_override(
                        chat_id=chat_id,
                        step=current,
                        state=state,
                    )
                    if next_step is None:
                        return None
                    current = next_step
                    continue

                state = await self.repo.get_chat_funnel_state(chat_id)
                prompt_delay_seconds = self._input_prompt_delay_seconds(current)
                if prompt_delay_seconds > 0:
                    if state is not None:
                        runtime_json = dict(state.runtime_json or {})
                        runtime_json["input_prompt_pending_step_id"] = str(current.id)
                        await self.repo.upsert_chat_funnel_state(
                            chat_id=chat_id,
                            funnel_id=state.funnel_id,
                            funnel_version_id=state.funnel_version_id,
                            current_step_id=current.id,
                            entered_step_at=datetime.now(timezone.utc),
                            waiting_for_answer=False,
                            runtime_json=runtime_json,
                        )
                    await self._schedule_job(
                        chat_id=chat_id,
                        step=current,
                        job_type="input_prompt",
                        delay_seconds=prompt_delay_seconds,
                        payload_json={},
                    )
                    logger.info(
                        "Scheduled delayed input prompt chat_id=%s step_id=%s delay_seconds=%s",
                        chat_id,
                        current.id,
                        prompt_delay_seconds,
                    )
                    return current

                if state is not None:
                    await self.repo.upsert_chat_funnel_state(
                        chat_id=chat_id,
                        funnel_id=state.funnel_id,
                        funnel_version_id=state.funnel_version_id,
                        current_step_id=current.id,
                        entered_step_at=datetime.now(timezone.utc),
                        waiting_for_answer=True,
                    )
                await self._send_input_prompt(chat_id=chat_id, step=current)
                await self._schedule_input_timeout(chat_id=chat_id, step=current)
                return current

            if current.step_type == "condition":
                outcome = await self._evaluate_condition_outcome(
                    chat_id=chat_id,
                    step=current,
                    answer=answer,
                )
                next_step = await self._move_condition_outcome(
                    chat_id=chat_id,
                    step=current,
                    outcome=outcome,
                )
                if next_step is None:
                    return None
                current = next_step
                continue

            if current.step_type == "action":
                action_ok = await self._execute_crm_actions(chat_id=chat_id, step=current)
                if not action_ok:
                    return current
                next_step = await self._move_from_step(
                    chat_id=chat_id,
                    step=current,
                    answer=answer,
                )
                if next_step is None:
                    return None
                current = next_step
                continue

            if current.step_type == "operator":
                await self._execute_operator_handoff(chat_id=chat_id, step=current)
                return None

            if current.step_type == "integration":
                integration_ok = await self._execute_integration_step(
                    chat_id=chat_id,
                    step=current,
                )
                if not integration_ok:
                    return current
                next_step = await self._move_from_step(
                    chat_id=chat_id,
                    step=current,
                    answer=answer,
                )
                if next_step is None:
                    return None
                current = next_step
                continue

            if current.step_type == "delay":
                next_step = await self._execute_delay_step(chat_id=chat_id, step=current)
                if next_step is None or next_step.id == current.id:
                    return next_step
                current = next_step
                continue

            if current.step_type == "finish":
                await self._execute_finish(chat_id=chat_id, step=current)
                return None

            logger.info(
                "Funnel runtime stopped on unsupported block step_id=%s step_type=%s block_type=%s",
                current.id,
                current.step_type,
                current.block_type,
            )
            return current

        logger.warning("Funnel runtime guard reached chat_id=%s step_id=%s", chat_id, step.id)
        return None

    async def _execute_message_sequence(
        self,
        *,
        chat_id: UUID,
        step: FunnelStep,
        start_index: int = 0,
        answer: Optional[str] = None,
        skip_delay_at_start: bool = False,
    ) -> Optional[FunnelStep]:
        messages = self._message_sequence(step)
        if not messages:
            return await self._move_from_step(chat_id=chat_id, step=step, answer=answer)

        index = max(start_index, 0)
        while index < len(messages):
            item = messages[index]
            delay_seconds = self._message_delay_seconds(item)
            if skip_delay_at_start and index == start_index:
                delay_seconds = 0
            if delay_seconds > 0:
                await self._schedule_job(
                    chat_id=chat_id,
                    step=step,
                    job_type="message_sequence",
                    delay_seconds=delay_seconds,
                    payload_json={"message_index": index},
                )
                logger.info(
                    "Scheduled message sequence chat_id=%s step_id=%s index=%s delay_seconds=%s",
                    chat_id,
                    step.id,
                    index,
                    delay_seconds,
                )
                return step

            buttons = self._buttons_from_message_item(item)
            sent = await self._send_message_item(
                chat_id=chat_id,
                step=step,
                item=item,
                reply_markup=self._reply_markup_for_buttons(
                    step=step,
                    buttons=buttons,
                    message_index=index,
                ),
            )
            if not sent:
                logger.warning(
                    "Message sequence item has no deliverable payload chat_id=%s step_id=%s index=%s",
                    chat_id,
                    step.id,
                    index,
                )
            if buttons or self._message_item_waits_for_answer(item):
                state = await self.repo.get_chat_funnel_state(chat_id)
                if state is not None:
                    runtime_json = dict(state.runtime_json or {})
                    runtime_json["message_sequence"] = {
                        "step_id": str(step.id),
                        "message_index": index,
                    }
                    await self.repo.upsert_chat_funnel_state(
                        chat_id=chat_id,
                        funnel_id=state.funnel_id,
                        funnel_version_id=state.funnel_version_id,
                        current_step_id=step.id,
                        entered_step_at=state.entered_step_at,
                        waiting_for_answer=True,
                        runtime_json=runtime_json,
                    )
                return step
            index += 1

        return await self._move_from_step(chat_id=chat_id, step=step, answer=answer)

    async def _send_step_message(self, *, chat_id: UUID, step: FunnelStep) -> None:
        sequence = self._message_sequence(step)
        item = sequence[0] if sequence else step.config_json or {}
        text = self._message_item_text(item)
        media_type, media_ref = self._message_item_media_payload(step, item)
        upload_id = self._message_item_upload_id(item)
        if not text and media_ref is None and upload_id is None:
            return
        await self._create_outgoing_message(
            chat_id=chat_id,
            text=text,
            message_type=media_type,
            telegram_file_id=media_ref,
            broadcast_upload_id=upload_id,
            file_name=self._step_file_name(step),
            mime_type=self._step_mime_type(step),
            reply_markup=self._reply_markup_for_step(step),
        )

    async def _send_input_prompt(self, *, chat_id: UUID, step: FunnelStep) -> None:
        text = self._step_prompt(step)
        if not text:
            return
        await self._create_outgoing_message(
            chat_id=chat_id,
            text=text,
            reply_markup=self._reply_markup_for_step(step),
        )

    async def _schedule_input_timeout(self, *, chat_id: UUID, step: FunnelStep) -> None:
        timeout_seconds = self._input_timeout_seconds(step)
        if timeout_seconds <= 0:
            return
        await self._schedule_job(
            chat_id=chat_id,
            step=step,
            job_type="input_timeout",
            delay_seconds=timeout_seconds,
            payload_json={},
        )
        logger.info(
            "Scheduled input timeout chat_id=%s step_id=%s timeout_seconds=%s",
            chat_id,
            step.id,
            timeout_seconds,
        )

    async def _schedule_job(
        self,
        *,
        chat_id: UUID,
        step: FunnelStep,
        job_type: str,
        delay_seconds: int,
        payload_json: dict,
    ) -> None:
        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None:
            return
        await self.repo.cancel_scheduled_jobs_for_chat(
            chat_id=chat_id,
            job_type=job_type,
            step_id=step.id,
        )
        job = await self.repo.create_scheduled_job(
            job_type=job_type,
            chat_id=chat_id,
            funnel_state_id=state.id,
            funnel_id=state.funnel_id,
            funnel_version_id=state.funnel_version_id,
            step_id=step.id,
            run_at=datetime.now(timezone.utc) + timedelta(seconds=delay_seconds),
            payload_json=payload_json,
        )
        await enqueue_funnel_scheduled_job(job.id, delay_seconds)

    async def _execute_delay_step(self, *, chat_id: UUID, step: FunnelStep) -> Optional[FunnelStep]:
        delay_seconds = self._delay_step_seconds(step)
        config = step.config_json or {}
        delay_type = str(config.get("delay_type") or "wait").strip()
        if delay_type in {"no_reply_timeout", "reply_timeout"}:
            state = await self.repo.get_chat_funnel_state(chat_id)
            if state is not None:
                runtime_json = dict(state.runtime_json or {})
                runtime_json.setdefault("no_reply", {})[str(step.id)] = {"replied": False}
                await self.repo.upsert_chat_funnel_state(
                    chat_id=chat_id,
                    funnel_id=state.funnel_id,
                    funnel_version_id=state.funnel_version_id,
                    current_step_id=step.id,
                    entered_step_at=datetime.now(timezone.utc),
                    waiting_for_answer=False,
                    runtime_json=runtime_json,
                )
            await self._schedule_job(
                chat_id=chat_id,
                step=step,
                job_type="no_reply_timeout",
                delay_seconds=max(delay_seconds, 1),
                payload_json={},
            )
            return step

        if delay_seconds <= 0:
            return await self._move_to_config_target_or_next(
                chat_id=chat_id,
                step=step,
                target_key="target_step_id",
                answer="delay",
            )
        await self._schedule_job(
            chat_id=chat_id,
            step=step,
            job_type="delay_step",
            delay_seconds=delay_seconds,
            payload_json={},
        )
        return step

    async def _create_outgoing_message(
        self,
        *,
        chat_id: UUID,
        text: str,
        reply_markup: Optional[dict],
        message_type: str = MessageType.TEXT,
        telegram_file_id: Optional[str] = None,
        broadcast_upload_id: Optional[UUID] = None,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> None:
        chat = await self.chat_repo.get_by_id(chat_id)
        if chat is None:
            return
        normalized_type = self._normalize_message_type(message_type)
        message_text = text.strip()
        if broadcast_upload_id is not None and normalized_type != MessageType.TEXT:
            if chat.bot_id is None:
                raise RuntimeError("Chat bot is not configured for funnel media send")
            upload = await self.broadcast_repo.get_upload_in_project(
                broadcast_upload_id,
                chat.project_id,
            )
            if upload is None:
                raise RuntimeError("Funnel media upload is missing or unavailable")
            if upload.media_type != normalized_type:
                raise RuntimeError("Funnel media upload type does not match message type")
            if upload.expires_at is not None and upload.expires_at <= datetime.now(timezone.utc):
                raise RuntimeError("Funnel media upload has expired")
            path = Path(upload.storage_path)
            if not upload.storage_path or not path.exists():
                raise RuntimeError("Funnel media upload file is missing from private storage")

            telegram_result = await self.message_service._send_media_to_telegram_by_type(
                media_type=normalized_type,
                media=path,
                project_id=chat.project_id,
                bot_id=chat.bot_id,
                external_chat_id=chat.external_chat_id,
                caption=message_text or None,
                reply_markup=reply_markup,
                file_name=upload.file_name,
                mime_type=upload.mime_type,
            )
            if telegram_result is None:
                raise RuntimeError("Telegram did not accept funnel media message")

            actual_media_type = self.message_service._actual_telegram_media_type(
                normalized_type,
                telegram_result,
            )
            telegram_file_id, file_unique_id, telegram_file_size = (
                self.message_service._extract_telegram_media_metadata(
                    actual_media_type,
                    telegram_result,
                )
            )
            await self.message_service.create_message(
                chat_id=chat_id,
                project_id=chat.project_id,
                data=MessageCreate(
                    external_message_id=self.message_service._telegram_message_id(telegram_result),
                    message_type=actual_media_type,
                    sender_type=SenderType.BOT,
                    sender_id=None,
                    body=None,
                    caption=message_text or None,
                    telegram_file_id=telegram_file_id,
                    file_unique_id=file_unique_id,
                    file_name=upload.file_name,
                    mime_type=upload.mime_type,
                    file_size=telegram_file_size or upload.file_size,
                    raw_payload_json={
                        "telegram_result": telegram_result,
                        "broadcast_upload_id": str(upload.id),
                    },
                ),
                send_to_telegram=False,
            )
            return

        await self.message_service.create_message(
            chat_id=chat_id,
            project_id=chat.project_id,
            data=MessageCreate(
                message_type=normalized_type,
                sender_type=SenderType.BOT,
                sender_id=None,
                body=message_text if normalized_type == MessageType.TEXT else None,
                caption=message_text if normalized_type != MessageType.TEXT else None,
                telegram_file_id=telegram_file_id,
                file_name=file_name,
                mime_type=mime_type,
                reply_markup=reply_markup,
            ),
        )

    async def _send_message_item(
        self,
        *,
        chat_id: UUID,
        step: FunnelStep,
        item: dict[str, Any],
        reply_markup: Optional[dict],
    ) -> bool:
        text = self._message_item_text(item)
        message_type, media_ref = self._message_item_media_payload(step, item)
        upload_id = self._message_item_upload_id(item)
        if not text and media_ref is None and upload_id is None:
            return False
        await self._create_outgoing_message(
            chat_id=chat_id,
            text=text,
            message_type=message_type,
            telegram_file_id=media_ref,
            broadcast_upload_id=upload_id,
            file_name=self._message_item_file_name(item),
            mime_type=self._message_item_mime_type(item),
            reply_markup=reply_markup,
        )
        return True

    async def _move_from_step(
        self,
        *,
        chat_id: UUID,
        step: FunnelStep,
        answer: Optional[str],
    ) -> Optional[FunnelStep]:
        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None:
            return None
        edges = [
            edge
            for edge in await self.repo.list_edges(state.funnel_version_id)
            if edge.from_step_id == step.id
        ]
        edge = self._select_edge(edges, answer)
        if edge is None:
            await self._mark_completed(chat_id)
            return None
        return await self.move_to_next_step(chat_id=chat_id, edge_id=edge.id)

    async def _move_to_config_target_or_next(
        self,
        *,
        chat_id: UUID,
        step: FunnelStep,
        target_key: str,
        answer: Optional[str],
    ) -> Optional[FunnelStep]:
        config = step.config_json or {}
        target_step_id = config.get(target_key)
        if target_step_id:
            return await self._move_to_step_id(
                chat_id=chat_id,
                target_step_id=target_step_id,
                from_step=step,
            )
        return await self._move_from_step(chat_id=chat_id, step=step, answer=answer)

    async def _move_to_step_id(
        self,
        *,
        chat_id: UUID,
        target_step_id: Any,
        from_step: FunnelStep,
    ) -> Optional[FunnelStep]:
        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None:
            return None
        try:
            parsed_step_id = target_step_id if isinstance(target_step_id, UUID) else UUID(str(target_step_id))
        except (TypeError, ValueError):
            logger.warning(
                "Invalid target_step_id chat_id=%s from_step_id=%s target=%s",
                chat_id,
                from_step.id,
                target_step_id,
            )
            return await self._move_from_step(chat_id=chat_id, step=from_step, answer=None)

        next_step = await self.repo.get_step(parsed_step_id)
        if next_step is None or next_step.funnel_version_id != state.funnel_version_id:
            logger.warning(
                "Target step missing or outside active version chat_id=%s from_step_id=%s target=%s",
                chat_id,
                from_step.id,
                parsed_step_id,
            )
            return await self._move_from_step(chat_id=chat_id, step=from_step, answer=None)

        logger.info(
            "Moving funnel step by explicit target chat_id=%s from_step_id=%s to_step_id=%s",
            chat_id,
            from_step.id,
            next_step.id,
        )
        await self.repo.upsert_chat_funnel_state(
            chat_id=chat_id,
            funnel_id=state.funnel_id,
            funnel_version_id=state.funnel_version_id,
            current_step_id=next_step.id,
            entered_step_at=datetime.now(timezone.utc),
            waiting_for_answer=False,
        )
        await self._log_runtime_step(chat_id=chat_id, step=next_step, status="success")
        return next_step

    async def _move_condition_outcome(
        self,
        *,
        chat_id: UUID,
        step: FunnelStep,
        outcome: str,
    ) -> Optional[FunnelStep]:
        config = step.config_json or {}
        if step.block_type == "generic_ab_test":
            variants = config.get("variants")
            if isinstance(variants, list):
                for item in variants:
                    if (
                        isinstance(item, dict)
                        and str(item.get("id") or "").strip() == outcome
                        and item.get("target_step_id")
                    ):
                        return await self._move_to_step_id(
                            chat_id=chat_id,
                            target_step_id=item.get("target_step_id"),
                            from_step=step,
                        )

        outcomes = config.get("outcomes")
        if isinstance(outcomes, list):
            outcome_values = self._branch_match_values(outcome)
            for item in outcomes:
                if not isinstance(item, dict):
                    continue
                labels = self._branch_match_values(item.get("id")) | self._branch_match_values(
                    item.get("label")
                ) | self._branch_match_values(item.get("value"))
                if outcome_values & labels and item.get("target_step_id"):
                    return await self._move_to_step_id(
                        chat_id=chat_id,
                        target_step_id=item.get("target_step_id"),
                        from_step=step,
                    )
        if outcome == "fallback" and config.get("fallback_target_step_id"):
            return await self._move_to_step_id(
                chat_id=chat_id,
                target_step_id=config.get("fallback_target_step_id"),
                from_step=step,
            )
        return await self._move_from_step(chat_id=chat_id, step=step, answer=outcome)

    async def _execute_finish(self, *, chat_id: UUID, step: FunnelStep) -> None:
        text = self._step_text(step)
        if text:
            await self._create_outgoing_message(
                chat_id=chat_id,
                text=text,
                reply_markup=None,
            )
        await self._apply_finish_result(chat_id=chat_id, step=step)
        await self._mark_completed(chat_id, step=step)

    async def _mark_completed(self, chat_id: UUID, step: Optional[FunnelStep] = None) -> None:
        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None:
            return
        current_step_id = step.id if step is not None else state.current_step_id
        await self.repo.upsert_chat_funnel_state(
            chat_id=chat_id,
            funnel_id=state.funnel_id,
            funnel_version_id=state.funnel_version_id,
            current_step_id=current_step_id,
            entered_step_at=state.entered_step_at,
            waiting_for_answer=False,
            completed_at=datetime.now(timezone.utc),
        )
        logger.info(
            "Finish applied chat_id=%s funnel_id=%s funnel_version_id=%s finish_step_id=%s",
            chat_id,
            state.funnel_id,
            state.funnel_version_id,
            current_step_id,
        )

    async def _apply_finish_result(self, *, chat_id: UUID, step: FunnelStep) -> None:
        config = step.config_json or {}
        if config.get("set_lead_status") is False:
            return
        result = str(config.get("result") or "stop").strip().lower()
        if result == "stop":
            return

        status_code = self._finish_result_to_status_code(result)
        if status_code is None:
            logger.warning(
                "Unsupported finish result chat_id=%s step_id=%s result=%s",
                chat_id,
                step.id,
                result,
            )
            return

        lead = await self.repo.get_lead_by_chat(chat_id)
        if lead is None:
            logger.warning("Finish result has no lead to update chat_id=%s step_id=%s", chat_id, step.id)
            return

        updated = await self.lead_repo.set_status_by_code(
            lead.id,
            lead.project_id,
            status_code,
        )
        if updated is None and result == "rejected":
            updated = await self.lead_repo.set_status_by_code(
                lead.id,
                lead.project_id,
                LeadStatusCode.LOST,
            )
        if updated is None:
            logger.warning(
                "Finish result status was not applied chat_id=%s lead_id=%s result=%s "
                "status_code=%s",
                chat_id,
                lead.id,
                result,
                status_code,
            )

    @staticmethod
    def _finish_result_to_status_code(result: str) -> Optional[str]:
        if result == "success":
            return LeadStatusCode.QUALIFIED
        if result == "lost":
            return LeadStatusCode.LOST
        if result == "rejected":
            return "rejected"
        return None

    async def _execute_crm_actions(self, *, chat_id: UUID, step: FunnelStep) -> bool:
        lead = await self.repo.get_lead_by_chat(chat_id)
        if lead is None:
            logger.warning("CRM action has no lead chat_id=%s step_id=%s", chat_id, step.id)
            return True
        config = step.config_json or {}
        raw_actions = config.get("actions")
        if not isinstance(raw_actions, list):
            raw_actions = [config]

        for raw in raw_actions:
            if not isinstance(raw, dict):
                continue
            action_type = str(raw.get("type") or step.block_type or "").strip()
            try:
                if action_type == "add_tag" and raw.get("tag_id"):
                    tag_id = UUID(str(raw.get("tag_id")))
                    tag = await self.tag_repo.get_by_id_in_project(tag_id, lead.project_id)
                    if tag is not None:
                        await self.tag_repo.add_tag_to_lead(lead.id, tag.id)
                elif action_type == "remove_tag" and raw.get("tag_id"):
                    await self.tag_repo.remove_tag_from_lead(lead.id, UUID(str(raw.get("tag_id"))))
                elif action_type == "clear_tags":
                    await self.lead_repo.clear_tags(lead.id)
                elif action_type == "set_lead_status":
                    status_code = str(raw.get("status") or raw.get("value") or "").strip()
                    if status_code:
                        await self.lead_repo.set_status_by_code(lead.id, lead.project_id, status_code)
                elif action_type == "mark_lost":
                    await self.lead_repo.set_status_by_code(lead.id, lead.project_id, LeadStatusCode.LOST)
                elif action_type == "mark_success":
                    await self.lead_repo.set_status_by_code(lead.id, lead.project_id, LeadStatusCode.QUALIFIED)
                elif action_type == "mark_rejected":
                    updated = await self.lead_repo.set_status_by_code(lead.id, lead.project_id, "rejected")
                    if updated is None:
                        await self.lead_repo.set_status_by_code(lead.id, lead.project_id, LeadStatusCode.LOST)
                elif action_type == "write_field":
                    field = self._normalize_field_key(raw.get("field") or raw.get("lead_field_key"))
                    if field:
                        await self.repo.update_lead_mapped_fields(
                            lead.id,
                            {field: raw.get("value")} if field in DIRECT_LEAD_FIELDS else {},
                            {field: raw.get("value")} if field not in DIRECT_LEAD_FIELDS else {},
                        )
                elif action_type == "assign_operator":
                    manager_id = raw.get("operator_id") or raw.get("manager_id")
                    if manager_id:
                        await self.lead_repo.update_contact(
                            lead.id,
                            lead.project_id,
                            manager_id=UUID(str(manager_id)),
                        )
                elif action_type == "unassign_operator":
                    await self.lead_repo.update_contact(
                        lead.id,
                        lead.project_id,
                        manager_id=None,
                    )
                elif action_type in {"update_lead", "create_lead"}:
                    direct_values, custom_values = self._lead_update_values(raw)
                    if direct_values or custom_values:
                        await self.repo.update_lead_mapped_fields(
                            lead.id,
                            direct_values,
                            custom_values,
                        )
                elif action_type in {"submit_to_partner", "send_to_crm"}:
                    integration_id = raw.get("partner_integration_id") or raw.get("integration_id")
                    if not integration_id:
                        await self._log_runtime_step(
                            chat_id=chat_id,
                            step=step,
                            status="failed",
                            error_message="Ошибка CRM-действия: не указана интеграция партнёра",
                        )
                        logger.warning(
                            "Partner submission action skipped without integration id "
                            "chat_id=%s lead_id=%s step_id=%s",
                            chat_id,
                            lead.id,
                            step.id,
                        )
                        return False
                    integration = await self.partner_repo.get_in_project(
                        UUID(str(integration_id)),
                        lead.project_id,
                    )
                    if integration is None or not integration.is_active:
                        await self._log_runtime_step(
                            chat_id=chat_id,
                            step=step,
                            status="failed",
                            error_message=(
                                "Ошибка CRM-действия: партнёрская интеграция "
                                f"{integration_id} недоступна или выключена"
                            ),
                        )
                        logger.warning(
                            "Partner submission action references unavailable integration "
                            "chat_id=%s lead_id=%s step_id=%s integration_id=%s",
                            chat_id,
                            lead.id,
                            step.id,
                            integration_id,
                        )
                        return False
                    await self.partner_repo.create_submission(
                        lead_id=lead.id,
                        partner_integration_id=integration.id,
                        status="pending",
                    )
                elif action_type in {"send_fb_event", "send_facebook_capi_event"}:
                    event_name = str(
                        raw.get("event_name")
                        or raw.get("fb_event_name")
                        or "Lead"
                    ).strip()
                    try:
                        event_name = FacebookCAPIService.validate_event_name(event_name)
                    except FacebookCAPIError as exc:
                        await self._log_runtime_step(
                            chat_id=chat_id,
                            step=step,
                            status="failed",
                            error_message=f"Ошибка Facebook CAPI: {exc}",
                        )
                        return False

                    chat = await self.chat_repo.get_by_id(chat_id)
                    if chat is None or chat.tracking_link_id is None:
                        logger.warning(
                            "Facebook CAPI action skipped without tracking link chat_id=%s lead_id=%s step_id=%s",
                            chat_id,
                            lead.id,
                            step.id,
                        )
                        continue

                    tracking_link = await self.tracking_link_repo.get_link_by_id(chat.tracking_link_id)
                    if (
                        tracking_link is None
                        or not tracking_link.fb_pixel_id
                        or not tracking_link.fb_capi_token
                    ):
                        logger.warning(
                            "Facebook CAPI action skipped without configured link chat_id=%s lead_id=%s "
                            "tracking_link_id=%s step_id=%s",
                            chat_id,
                            lead.id,
                            chat.tracking_link_id,
                            step.id,
                        )
                        continue

                    custom_data = {
                        "source": "funnel_runtime",
                        "project_id": str(lead.project_id),
                        "tracking_code": tracking_link.code,
                        "funnel_step_id": str(step.id),
                        "funnel_step_key": step.key,
                        "funnel_step_title": step.title,
                    }
                    queued_job_id = await enqueue_facebook_capi_event(
                        lead_id=lead.id,
                        tracking_link_id=tracking_link.id,
                        event_name=event_name,
                        custom_data=custom_data,
                    )
                    if queued_job_id is None:
                        logger.warning(
                            "Facebook CAPI event was not queued chat_id=%s lead_id=%s step_id=%s event_name=%s",
                            chat_id,
                            lead.id,
                            step.id,
                            event_name,
                        )
                elif action_type == "add_note":
                    logger.info("CRM note action recorded chat_id=%s lead_id=%s step_id=%s", chat_id, lead.id, step.id)
                else:
                    logger.warning(
                        "Unsupported CRM action chat_id=%s step_id=%s type=%s",
                        chat_id,
                        step.id,
                        action_type,
                    )
            except Exception as exc:
                await self._log_runtime_step(
                    chat_id=chat_id,
                    step=step,
                    status="failed",
                    error_message=f"Ошибка CRM-действия {action_type}: {exc}",
                )
                logger.exception(
                    "CRM action failed chat_id=%s lead_id=%s step_id=%s type=%s",
                    chat_id,
                    lead.id,
                    step.id,
                    action_type,
                )
                return False
        return True

    async def _execute_operator_handoff(self, *, chat_id: UUID, step: FunnelStep) -> None:
        state = await self.repo.get_chat_funnel_state(chat_id)
        chat = await self.chat_repo.get_by_id(chat_id)
        lead = await self.repo.get_lead_by_chat(chat_id)
        if chat is None:
            logger.warning("Operator handoff has no chat chat_id=%s step_id=%s", chat_id, step.id)
            return

        await self.bot_repo.disable_bot_for_chat(chat_id)

        if lead is not None:
            status_code = await self._manual_processing_status_code(lead.project_id)
            updated = await self.lead_repo.set_status_by_code(
                lead.id,
                lead.project_id,
                status_code,
            )
            if updated is None and status_code != LeadStatusCode.NEW:
                await self.lead_repo.set_status_by_code(
                    lead.id,
                    lead.project_id,
                    LeadStatusCode.NEW,
                )

            manager_id = self._operator_manager_id(step)
            if manager_id is not None:
                await self.lead_repo.update_contact(
                    lead.id,
                    lead.project_id,
                    manager_id=manager_id,
                )

        handoff_message = self._operator_handoff_message(step)
        if handoff_message:
            await self._create_outgoing_message(
                chat_id=chat_id,
                text=handoff_message,
                reply_markup=None,
            )

        await self.chat_audit.log_event(
            chat_id=chat_id,
            user_id=None,
            event_type=ChatEventType.NOTE_ADDED,
            old_value=None,
            new_value=f"Воронка передала чат оператору на блоке «{step.title}».",
            project_id=chat.project_id,
        )
        await self._send_operator_alert(chat=chat, lead_id=lead.id if lead else None, step=step)
        await self._log_runtime_step(chat_id=chat_id, step=step, status="success")
        await self.repo.delete_chat_funnel_state(chat_id)
        logger.info(
            "Funnel operator handoff completed chat_id=%s funnel_id=%s funnel_version_id=%s step_id=%s",
            chat_id,
            state.funnel_id if state else None,
            state.funnel_version_id if state else step.funnel_version_id,
            step.id,
        )

    async def _execute_integration_step(self, *, chat_id: UUID, step: FunnelStep) -> bool:
        config = step.config_json or {}
        integration_type = str(config.get("integration_type") or step.block_type or "").strip()
        if integration_type not in {"webhook", "http_request", "outgoing_webhook", "generic_integration"}:
            logger.info(
                "Integration step has no local runtime handler; passing through chat_id=%s step_id=%s type=%s",
                chat_id,
                step.id,
                integration_type,
            )
            return True

        url = str(config.get("url") or config.get("webhook_url") or "").strip()
        if not url:
            await self._log_runtime_step(
                chat_id=chat_id,
                step=step,
                status="failed",
                error_message="Integration step requires url",
            )
            return False

        method = str(config.get("method") or "POST").strip().upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            method = "POST"
        headers = config.get("headers") if isinstance(config.get("headers"), dict) else {}
        timeout_seconds = self._integration_timeout_seconds(config)
        payload = await self._integration_payload(chat_id=chat_id, step=step)
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.request(
                    method,
                    url,
                    headers={str(key): str(value) for key, value in headers.items()},
                    json=payload if method != "GET" else None,
                    params=payload if method == "GET" else None,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            await self._log_runtime_step(
                chat_id=chat_id,
                step=step,
                status="failed",
                error_message=f"Integration request failed: {exc}",
            )
            logger.warning(
                "Funnel integration request failed chat_id=%s step_id=%s url=%s error=%s",
                chat_id,
                step.id,
                url,
                exc,
            )
            return False

        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is not None:
            runtime_json = dict(state.runtime_json or {})
            integrations = dict(runtime_json.get("integrations") or {})
            integrations[str(step.id)] = {
                "url": url,
                "method": method,
                "status_code": response.status_code,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            runtime_json["integrations"] = integrations
            await self.repo.update_chat_funnel_runtime(
                chat_id=chat_id,
                runtime_json=runtime_json,
            )
        return True

    async def _save_input_answer(
        self,
        *,
        chat_id: UUID,
        step: FunnelStep,
        answer: Any,
    ) -> None:
        lead = await self.repo.get_lead_by_chat(chat_id)
        if lead is None:
            return

        answer_type = self._input_answer_type(step)
        direct_values: dict[str, Any] = {}
        custom_values: dict[str, Any] = {}
        normalized_answer = str(answer or "").strip()
        configured_field = self._normalize_field_key(
            (step.config_json or {}).get("custom_field_key")
            or (step.config_json or {}).get("save_to")
            or (step.config_json or {}).get("field_key")
            or (step.config_json or {}).get("lead_field_key")
        )

        if configured_field:
            value = self._transform_value(configured_field, normalized_answer)
            if configured_field in DIRECT_LEAD_FIELDS:
                direct_values[configured_field] = value
            else:
                custom_values[configured_field] = value
        elif answer_type == "phone":
            direct_values["phone"] = self._normalize_phone(normalized_answer)
        elif answer_type == "email":
            custom_values["email"] = normalized_answer
        elif answer_type == "name":
            direct_values["name"] = normalized_answer
        else:
            field_key = self._input_target_field(step)
            if field_key:
                value = self._transform_value(field_key, normalized_answer)
                if field_key in DIRECT_LEAD_FIELDS:
                    direct_values[field_key] = value
                else:
                    custom_values[field_key] = value

        if not direct_values and not custom_values:
            return
        await self.repo.update_lead_mapped_fields(lead.id, direct_values, custom_values)
        await self.scoring.update_lead_score(lead.id)

    async def _manual_processing_status_code(self, project_id: UUID) -> str:
        statuses = await self.lead_repo.list_statuses()
        for candidate in MANUAL_STATUS_CODE_CANDIDATES:
            if any(status.code == candidate for status in statuses):
                return candidate
        for status in statuses:
            haystack = f"{status.code} {status.name}".lower()
            if "manual" in haystack or "ручн" in haystack:
                return status.code
        if await self.lead_repo.get_status_by_code(LeadStatusCode.NEW) is not None:
            return LeadStatusCode.NEW
        logger.warning("No manual or new lead status configured project_id=%s", project_id)
        return LeadStatusCode.NEW

    @staticmethod
    def _operator_manager_id(step: FunnelStep) -> Optional[UUID]:
        config = step.config_json or {}
        raw = config.get("operator_id") or config.get("manager_id")
        if not raw:
            return None
        try:
            return raw if isinstance(raw, UUID) else UUID(str(raw))
        except (TypeError, ValueError):
            logger.warning("Invalid operator manager id step_id=%s manager_id=%s", step.id, raw)
            return None

    @staticmethod
    def _operator_handoff_message(step: FunnelStep) -> str:
        config = step.config_json or {}
        if config.get("send_message") is False:
            return ""
        return str(
            config.get("text")
            or config.get("message")
            or config.get("message_text")
            or "Передаю диалог оператору. Специалист скоро подключится."
        ).strip()

    async def _send_operator_alert(
        self,
        *,
        chat: Any,
        lead_id: Optional[UUID],
        step: FunnelStep,
    ) -> None:
        config = step.config_json or {}
        alert_chat_id = (
            config.get("alert_chat_id")
            or config.get("admin_chat_id")
            or config.get("telegram_alert_chat_id")
        )
        if not alert_chat_id:
            logger.info(
                "Operator handoff Telegram alert skipped: alert chat is not configured "
                "project_id=%s chat_id=%s step_id=%s",
                chat.project_id,
                chat.id,
                step.id,
            )
            return
        text = str(
            config.get("alert_text")
            or (
                "Чат требует ручного вмешательства.\n"
                f"CRM chat_id: {chat.id}\n"
                f"lead_id: {lead_id or 'нет'}\n"
                f"Блок: {step.title}"
            )
        ).strip()
        result = await self.telegram_sender.send_message(
            project_id=chat.project_id,
            bot_id=chat.bot_id,
            external_chat_id=str(alert_chat_id),
            text=text,
        )
        if result is None:
            logger.warning(
                "Operator handoff Telegram alert was not delivered project_id=%s chat_id=%s alert_chat_id=%s",
                chat.project_id,
                chat.id,
                alert_chat_id,
            )

    @staticmethod
    def _integration_timeout_seconds(config: dict[str, Any]) -> float:
        try:
            return min(max(float(config.get("timeout_seconds") or 10), 1), 60)
        except (TypeError, ValueError):
            return 10.0

    async def _integration_payload(self, *, chat_id: UUID, step: FunnelStep) -> dict[str, Any]:
        state = await self.repo.get_chat_funnel_state(chat_id)
        lead = await self.repo.get_lead_by_chat(chat_id)
        lead_context = await self.lead_repo.get_lead_context(lead.id) if lead is not None else {}
        config = step.config_json or {}
        extra_payload = config.get("payload") if isinstance(config.get("payload"), dict) else {}
        return {
            "chat_id": str(chat_id),
            "lead_id": str(lead.id) if lead is not None else None,
            "project_id": str(lead.project_id) if lead is not None else None,
            "funnel_id": str(state.funnel_id) if state is not None else None,
            "funnel_version_id": str(state.funnel_version_id) if state is not None else None,
            "step_id": str(step.id),
            "step_key": step.key,
            "step_title": step.title,
            "lead": {
                "name": lead.name,
                "phone": lead.phone,
                "username": lead.username,
                "custom_fields": lead.custom_fields or {},
                "context": lead_context,
            }
            if lead is not None
            else None,
            **extra_payload,
        }

    @staticmethod
    def _lead_update_values(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        source = raw.get("fields") if isinstance(raw.get("fields"), dict) else raw
        direct_values: dict[str, Any] = {}
        custom_values: dict[str, Any] = {}
        for key, value in source.items():
            field = FunnelRuntimeService._normalize_field_key(key)
            if not field or field in {"type", "actions"}:
                continue
            if field in DIRECT_LEAD_FIELDS:
                direct_values[field] = FunnelRuntimeService._transform_value(field, value)
            else:
                custom_values[field] = value
        return direct_values, custom_values

    async def _evaluate_condition_outcome(
        self,
        *,
        chat_id: UUID,
        step: FunnelStep,
        answer: Optional[str],
    ) -> str:
        config = step.config_json or {}
        if step.block_type == "generic_ab_test":
            return self._evaluate_ab_test_variant(chat_id=chat_id, step=step)

        if str(config.get("mode") or "").strip() == "simple_yes_no":
            value = str(answer or await self._condition_source_value(chat_id, "last_answer", None) or "")
            normalized = value.strip().lower()
            if normalized in {"yes", "y", "true", "1", "да", "ага", "ок"}:
                return "true"
            if normalized in {"no", "n", "false", "0", "нет"}:
                return "false"
            return "fallback"

        if step.block_type == "generic_hold_router":
            hold_enabled = bool(await self._condition_source_value(chat_id, "hold_mode", None))
            await self._apply_hold_call_plan(chat_id=chat_id, step=step, hold_enabled=hold_enabled)
            logger.info(
                "Hold router evaluated chat_id=%s step_id=%s is_hold_active=%s",
                chat_id,
                step.id,
                hold_enabled,
            )
            return "tomorrow" if hold_enabled else "today"

        block_outcome = await self._evaluate_block_specific_condition(
            chat_id=chat_id,
            step=step,
            answer=answer,
        )
        if block_outcome is not None:
            return block_outcome

        raw_conditions = config.get("conditions")
        if not isinstance(raw_conditions, list) or not raw_conditions:
            return "true" if answer else "false"
        values = [
            await self._evaluate_single_condition(chat_id=chat_id, condition=condition)
            for condition in raw_conditions
            if isinstance(condition, dict)
        ]
        if not values:
            return "fallback"
        passed = any(values) if config.get("mode") == "any" else all(values)
        outcome = "true" if passed else "false"
        logger.info(
            "Condition evaluated chat_id=%s step_id=%s outcome=%s values=%s",
            chat_id,
            step.id,
            outcome,
            values,
        )
        return outcome

    async def _evaluate_block_specific_condition(
        self,
        *,
        chat_id: UUID,
        step: FunnelStep,
        answer: Optional[str],
    ) -> Optional[str]:
        config = step.config_json or {}
        block_type = step.block_type

        if block_type in {"button_equals", "text_contains", "text_equals"}:
            actual = answer or await self._condition_source_value(chat_id, "last_answer", None)
            operator = "contains" if block_type == "text_contains" else "equals"
            passed = self._compare_condition(actual, operator, config.get("value"))
            return "true" if passed else "false"

        if block_type in {"field_exists", "field_empty", "field_compare"}:
            field = config.get("field") or config.get("lead_field_key")
            source = "lead_field"
            operator = (
                "exists"
                if block_type == "field_exists"
                else "empty"
                if block_type == "field_empty"
                else str(config.get("operator") or "equals")
            )
            actual = await self._condition_source_value(chat_id, source, field)
            passed = self._compare_condition(actual, operator, config.get("value"))
            return "true" if passed else "false"

        if block_type in {"has_tag", "not_has_tag"}:
            actual = await self._condition_source_value(chat_id, "tag", None)
            expected = config.get("tag_id") or config.get("tag_name") or config.get("value")
            has_tag = self._compare_condition(actual, "contains", expected)
            passed = has_tag if block_type == "has_tag" else not has_tag
            return "true" if passed else "false"

        if block_type == "lead_status_equals":
            actual = await self._condition_source_value(chat_id, "status", None)
            expected = config.get("status") or config.get("status_code") or config.get("value")
            return "true" if self._compare_condition(actual, "equals", expected) else "false"

        if block_type == "tracking_link_equals":
            actual = await self._condition_source_value(chat_id, "tracking_link", None)
            expected = config.get("tracking_link") or config.get("tracking_code") or config.get("value")
            return "true" if self._compare_condition(actual, "equals", expected) else "false"

        if block_type in {"operator_assigned", "operator_not_assigned"}:
            assigned = bool(await self._condition_source_value(chat_id, "operator_assigned", None))
            passed = assigned if block_type == "operator_assigned" else not assigned
            return "true" if passed else "false"

        return None

    def _evaluate_ab_test_variant(self, *, chat_id: UUID, step: FunnelStep) -> str:
        config = step.config_json or {}
        raw_variants = config.get("variants")
        variants = [item for item in raw_variants if isinstance(item, dict)] if isinstance(raw_variants, list) else []
        weighted_variants: list[tuple[str, int]] = []
        for index, variant in enumerate(variants):
            variant_id = str(variant.get("id") or f"variant_{index + 1}").strip()
            if not variant_id:
                continue
            try:
                weight = int(variant.get("weight") or 0)
            except (TypeError, ValueError):
                weight = 0
            if weight > 0:
                weighted_variants.append((variant_id, weight))

        if not weighted_variants:
            return "a"

        total_weight = sum(weight for _, weight in weighted_variants)
        digest = sha256(f"{chat_id}:{step.id}".encode("utf-8")).hexdigest()
        bucket = int(digest[:12], 16) % total_weight
        cursor = 0
        for variant_id, weight in weighted_variants:
            cursor += weight
            if bucket < cursor:
                logger.info(
                    "A/B variant selected chat_id=%s step_id=%s variant=%s bucket=%s total=%s",
                    chat_id,
                    step.id,
                    variant_id,
                    bucket,
                    total_weight,
                )
                return variant_id
        return weighted_variants[-1][0]

    async def _evaluate_single_condition(self, *, chat_id: UUID, condition: dict) -> bool:
        source = str(condition.get("source") or "last_answer")
        field = condition.get("field")
        if condition.get("source") is None and field:
            source = "lead_field"
        operator = str(condition.get("operator") or condition.get("type") or "equals")
        expected = condition.get("value")
        actual = await self._condition_source_value(chat_id, source, field)
        return self._compare_condition(actual, operator, expected)

    async def _condition_source_value(self, chat_id: UUID, source: str, field: Any) -> Any:
        state = await self.repo.get_chat_funnel_state(chat_id)
        runtime_json = state.runtime_json if state is not None else {}
        lead = await self.repo.get_lead_by_chat(chat_id)

        if source == "last_answer":
            return (runtime_json or {}).get("last_answer")
        if source == "hold_mode":
            if state is None:
                return False
            version = await self.repo.get_version(state.funnel_version_id)
            return bool(version.is_hold_active) if version is not None else False
        if lead is None:
            return None
        if source in {"lead_field", "custom_field", "field"}:
            key = str(field or "").strip()
            if not key:
                return None
            if hasattr(lead, key):
                return getattr(lead, key)
            return (lead.custom_fields or {}).get(key)
        if source == "tag":
            tags = await self.tag_repo.list_for_lead(lead.id)
            return [str(tag.id) for tag in tags] + [tag.name for tag in tags]
        if source == "status":
            context = await self.lead_repo.get_lead_context(lead.id)
            return context.get("status_code")
        if source == "tracking_link":
            context = await self.lead_repo.get_lead_context(lead.id)
            return context.get("tracking_ref_code") or context.get("tracking_code") or context.get("tracking_title")
        if source == "operator_assigned":
            return lead.manager_id is not None
        return None

    async def _should_override_call_time_for_hold(
        self,
        *,
        chat_id: UUID,
        step: FunnelStep,
    ) -> bool:
        if not self._is_call_time_input_step(step):
            return False
        return bool(await self._condition_source_value(chat_id, "hold_mode", None))

    async def _apply_hold_call_time_override(
        self,
        *,
        chat_id: UUID,
        step: FunnelStep,
        state: Any,
    ) -> Optional[FunnelStep]:
        current_state = await self.repo.get_chat_funnel_state(chat_id) or state
        answer = self._hold_call_time_answer(step)
        lead = await self.repo.get_lead_by_chat(chat_id)
        if lead is not None:
            await self.repo.update_lead_mapped_fields(
                lead.id,
                {"call_time_text": answer},
                {},
            )
            await self.scoring.update_lead_score(lead.id)

        await self._log_step_event(chat_id=chat_id, step=step, event_type="answered")
        runtime_json = self._runtime_with_answer(
            current_state.runtime_json,
            step_id=step.id,
            answer=answer,
        )
        await self.repo.upsert_chat_funnel_state(
            chat_id=chat_id,
            funnel_id=current_state.funnel_id,
            funnel_version_id=current_state.funnel_version_id,
            current_step_id=step.id,
            entered_step_at=current_state.entered_step_at,
            waiting_for_answer=False,
            runtime_json=runtime_json,
        )

        choice = self._choice_for_answer(step, answer)
        if choice and choice.get("target_step_id"):
            return await self._move_to_step_id(
                chat_id=chat_id,
                target_step_id=choice.get("target_step_id"),
                from_step=step,
            )
        return await self._move_from_step(chat_id=chat_id, step=step, answer=answer)

    def _hold_call_time_answer(self, step: FunnelStep) -> str:
        config = step.config_json or {}
        configured = (
            config.get("hold_answer")
            or config.get("tomorrow_label")
            or config.get("tomorrow_value")
        )
        if configured:
            return str(configured).strip() or "На завтра"

        for choice in self._buttons_from_step(step):
            candidates = [
                choice.get("label"),
                choice.get("value"),
                choice.get("id"),
            ]
            if any(self._is_tomorrow_value(candidate) for candidate in candidates):
                return str(choice.get("label") or choice.get("value") or "На завтра").strip()
        return "На завтра"

    @staticmethod
    def _is_call_time_input_step(step: FunnelStep) -> bool:
        config = step.config_json or {}
        save_to = str(config.get("save_to") or "").strip()
        return step.block_type == "ask_call_time" or save_to == "call_time_text"

    @staticmethod
    def _is_tomorrow_value(value: Any) -> bool:
        normalized = str(value or "").strip().lower()
        return "завтр" in normalized or "tomorrow" in normalized

    @staticmethod
    def _compare_condition(actual: Any, operator: str, expected: Any) -> bool:
        if operator in {"exists", "field_exists"}:
            return actual not in {None, ""}
        if operator in {"empty", "field_empty"}:
            return actual in {None, "", []}
        if operator in {"contains", "text_contains"}:
            if isinstance(actual, list):
                return str(expected) in {str(item) for item in actual}
            return str(expected).lower() in str(actual or "").lower()
        if operator in {"not_equals", "!="}:
            return str(actual or "").strip().lower() != str(expected or "").strip().lower()
        if operator in {"gt", "lt"}:
            try:
                left = float(actual)
                right = float(expected)
            except (TypeError, ValueError):
                return False
            return left > right if operator == "gt" else left < right
        return str(actual or "").strip().lower() == str(expected or "").strip().lower()

    async def _apply_hold_call_plan(
        self,
        *,
        chat_id: UUID,
        step: FunnelStep,
        hold_enabled: bool,
    ) -> None:
        lead = await self.repo.get_lead_by_chat(chat_id)
        if lead is None:
            return
        config = step.config_json or {}
        if config.get("set_call_time") is False:
            return
        value = (
            str(config.get("tomorrow_label") or "На завтра")
            if hold_enabled
            else str(config.get("today_label") or "Сегодня")
        )
        await self.repo.update_lead_mapped_fields(
            lead.id,
            {"call_time_text": value},
            {},
        )
        await self.scoring.update_lead_score(lead.id)

    async def _log_step_event(
        self,
        *,
        chat_id: UUID,
        step: FunnelStep,
        event_type: str,
    ) -> None:
        state = await self.repo.get_chat_funnel_state(chat_id)
        lead = await self.repo.get_lead_by_chat(chat_id)
        if state is None or lead is None:
            return
        await self.repo.create_step_log(
            lead_id=lead.id,
            funnel_id=state.funnel_id,
            funnel_version_id=state.funnel_version_id,
            step_id=step.id,
            step_name=step.title,
            event_type=event_type,
        )

    async def _log_runtime_step(
        self,
        *,
        chat_id: UUID,
        step: FunnelStep,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        state = await self.repo.get_chat_funnel_state(chat_id)
        funnel_version_id = state.funnel_version_id if state is not None else step.funnel_version_id
        await self.repo.create_runtime_log(
            chat_id=chat_id,
            funnel_version_id=funnel_version_id,
            step_id=step.id,
            status=status,
            error_message=error_message,
        )

    @staticmethod
    def _select_edge(edges, answer: Optional[str]):
        if not edges:
            return None
        if answer is None:
            return edges[0]

        normalized_values = FunnelRuntimeService._branch_match_values(answer)
        for edge in edges:
            condition = edge.condition_json or {}
            candidates = [
                condition.get("outcome"),
                condition.get("label"),
                condition.get("value"),
                condition.get("button_value"),
                condition.get("choice"),
            ]
            if any(
                normalized_values & FunnelRuntimeService._branch_match_values(candidate)
                for candidate in candidates
                if candidate is not None
            ):
                return edge
        return edges[0]

    @staticmethod
    def _branch_match_values(value: Any) -> set[str]:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return set()
        aliases = {normalized}
        if normalized in {"true", "yes", "y", "1", "да", "ага", "ок"}:
            aliases.update({"true", "yes", "y", "1", "да"})
        if normalized in {"false", "no", "n", "0", "нет"}:
            aliases.update({"false", "no", "n", "0", "нет"})
        if "завтр" in normalized or normalized == "tomorrow":
            aliases.update({"tomorrow", "завтра", "на завтра", "true", "yes", "да"})
        if "сегодня" in normalized or normalized == "today":
            aliases.update({"today", "сегодня", "false", "no", "нет"})
        return aliases

    @staticmethod
    def _is_message_step(step: FunnelStep) -> bool:
        return step.step_type == "message" or step.block_type in {
            "generic_message",
            "send_text",
            "send_inline_buttons",
            "send_personalized_message",
            "send_photo",
            "send_video",
            "send_voice",
            "send_video_note",
            "send_file",
            "send_link",
            "send_reply_buttons",
            "send_template",
        }

    @staticmethod
    def _is_input_step(step: FunnelStep) -> bool:
        return step.step_type == "input" or step.block_type.startswith("ask_")

    def _step_has_buttons(self, step: FunnelStep) -> bool:
        return bool(self._buttons_from_step(step))

    @staticmethod
    def _message_sequence(step: FunnelStep) -> list[dict[str, Any]]:
        config = step.config_json or {}
        raw_messages = config.get("messages")
        if isinstance(raw_messages, list) and raw_messages:
            messages = [item for item in raw_messages if isinstance(item, dict)]
            if messages:
                return messages

        text = FunnelRuntimeService._step_text(step)
        legacy = {
            "id": "legacy_message",
            "type": config.get("message_type") or config.get("type") or step.block_type,
            "text": text,
            "caption": config.get("caption"),
            "delay_seconds": config.get("delay_seconds") or 0,
            "wait_for_answer": bool(config.get("wait_for_answer")),
            "buttons": config.get("buttons") or [],
            "media": config.get("media"),
            "telegram_file_id": config.get("telegram_file_id")
            or config.get("file_id")
            or config.get("media_file_id"),
            "upload_id": config.get("upload_id"),
            "photo": config.get("photo"),
            "video": config.get("video"),
            "voice": config.get("voice"),
            "video_note": config.get("video_note"),
            "document": config.get("document") or config.get("file"),
            "media_url": config.get("media_url"),
            "file_name": config.get("file_name"),
            "mime_type": config.get("mime_type"),
        }
        if (
            not text
            and FunnelRuntimeService._media_reference_from_item(legacy) is None
            and FunnelRuntimeService._message_item_upload_id(legacy) is None
        ):
            return []
        return [legacy]

    @staticmethod
    def _message_item_text(item: dict[str, Any]) -> str:
        return str(
            item.get("text")
            or item.get("message")
            or item.get("message_text")
            or item.get("body")
            or item.get("content")
            or item.get("caption")
            or ""
        ).strip()

    @classmethod
    def _message_item_media_payload(
        cls,
        step: FunnelStep,
        item: dict[str, Any],
    ) -> tuple[str, Optional[str]]:
        media_ref = cls._media_reference_from_item(item)
        if media_ref is None and cls._message_item_upload_id(item) is None:
            return MessageType.TEXT, None
        message_type = cls._message_item_type(step, item)
        if message_type == MessageType.TEXT:
            message_type = MessageType.DOCUMENT
        return message_type, media_ref

    @classmethod
    def _step_media_payload(cls, step: FunnelStep) -> tuple[str, Optional[str]]:
        sequence = cls._message_sequence(step)
        item = sequence[0] if sequence else step.config_json or {}
        return cls._message_item_media_payload(step, item)

    @staticmethod
    def _media_reference_from_item(item: dict[str, Any]) -> Optional[str]:
        media = item.get("media") if isinstance(item.get("media"), dict) else {}
        for key in (
            "telegram_file_id",
            "file_id",
            "media_file_id",
            "photo",
            "video",
            "voice",
            "video_note",
            "document",
            "file",
            "media_url",
        ):
            value = item.get(key) or media.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _message_item_upload_id(item: dict[str, Any]) -> Optional[UUID]:
        media = item.get("media") if isinstance(item.get("media"), dict) else {}
        for key in ("upload_id", "broadcast_upload_id"):
            value = item.get(key) or media.get(key)
            if value is None:
                continue
            try:
                return UUID(str(value))
            except (TypeError, ValueError):
                continue
        return None

    @classmethod
    def _message_item_type(cls, step: FunnelStep, item: dict[str, Any]) -> str:
        if item.get("photo"):
            return MessageType.PHOTO
        if item.get("video"):
            return MessageType.VIDEO
        if item.get("voice"):
            return MessageType.VOICE
        if item.get("video_note"):
            return MessageType.VIDEO_NOTE
        if item.get("document") or item.get("file") or item.get("media_url"):
            return MessageType.DOCUMENT
        raw = str(
            item.get("message_type")
            or item.get("media_type")
            or item.get("type")
            or step.block_type
            or MessageType.TEXT
        ).strip()
        return cls._normalize_message_type(raw)

    @staticmethod
    def _normalize_message_type(message_type: str) -> str:
        normalized = message_type.strip().lower()
        if normalized in {"send_photo", "photo", "image", "picture"}:
            return MessageType.PHOTO
        if normalized in {"send_video", "video"}:
            return MessageType.VIDEO
        if normalized in {"send_voice", "voice"}:
            return MessageType.VOICE
        if normalized in {"send_video_note", "video_note", "circle", "round_video"}:
            return MessageType.VIDEO_NOTE
        if normalized in {"send_file", "file", "document", "audio", "animation"}:
            return MessageType.DOCUMENT
        return MessageType.TEXT

    @staticmethod
    def _message_item_file_name(item: dict[str, Any]) -> Optional[str]:
        value = item.get("file_name") or item.get("filename") or item.get("name")
        return str(value).strip() if value else None

    @staticmethod
    def _message_item_mime_type(item: dict[str, Any]) -> Optional[str]:
        value = item.get("mime_type") or item.get("content_type")
        return str(value).strip() if value else None

    @staticmethod
    def _step_file_name(step: FunnelStep) -> Optional[str]:
        return FunnelRuntimeService._message_item_file_name(step.config_json or {})

    @staticmethod
    def _step_mime_type(step: FunnelStep) -> Optional[str]:
        return FunnelRuntimeService._message_item_mime_type(step.config_json or {})

    @staticmethod
    def _message_delay_seconds(item: dict[str, Any]) -> int:
        try:
            return max(int(item.get("delay_seconds") or 0), 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _message_item_waits_for_answer(item: dict[str, Any]) -> bool:
        return bool(
            item.get("wait_for_answer")
            or item.get("waitForAnswer")
            or item.get("wait_answer")
            or item.get("wait_for_reply")
        )

    def _waiting_message_index(
        self,
        step: FunnelStep,
        runtime_json: dict[str, Any] | None,
    ) -> Optional[int]:
        marker = (runtime_json or {}).get("message_sequence")
        if not isinstance(marker, dict):
            return None
        if str(marker.get("step_id") or "") != str(step.id):
            return None
        try:
            message_index = int(marker.get("message_index") or 0)
        except (TypeError, ValueError):
            return None
        messages = self._message_sequence(step)
        if 0 <= message_index < len(messages):
            return message_index
        return None

    @staticmethod
    def _step_text(step: FunnelStep) -> str:
        config = step.config_json or {}
        return str(
            config.get("text")
            or config.get("message")
            or config.get("message_text")
            or config.get("body")
            or config.get("content")
            or ""
        ).strip()

    @staticmethod
    def _step_prompt(step: FunnelStep) -> str:
        config = step.config_json or {}
        fallback_by_block = {
            "ask_name": "Как вас зовут?",
            "ask_phone": "Напишите номер телефона",
            "ask_age": "Сколько вам лет?",
            "ask_country": "В какой вы стране?",
            "ask_call_time": "Когда удобно созвониться?",
            "ask_choice": "Выберите вариант",
        }
        return str(
            config.get("prompt")
            or config.get("text")
            or config.get("question")
            or config.get("question_text")
            or config.get("message")
            or config.get("message_text")
            or fallback_by_block.get(step.block_type)
            or "Напишите ответ"
        ).strip()

    def _reply_markup_for_step(self, step: FunnelStep) -> Optional[dict]:
        buttons = self._buttons_from_step(step)
        return self._reply_markup_for_buttons(step=step, buttons=buttons)

    def _reply_markup_for_buttons(
        self,
        *,
        step: FunnelStep,
        buttons: list[dict[str, Any]],
        message_index: Optional[int] = None,
    ) -> Optional[dict]:
        if not buttons:
            return None
        rows = []
        for index, button in enumerate(buttons):
            item = {"text": button["label"]}
            if button.get("type") == "url" and button.get("url"):
                item["url"] = button["url"]
            else:
                if message_index is None:
                    item["callback_data"] = f"fr:{step.id.hex}:{index}"
                else:
                    item["callback_data"] = f"fr:{step.id.hex}:{message_index}:{index}"
            rows.append([item])
        return {"inline_keyboard": rows}

    def _buttons_from_step(
        self,
        step: FunnelStep,
        *,
        message_index: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        config = step.config_json or {}
        if message_index is not None:
            messages = self._message_sequence(step)
            if 0 <= message_index < len(messages):
                return self._buttons_from_message_item(messages[message_index])
        raw_buttons = config.get("buttons") or config.get("choices") or []
        return self._normalize_buttons(raw_buttons)

    def _buttons_from_message_item(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        return self._normalize_buttons(item.get("buttons") or item.get("choices") or [])

    @staticmethod
    def _normalize_buttons(raw_buttons: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_buttons, list):
            return []

        buttons: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_buttons):
            if isinstance(raw, str):
                label = raw.strip()
                value = label
                button = {
                    "id": f"btn_{index + 1}",
                    "label": label,
                    "value": value,
                    "type": "branch",
                }
            elif isinstance(raw, dict):
                label = str(
                    raw.get("label")
                    or raw.get("text")
                    or raw.get("title")
                    or raw.get("value")
                    or f"Вариант {index + 1}"
                ).strip()
                value = str(
                    raw.get("value")
                    or raw.get("key")
                    or raw.get("id")
                    or label
                ).strip()
                button = {
                    "id": str(raw.get("id") or f"btn_{index + 1}"),
                    "label": label,
                    "value": value or label,
                    "type": str(raw.get("type") or ("url" if raw.get("url") else "branch")),
                    "target_step_id": raw.get("target_step_id"),
                    "url": raw.get("url"),
                }
            else:
                continue
            if label:
                buttons.append(button)
        return buttons

    @staticmethod
    def _parse_callback_data(
        callback_data: Optional[str],
    ) -> tuple[Optional[UUID], Optional[int], Optional[int]]:
        if not callback_data or not callback_data.startswith("fr:"):
            return None, None, None
        parts = callback_data.split(":")
        if len(parts) not in {3, 4}:
            return None, None, None
        try:
            step_id = UUID(hex=parts[1])
            if len(parts) == 3:
                return step_id, None, int(parts[2])
            return step_id, int(parts[2]), int(parts[3])
        except (TypeError, ValueError):
            return None, None, None

    @staticmethod
    def _evaluate_condition(step: FunnelStep, answer: Optional[str]) -> bool:
        config = step.config_json or {}
        conditions = config.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            return bool(answer)
        values: list[bool] = []
        normalized_answer = str(answer or "").strip().lower()
        for condition in conditions:
            if not isinstance(condition, dict):
                continue
            condition_type = condition.get("type")
            expected = str(condition.get("value") or "").strip().lower()
            if condition_type in {"text_contains", "contains"}:
                values.append(bool(expected and expected in normalized_answer))
            elif condition_type in {"button_equals", "equals"}:
                values.append(normalized_answer == expected)
        if not values:
            return bool(answer)
        return all(values) if config.get("mode") != "any" else any(values)

    @staticmethod
    def _input_timeout_seconds(step: FunnelStep) -> int:
        config = step.config_json or {}
        try:
            return max(int(config.get("timeout_seconds") or 0), 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _input_max_retries(step: FunnelStep) -> int:
        config = step.config_json or {}
        try:
            return max(int(config.get("max_retries") or 0), 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _input_retry_message(step: FunnelStep) -> str:
        config = step.config_json or {}
        validation = config.get("validation") if isinstance(config.get("validation"), dict) else {}
        return str(
            config.get("retry_message")
            or config.get("error_message")
            or validation.get("error_message")
            or "Введите корректное значение"
        ).strip()

    @staticmethod
    def _delay_step_seconds(step: FunnelStep) -> int:
        config = step.config_json or {}
        for key in ("delay_seconds", "seconds"):
            if config.get(key) is not None:
                try:
                    return max(int(config.get(key) or 0), 0)
                except (TypeError, ValueError):
                    return 0
        if config.get("minutes") is not None or config.get("delay_minutes") is not None:
            try:
                return max(int(config.get("minutes") or config.get("delay_minutes") or 0), 0) * 60
            except (TypeError, ValueError):
                return 0
        if config.get("hours") is not None or config.get("delay_hours") is not None:
            try:
                return max(int(config.get("hours") or config.get("delay_hours") or 0), 0) * 3600
            except (TypeError, ValueError):
                return 0
        return 0

    @staticmethod
    def _input_prompt_delay_seconds(step: FunnelStep) -> int:
        config = step.config_json or {}
        for key in ("delay_before_seconds", "prompt_delay_seconds"):
            if config.get(key) is not None:
                try:
                    return max(int(config.get(key) or 0), 0)
                except (TypeError, ValueError):
                    return 0
        return 0

    @staticmethod
    def _is_input_prompt_pending(
        runtime_json: dict[str, Any] | None,
        step: FunnelStep,
    ) -> bool:
        marker = (runtime_json or {}).get("input_prompt_pending_step_id")
        return str(marker or "") == str(step.id)

    @staticmethod
    def _is_no_reply_delay_step(step: FunnelStep) -> bool:
        if step.step_type != "delay":
            return False
        delay_type = str((step.config_json or {}).get("delay_type") or "").strip()
        return delay_type in {"no_reply_timeout", "reply_timeout"}

    def _validate_input_answer(self, step: FunnelStep, answer: Optional[str]) -> dict[str, Any]:
        config = step.config_json or {}
        validation_type = self._input_answer_type(step)
        text = str(answer or "").strip()

        if validation_type == "phone":
            digits = re.sub(r"\D+", "", text)
            return {
                "valid": bool(PHONE_RE.match(text)) and 10 <= len(digits) <= 15,
                "normalized": self._normalize_phone(text),
            }
        if validation_type == "email":
            return {"valid": bool(EMAIL_RE.match(text)), "normalized": text}
        if validation_type == "name":
            return {
                "valid": len(text) >= 2 and not text.isdigit(),
                "normalized": text,
            }
        if validation_type == "number":
            try:
                float(text.replace(",", "."))
            except ValueError:
                return {"valid": False}
            return {"valid": True}
        if validation_type == "choice":
            return {"valid": self._choice_for_answer(step, text) is not None}
        if validation_type in {"date", "time"}:
            return {"valid": bool(text)}
        return {"valid": bool(text) or not config.get("wait_for_answer", True)}

    @staticmethod
    def _input_answer_type(step: FunnelStep) -> str:
        config = step.config_json or {}
        validation = config.get("validation") if isinstance(config.get("validation"), dict) else {}
        raw_type = str(
            validation.get("type")
            or config.get("answer_type")
            or config.get("data_type")
            or config.get("field_type")
            or ""
        ).strip().lower()
        if raw_type:
            return raw_type
        block_type = step.block_type
        if block_type == "ask_phone":
            return "phone"
        if block_type == "ask_email":
            return "email"
        if block_type == "ask_name":
            return "name"
        if block_type in {"ask_number", "ask_age", "ask_budget"}:
            return "number"
        if block_type == "ask_choice":
            return "choice"
        if block_type == "ask_date":
            return "date"
        if block_type == "ask_time":
            return "time"
        return "text"

    @classmethod
    def _input_target_field(cls, step: FunnelStep) -> Optional[str]:
        config = step.config_json or {}
        field = cls._normalize_field_key(
            config.get("field_key")
            or config.get("custom_field_key")
            or config.get("save_to")
            or config.get("lead_field_key")
            or config.get("variable_name")
        )
        if field:
            return field
        fallback_by_block = {
            "ask_age": "age",
            "ask_country": "country",
            "ask_call_time": "call_time_text",
            "ask_comment": "comment",
            "ask_city": "city",
            "ask_budget": "budget",
        }
        return fallback_by_block.get(step.block_type)

    @staticmethod
    def _normalize_phone(value: str) -> str:
        digits = re.sub(r"\D+", "", value)
        return f"+{digits}" if digits else value.strip()

    def _choice_for_answer(self, step: FunnelStep, answer: Optional[str]) -> Optional[dict[str, Any]]:
        normalized = str(answer or "").strip().lower()
        for choice in self._buttons_from_step(step):
            if normalized in {
                str(choice.get("value") or "").strip().lower(),
                str(choice.get("label") or "").strip().lower(),
                str(choice.get("id") or "").strip().lower(),
            }:
                return choice
        return None

    @staticmethod
    def _runtime_with_answer(
        runtime_json: Optional[dict],
        *,
        step_id: UUID,
        answer: Any,
        button: Optional[dict[str, Any]] = None,
    ) -> dict:
        runtime = dict(runtime_json or {})
        runtime["last_answer"] = answer
        runtime["last_answer_step_id"] = str(step_id)
        retries = dict(runtime.get("input_retries") or {})
        retries[str(step_id)] = 0
        runtime["input_retries"] = retries
        if button is not None:
            runtime["last_button"] = {
                "id": button.get("id"),
                "value": button.get("value"),
                "label": button.get("label"),
                "target_step_id": str(button.get("target_step_id")) if button.get("target_step_id") else None,
            }
        return runtime

    @staticmethod
    def _input_retry_count(runtime_json: Optional[dict], step_id: UUID) -> int:
        retries = (runtime_json or {}).get("input_retries") or {}
        try:
            return int(retries.get(str(step_id)) or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _runtime_with_retry_count(
        runtime_json: Optional[dict],
        step_id: UUID,
        retry_count: int,
    ) -> dict:
        runtime = dict(runtime_json or {})
        retries = dict(runtime.get("input_retries") or {})
        retries[str(step_id)] = retry_count
        runtime["input_retries"] = retries
        return runtime

    @classmethod
    def _normalize_field_key(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _transform_value(field_key: str, answer: Any) -> Any:
        if answer is None:
            return None
        if field_key == "age":
            try:
                return int(str(answer).strip())
            except ValueError:
                return None
        if field_key == "has_card":
            normalized = str(answer).strip().lower()
            if normalized in {"true", "1", "yes", "y", "да", "есть"}:
                return True
            if normalized in {"false", "0", "no", "n", "нет"}:
                return False
            return None
        return str(answer).strip()
