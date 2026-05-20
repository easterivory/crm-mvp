from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.funnel import FunnelStep, FunnelVersion
from app.repositories.funnel_repository import FunnelRepository
from app.services.funnel_block_registry import LEAD_FIELD_KEYS


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

    async def get_published_funnel_for_bot(self, bot_id: UUID) -> Optional[FunnelVersion]:
        return await self.repo.get_published_for_bot(bot_id)

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
            return None
        await self.repo.upsert_chat_funnel_state(
            chat_id=chat_id,
            funnel_id=funnel_id,
            funnel_version_id=funnel_version_id,
            current_step_id=trigger.id,
            entered_step_at=datetime.now(timezone.utc),
        )
        return trigger

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
        if not relevant:
            return
        lead = await self.repo.get_lead_by_chat(chat_id)
        if lead is None:
            return

        direct_values: dict[str, Any] = {}
        custom_values: dict[str, Any] = {}
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
