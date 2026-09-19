"""Gambling-project push rules worker."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from app.core.database import get_db_session
from app.repositories.funnel_repository import FunnelRepository
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.operational_alert_service import send_operational_alert
from app.services.telegram_sender import TelegramDeliveryError

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
    attempted_at = datetime.now(timezone.utc)
    context: dict[str, str] = {}
    async with get_db_session() as db:
        try:
            repo = FunnelRepository(db)
            if not await repo.lock_chat_for_runtime(chat_id):
                return False
            if await repo.is_push_delivery_suspended(chat_id):
                return False
            state = await repo.get_chat_funnel_state(chat_id)
            if state is None:
                return False
            context = {
                "funnel_id": str(state.funnel_id),
                "version_id": str(state.funnel_version_id),
                "step_id": str(state.current_step_id),
                "entered_step_at": state.entered_step_at.isoformat(),
            }
            attempted_at = datetime.now(timezone.utc)
            processed = await FunnelRuntimeService(
                db,
                release_transaction_before_external_io=True,
                raise_on_telegram_delivery_error=True,
            ).mark_push_sent(
                chat_id=chat_id,
                push_rule_id=push_rule_id,
            )
            await db.commit()
            if processed:
                logger.info(
                    "Funnel push sent chat_id=%s rule_id=%s context=%s",
                    chat_id, push_rule_id, context,
                )
            return processed
        except TelegramDeliveryError as exc:
            await db.rollback()
            if not exc.cannot_initiate:
                logger.warning(
                    "Funnel push delivery rejected chat_id=%s rule_id=%s context=%s "
                    "method=%s code=%s transient=%s retry_after=%s reason=%s",
                    chat_id, push_rule_id, context, exc.method, exc.error_code,
                    exc.transient, exc.retry_after, exc.description,
                )
                raise
            # Persist separately: the sending transaction may have been rolled back
            # or committed before network IO. Never reuse expired ORM state here.
            async with get_db_session() as failure_db:
                failure_repo = FunnelRepository(failure_db)
                if not await failure_repo.lock_chat_for_runtime(chat_id):
                    raise
                current = await failure_repo.get_chat_funnel_state(chat_id)
                if (
                    current is None
                    or current.entered_step_at.isoformat() != context.get("entered_step_at")
                    or str(current.current_step_id) != context.get("step_id")
                    or str(current.funnel_version_id) != context.get("version_id")
                ):
                    logger.info("Funnel push suspension obsolete chat_id=%s rule_id=%s context=%s", chat_id, push_rule_id, context)
                    return False
                runtime = dict(current.runtime_json or {})
                runtime["push_delivery_suspended"] = {
                    "at_epoch": attempted_at.timestamp(),
                    "reason": "telegram_cannot_initiate_conversation",
                    "rule_id": str(push_rule_id),
                    **context,
                }
                await failure_repo.update_chat_funnel_runtime(chat_id=chat_id, runtime_json=runtime)
                await failure_db.commit()
            logger.warning(
                "Funnel pushes suspended chat_id=%s rule_id=%s context=%s "
                "reason=telegram_cannot_initiate_conversation code=%s "
                "resume_on=new_incoming_message_or_step_entry sent=False",
                chat_id, push_rule_id, context, exc.error_code,
            )
            await send_operational_alert(
                component="funnel_push_worker",
                title="Funnel pushes suspended: Telegram cannot initiate conversation",
                details={"chat_id": chat_id, "push_rule_id": push_rule_id, **context,
                         "reason": exc.description, "sent": False,
                         "resume_on": "new incoming message or step entry"},
                dedupe_key=f"funnel-push-cannot-initiate:{chat_id}",
            )
            return False
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
