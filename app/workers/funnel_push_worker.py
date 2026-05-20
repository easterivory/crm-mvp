"""
Funnel push worker foundation.

Not wired into app.workers.__main__ yet: v1 stores push rules and exposes
runtime lookup, but production scheduling should be enabled only after the
message-sending/audit semantics are finalized.
"""
import logging

from app.core.database import get_db_session
from app.services.funnel_runtime_service import FunnelRuntimeService

logger = logging.getLogger(__name__)


async def run_once(limit: int = 100) -> int:
    async with get_db_session() as db:
        runtime = FunnelRuntimeService(db)
        stuck_items = await runtime.find_stuck_chats_for_push_rules()
        processed = 0
        for state, rule in stuck_items[:limit]:
            logger.info(
                "funnel_push_worker candidate chat=%s step=%s rule=%s delay=%s",
                state.chat_id,
                state.current_step_id,
                rule.id,
                rule.delay_minutes,
            )
            await runtime.mark_push_sent(chat_id=state.chat_id, push_rule_id=rule.id)
            processed += 1
        await db.commit()
        return processed
