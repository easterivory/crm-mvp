"""Durable, fail-closed execution markers for AI steps only."""
from __future__ import annotations

from dataclasses import asdict
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.funnel import ChatFunnelState, FunnelStep
from app.services.ai_response_execution_service import AIResponseExecutionOutcome


class AIDeliveryStateService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def current(
        self, chat_id: UUID, step_id: UUID, execution_id: str | None = None
    ) -> ChatFunnelState | None:
        state = (
            await self.db.execute(
                select(ChatFunnelState)
                .where(ChatFunnelState.chat_id == chat_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if (
            state is None
            or state.is_paused
            or state.completed_at is not None
            or state.current_step_id != step_id
        ):
            return None
        if execution_id is not None:
            marker = dict((state.runtime_json or {}).get("ai_execution") or {})
            if (
                marker.get("id") != execution_id
                or marker.get("state_id") != str(state.id)
                or marker.get("visit") != self.visit(state)
                or marker.get("version_id") != str(state.funnel_version_id)
            ):
                return None
        return state

    @staticmethod
    def visit(state: ChatFunnelState) -> str | None:
        return state.entered_step_at.isoformat() if state.entered_step_at else None

    @staticmethod
    def write(state: ChatFunnelState, marker: dict) -> None:
        state.runtime_json = {
            **(state.runtime_json or {}),
            "ai_execution": dict(marker),
        }

    async def begin(
        self, chat_id: UUID, step: FunnelStep, job_id: UUID | None
    ) -> tuple[str, dict] | None:
        state = await self.current(chat_id, step.id)
        if state is None or state.funnel_version_id != step.funnel_version_id:
            return None
        previous = dict((state.runtime_json or {}).get("ai_execution") or {})
        if (
            previous.get("step_id") == str(step.id)
            and previous.get("visit") == self.visit(state)
            and previous.get("state_id") == str(state.id)
        ):
            # A different duplicate task must not interrupt the owner while it is generating.
            if previous.get("job_id") != str(job_id):
                return None
            return str(previous["id"]), previous
        marker = {
            "id": str(uuid4()),
            "state_id": str(state.id),
            "step_id": str(step.id),
            "version_id": str(state.funnel_version_id),
            "visit": self.visit(state),
            "job_id": str(job_id),
            "status": "generating",
            "next_index": 0,
            "inflight_index": None,
        }
        self.write(state, marker)
        await self.db.commit()
        return marker["id"], marker

    async def save_outcome(
        self,
        chat_id: UUID,
        step_id: UUID,
        execution_id: str,
        outcome: AIResponseExecutionOutcome,
    ) -> bool:
        state = await self.current(chat_id, step_id, execution_id)
        if state is None:
            return False
        marker = dict(state.runtime_json["ai_execution"])
        marker.update(status="ready", outcome=asdict(outcome))
        self.write(state, marker)
        return True
