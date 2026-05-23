from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import MessageType, SenderType
from app.models.funnel import FunnelStep, FunnelVersion
from app.repositories.chat_repository import ChatRepository
from app.repositories.funnel_repository import FunnelRepository
from app.schemas.message import MessageCreate
from app.services.funnel_block_registry import LEAD_FIELD_KEYS

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
        from app.services.message_service import MessageService

        self.message_service = MessageService(db)

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
        if state is None or state.completed_at is not None:
            return False

        step = await self.repo.get_step(state.current_step_id)
        if step is None:
            return False

        if self._is_input_step(step):
            await self.apply_field_mappings(
                chat_id=chat_id,
                step_id=step.id,
                answer=text,
            )
            next_step = await self._move_from_step(
                chat_id=chat_id,
                step=step,
                answer=text,
            )
            if next_step is not None:
                await self._execute_from_step(chat_id=chat_id, step=next_step, answer=text)
            return True

        if self._step_has_buttons(step):
            return True

        await self._execute_from_step(chat_id=chat_id, step=step, answer=text)
        return True

    async def process_incoming_button(
        self,
        *,
        chat_id: UUID,
        callback_data: Optional[str],
        fallback_text: Optional[str] = None,
    ) -> bool:
        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None or state.completed_at is not None:
            return False

        step = await self.repo.get_step(state.current_step_id)
        if step is None:
            return False

        payload_step_id, _ = self._parse_callback_data(callback_data)
        if payload_step_id is not None and payload_step_id != step.id:
            logger.info(
                "Ignoring stale funnel callback chat_id=%s state_step=%s payload_step=%s",
                chat_id,
                step.id,
                payload_step_id,
            )
            return True

        answer = await self.resolve_callback_value(
            chat_id=chat_id,
            callback_data=callback_data,
        )
        answer = answer or fallback_text

        if self._is_input_step(step):
            await self.apply_field_mappings(
                chat_id=chat_id,
                step_id=step.id,
                answer=answer,
            )

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
        step_id, index = self._parse_callback_data(callback_data)
        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None:
            return None
        step = await self.repo.get_step(step_id or state.current_step_id)
        if step is None:
            return None
        buttons = self._buttons_from_step(step)
        if index is None or index < 0 or index >= len(buttons):
            return None
        return buttons[index]["value"]

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
        await self.repo.upsert_chat_funnel_state(
            chat_id=chat_id,
            funnel_id=state.funnel_id,
            funnel_version_id=state.funnel_version_id,
            current_step_id=next_step.id,
            entered_step_at=datetime.now(timezone.utc),
            completed_at=completed_at,
        )
        return next_step

    async def find_stuck_chats_for_push_rules(self):
        return await self.repo.find_stuck_chats_for_push_rules()

    async def mark_push_sent(self, *, chat_id: UUID, push_rule_id: UUID) -> None:
        # Placeholder for a future audit/event table. Keeping the method in place
        # lets the worker call a stable API without inventing runtime writes later.
        _ = (chat_id, push_rule_id)

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
            )

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
                await self._send_step_message(chat_id=chat_id, step=current)
                if self._step_has_buttons(current):
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

            if self._is_input_step(current):
                await self._send_input_prompt(chat_id=chat_id, step=current)
                return current

            if current.step_type == "condition":
                outcome = self._evaluate_condition(current, answer)
                next_step = await self._move_from_step(
                    chat_id=chat_id,
                    step=current,
                    answer="true" if outcome else "false",
                )
                if next_step is None:
                    return None
                current = next_step
                continue

            if current.step_type == "action":
                next_step = await self._move_from_step(
                    chat_id=chat_id,
                    step=current,
                    answer=answer,
                )
                if next_step is None:
                    return None
                current = next_step
                continue

            if current.step_type == "finish":
                await self._mark_completed(chat_id)
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

    async def _mark_completed(self, chat_id: UUID) -> None:
        state = await self.repo.get_chat_funnel_state(chat_id)
        if state is None:
            return
        await self.repo.upsert_chat_funnel_state(
            chat_id=chat_id,
            funnel_id=state.funnel_id,
            funnel_version_id=state.funnel_version_id,
            current_step_id=state.current_step_id,
            entered_step_at=state.entered_step_at,
            completed_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _select_edge(edges, answer: Optional[str]):
        if not edges:
            return None
        if answer is None:
            return edges[0]

        normalized = str(answer).strip().lower()
        for edge in edges:
            condition = edge.condition_json or {}
            candidates = [
                condition.get("outcome"),
                condition.get("label"),
                condition.get("value"),
                condition.get("button_value"),
                condition.get("choice"),
            ]
            if any(str(candidate).strip().lower() == normalized for candidate in candidates if candidate is not None):
                return edge
        return edges[0]

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
        if not buttons:
            return None
        return {
            "inline_keyboard": [
                [
                    {
                        "text": button["label"],
                        "callback_data": f"fr:{step.id.hex}:{index}",
                    }
                ]
                for index, button in enumerate(buttons)
            ]
        }

    @staticmethod
    def _buttons_from_step(step: FunnelStep) -> list[dict[str, str]]:
        config = step.config_json or {}
        raw_buttons = config.get("buttons") or config.get("choices") or []
        if not isinstance(raw_buttons, list):
            return []

        buttons: list[dict[str, str]] = []
        for index, raw in enumerate(raw_buttons):
            if isinstance(raw, str):
                label = raw.strip()
                value = label
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
            else:
                continue
            if label:
                buttons.append({"label": label, "value": value or label})
        return buttons

    @staticmethod
    def _parse_callback_data(callback_data: Optional[str]) -> tuple[Optional[UUID], Optional[int]]:
        if not callback_data or not callback_data.startswith("fr:"):
            return None, None
        parts = callback_data.split(":", 2)
        if len(parts) != 3:
            return None, None
        try:
            return UUID(hex=parts[1]), int(parts[2])
        except (TypeError, ValueError):
            return None, None

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
