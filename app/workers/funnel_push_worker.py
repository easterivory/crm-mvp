"""Gambling-project push rules worker."""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.core.database import get_db_session
from app.repositories.funnel_repository import FunnelRepository
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.operational_alert_service import send_operational_alert

logger = logging.getLogger(__name__)


async def _candidate_ids(limit: int) -> list[tuple[UUID, UUID]]:
    async with get_db_session() as db:
        try:
            candidates = await FunnelRepository(db).find_stuck_chats_for_push_rules(
                limit=limit,
            )
            result = [(state.chat_id, rule.id) for state, rule in candidates]
            await db.rollback()
            return result
        except Exception:
            await db.rollback()
            raise


async def _process_candidate(chat_id: UUID, push_rule_id: UUID) -> bool:
    async with get_db_session() as db:
        try:
            processed = await FunnelRuntimeService(
                db,
                release_transaction_before_external_io=True,
            ).mark_push_sent(
                chat_id=chat_id,
                push_rule_id=push_rule_id,
            )
            await db.commit()
            return processed
        except Exception:
            await db.rollback()
            raise


async def run_once(limit: int = 100) -> int:
    processed = 0
    for chat_id, push_rule_id in await _candidate_ids(limit):
        try:
            if await _process_candidate(chat_id, push_rule_id):
                processed += 1
        except Exception as exc:
            logger.exception(
                "Funnel push failed chat_id=%s push_rule_id=%s",
                chat_id,
                push_rule_id,
            )
            await send_operational_alert(
                component="funnel_push_worker",
                title="Gambling funnel push failed",
                details={
                    "chat_id": chat_id,
                    "push_rule_id": push_rule_id,
                    "error": f"{exc.__class__.__name__}: {str(exc)[:1000]}",
                },
                dedupe_key=f"funnel-push:{exc.__class__.__name__}",
            )
    return processed


async def run_loop(interval_seconds: float = 5.0) -> None:
    logger.info("Starting funnel push worker")
    while True:
        try:
            processed = await run_once()
            if processed:
                logger.info("Processed funnel pushes count=%s", processed)
        except Exception as exc:
            logger.exception("Funnel push worker loop failed")
            await send_operational_alert(
                component="funnel_push_worker",
                title="Gambling funnel push worker is unhealthy",
                details={"error": f"{exc.__class__.__name__}: {str(exc)[:1000]}"},
                dedupe_key=f"funnel-push-loop:{exc.__class__.__name__}",
            )
        await asyncio.sleep(interval_seconds)
