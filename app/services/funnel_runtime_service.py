from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LeadStatusCode, MessageType, SenderType
from app.models.funnel import FunnelScheduledJob, FunnelStep, FunnelVersion
from app.repositories.chat_repository import ChatRepository
from app.repositories.funnel_repository import FunnelRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.partner_repository import PartnerIntegrationRepository
from app.repositories.tag_repository import TagRepository
from app.schemas.message import MessageCreate
from app.services.funnel_block_registry import LEAD_FIELD_KEYS
from app.services.lead_scoring_service import LeadScoringService

logger = logging.getLogger(__name__)


DIRECT_LEAD_FIELDS = {
    "name",
    "phone",
    "username",
    "age",
    "country",
    "call_time_text",
    "has_card",
}


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
        self.chat_repo = ChatRepository(db)
        self.lead_repo = LeadRepository(db)
        self.partner_repo = PartnerIntegrationRepository(db)
        self.tag_repo = TagRepository(db)
        from app.services.message_service import MessageService

        self.message_service = MessageService(db)
        self.scoring = LeadScoringService(db)

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
        if state is None or state.funnel_version_id != active_funnel_version_id:
            return "not_started", state
        if state.completed_at is not None:
            return "completed", state

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
    ) -> Optional[FunnelStep]:
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
        await self.repo.upsert_chat_funnel_state(
            chat_id=chat_id,
            funnel_id=funnel_id,
            funnel_version_id=funnel_version_id,
            current_step_id=trigger.id,
            entered_step_at=datetime.now(timezone.utc),
            waiting_for_answer=False,
            runtime_json={},
        )
        await self._log_runtime_step(chat_id=chat_id, step=trigger, status="success")
        logger.info(
            "Starting active funnel chat_id=%s funnel_id=%s funnel_version_id=%s trigger_step_id=%s",
            chat_id,
            funnel_id,
            funnel_version_id,
            trigger.id,
        )
        return await self._execute_from_step(chat_id=chat_id, step=trigger)

    async def get_current_step(self, chat_id: UUID) -> Optional[FunnelStep]:
        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None or state.completed_at is not None:
            return None
        return await self.repo.get_step(state.current_step_id)

    async def process_user_answer(
        self,
        *,
        chat_id: UUID,
        text: Optional[str] = None,
        button_payload: Optional[str] = None,
    ) -> Optional[FunnelStep]:
        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None or state.completed_at is not None:
            return None

        answer = button_payload if button_payload is not None else text
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

        if state.waiting_for_answer or self._is_input_step(step):
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
        if state is None:
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
            if save_to in LEAD_FIELD_KEYS:
                value = self._transform_value(save_to, answer)
                if save_to in DIRECT_LEAD_FIELDS:
                    direct_values[save_to] = value
                else:
                    custom_values[save_to] = value

        for mapping in relevant:
            if mapping.lead_field_key not in LEAD_FIELD_KEYS:
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

            text = self._message_item_text(item)
            buttons = self._buttons_from_message_item(item)
            if text:
                await self._create_outgoing_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=self._reply_markup_for_buttons(
                        step=step,
                        buttons=buttons,
                        message_index=index,
                    ),
                )
            if buttons:
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
        text = self._step_text(step)
        if not text:
            return
        await self._create_outgoing_message(
            chat_id=chat_id,
            text=text,
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
        await self.repo.create_scheduled_job(
            job_type=job_type,
            chat_id=chat_id,
            funnel_state_id=state.id,
            funnel_id=state.funnel_id,
            funnel_version_id=state.funnel_version_id,
            step_id=step.id,
            run_at=datetime.now(timezone.utc) + timedelta(seconds=delay_seconds),
            payload_json=payload_json,
        )

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
    ) -> None:
        chat = await self.chat_repo.get_by_id(chat_id)
        if chat is None:
            return
        await self.message_service.create_message(
            chat_id=chat_id,
            project_id=chat.project_id,
            data=MessageCreate(
                message_type=MessageType.TEXT,
                sender_type=SenderType.BOT,
                sender_id=None,
                body=text,
                reply_markup=reply_markup,
            ),
        )

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
        outcomes = config.get("outcomes")
        if isinstance(outcomes, list):
            for item in outcomes:
                if not isinstance(item, dict):
                    continue
                labels = {str(item.get("id") or "").lower(), str(item.get("label") or "").lower()}
                if outcome.lower() in labels and item.get("target_step_id"):
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

    async def _evaluate_condition_outcome(
        self,
        *,
        chat_id: UUID,
        step: FunnelStep,
        answer: Optional[str],
    ) -> str:
        config = step.config_json or {}
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
            return "true" if hold_enabled else "false"

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

    async def _evaluate_single_condition(self, *, chat_id: UUID, condition: dict) -> bool:
        source = str(condition.get("source") or condition.get("field") or "last_answer")
        field = condition.get("field")
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
        if source == "lead_field":
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
        return aliases

    @staticmethod
    def _is_message_step(step: FunnelStep) -> bool:
        return step.step_type == "message" or step.block_type in {
            "generic_message",
            "send_text",
            "send_inline_buttons",
            "send_personalized_message",
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
        if not text:
            return []
        return [
            {
                "id": "legacy_text",
                "type": config.get("message_type") or "text",
                "text": text,
                "delay_seconds": config.get("delay_seconds") or 0,
                "buttons": config.get("buttons") or [],
            }
        ]

    @staticmethod
    def _message_item_text(item: dict[str, Any]) -> str:
        return str(
            item.get("text")
            or item.get("message")
            or item.get("message_text")
            or item.get("body")
            or item.get("content")
            or ""
        ).strip()

    @staticmethod
    def _message_delay_seconds(item: dict[str, Any]) -> int:
        try:
            return max(int(item.get("delay_seconds") or 0), 0)
        except (TypeError, ValueError):
            return 0

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
        return str(config.get("retry_message") or "Введите корректное значение").strip()

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
    def _is_no_reply_delay_step(step: FunnelStep) -> bool:
        if step.step_type != "delay":
            return False
        delay_type = str((step.config_json or {}).get("delay_type") or "").strip()
        return delay_type in {"no_reply_timeout", "reply_timeout"}

    def _validate_input_answer(self, step: FunnelStep, answer: Optional[str]) -> dict[str, Any]:
        config = step.config_json or {}
        validation = config.get("validation") if isinstance(config.get("validation"), dict) else {}
        validation_type = str(validation.get("type") or config.get("answer_type") or "text")
        text = str(answer or "").strip()

        if validation_type == "phone":
            digits = re.sub(r"\D+", "", text)
            return {"valid": len(digits) >= 10}
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
