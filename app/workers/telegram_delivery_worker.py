"""DB-backed intake and dispatch loops. They keep working while Redis is down."""
from __future__ import annotations

import asyncio
import logging
import time
from math import ceil
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, delete, event, exists, func, or_, select, update
from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeout
from sqlalchemy.orm import aliased

from app.core.arq_client import close_arq_client
from app.core.config import settings
from app.core.delivery_attempt import delivery_attempt
from app.core.database import get_db_session
from app.models.telegram_delivery import RuntimeDispatch, TelegramInbox
from app.services.funnel_job_queue import enqueue_funnel_chat_action, enqueue_funnel_scheduled_job
from app.services.funnel_start_queue import enqueue_funnel_start
from app.services.operational_alert_service import send_operational_alert
from app.services.telegram_service import TelegramService
from app.services.user_input_queue import enqueue_user_input

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc)


async def _claim_inbox() -> tuple[UUID, UUID, dict, int] | None:
    earlier = aliased(TelegramInbox)
    async with get_db_session() as db:
        row = await db.scalar(select(TelegramInbox).where(
            TelegramInbox.status == "pending", TelegramInbox.available_at <= _now(),
            ~exists(select(earlier.id).where(
                earlier.bot_id == TelegramInbox.bot_id, earlier.peer_key == TelegramInbox.peer_key,
                earlier.status.in_(["pending", "processing"]),
                or_(earlier.created_at < TelegramInbox.created_at,
                    and_(earlier.created_at == TelegramInbox.created_at, earlier.update_id < TelegramInbox.update_id)),
            )),
        ).order_by(TelegramInbox.available_at, TelegramInbox.created_at, TelegramInbox.update_id).limit(1).with_for_update(skip_locked=True))
        if row is None:
            return None
        row.status, row.claimed_at = "processing", _now()
        row.attempts += 1
        result = (row.id, row.bot_id, dict(row.payload_json), row.attempts)
        await db.commit()
        return result


async def process_next_inbox() -> bool:
    claimed = await _claim_inbox()
    if claimed is None:
        return False
    inbox_id, bot_id, payload, attempts = claimed
    started = time.monotonic()
    progress = {"committed": False, "external_io_started": False}
    token = delivery_attempt.set(progress)

    def committed(session):
        # A savepoint commit is not a durable boundary. A real commit may
        # precede network delivery: after that, replay needs human review.
        if not session.in_nested_transaction():
            progress["committed"] = True

    try:
        async with asyncio.timeout(max(settings.TELEGRAM_INBOX_TIMEOUT_SECONDS, 1)):
            async with get_db_session() as db:
                event.listen(db.sync_session, "after_commit", committed)
                try:
                    service = TelegramService(db, release_transaction_before_external_io=True)
                    parsed = TelegramService.parse_update(payload)
                    if parsed is None:
                        raise ValueError("Stored Telegram update cannot be parsed")
                    await service.handle_webhook_update(update=parsed, bot_id=bot_id)
                    await db.execute(update(TelegramInbox).where(
                        TelegramInbox.id == inbox_id, TelegramInbox.status == "processing",
                    ).values(status="done", completed_at=_now(), last_error=None))
                    await db.commit()
                    await service.dispatch_post_commit_actions()
                finally:
                    event.remove(db.sync_session, "after_commit", committed)
        logger.info("Telegram intake processed inbox_id=%s bot_id=%s update_id=%s elapsed_ms=%s attempts=%s",
                    inbox_id, bot_id, payload["update_id"], int((time.monotonic() - started) * 1000), attempts)
    except Exception as exc:
        # Only DB acquisition/transaction failures before a durable boundary
        # are retried. Never blindly replay callbacks or partial deliveries.
        safe_retry = isinstance(exc, (DBAPIError, PoolTimeout)) and not any(progress.values())
        pending = safe_retry and attempts < max(settings.TELEGRAM_INBOX_MAX_ATTEMPTS, 1)
        error = f"{type(exc).__name__}; stage=handle_update; committed={progress['committed']}; external_io_started={progress['external_io_started']}"
        async with get_db_session() as db:
            await db.execute(update(TelegramInbox).where(
                TelegramInbox.id == inbox_id, TelegramInbox.status == "processing",
            ).values(status="pending" if pending else "review", last_error=error,
                     available_at=_now() + timedelta(seconds=min(2 ** attempts, 60))))
            await db.commit()
        logger.exception("Telegram intake failed inbox_id=%s bot_id=%s update_id=%s attempts=%s retry=%s elapsed_ms=%s",
                         inbox_id, bot_id, payload["update_id"], attempts, pending, int((time.monotonic() - started) * 1000))
        if not pending:
            await send_operational_alert(component="telegram_inbox", title="Accepted Telegram update needs review",
                details={"inbox_id": inbox_id, "bot_id": bot_id, "update_id": payload["update_id"], "error": error},
                dedupe_key="telegram-inbox-review")
    finally:
        delivery_attempt.reset(token)
    return True


async def _dispatch(kind: str, payload: dict) -> bool:
    if kind == "input":
        return await enqueue_user_input(UUID(payload["chat_id"]), UUID(payload["message_id"]), delay_seconds=0)
    if kind == "start":
        return await enqueue_funnel_start(UUID(payload["chat_id"]), UUID(payload["message_id"]),
                                          fresh_lifecycle=payload["fresh_lifecycle"])
    if kind == "scheduled":
        delay = max(0, (datetime.fromisoformat(payload["run_at"]) - _now()).total_seconds())
        # Stable IDs make a lost Redis acknowledgement safe to retry.
        return await enqueue_funnel_scheduled_job(UUID(payload["job_id"]), delay) is not None
    if kind == "action":
        remaining = (datetime.fromisoformat(payload["expires_at"]) - _now()).total_seconds()
        if remaining <= 0:
            return True
        return await enqueue_funnel_chat_action(
            scheduled_job_id=UUID(payload["scheduled_job_id"]), chat_id=UUID(payload["chat_id"]),
            action=payload["action"], duration_seconds=min(ceil(remaining), payload["duration_seconds"]),
        ) is not None
    raise ValueError(f"Unknown runtime dispatch kind: {kind}")


async def dispatch_once() -> bool:
    async with get_db_session() as db:
        row = await db.scalar(select(RuntimeDispatch).where(
            RuntimeDispatch.status == "pending", RuntimeDispatch.available_at <= _now(),
        ).order_by(RuntimeDispatch.available_at, RuntimeDispatch.created_at).limit(1).with_for_update(skip_locked=True))
        if row is None:
            return False
        dispatch_id, kind, payload = row.id, row.kind, dict(row.payload_json)
        row.attempts += 1
        row.available_at = _now() + timedelta(seconds=60)
        claimed_until = row.available_at
        await db.commit()
    # No DB session/connection or chat lock is held during Redis I/O.
    try:
        accepted = await _dispatch(kind, payload)
        error = None if accepted else "Redis enqueue unavailable"
    except Exception as exc:
        accepted, error = False, type(exc).__name__
        logger.exception("Runtime dispatch failed dispatch_id=%s kind=%s", dispatch_id, kind)
    async with get_db_session() as db:
        # Input/start stay pending until the consumer acknowledges processing.
        # Their stable ARQ IDs also cover lost enqueue responses and restarts.
        values = {"last_error": error, "available_at": _now() + timedelta(seconds=60 if accepted else 5)}
        if accepted and kind in {"scheduled", "action"}:
            values.update(status="done", completed_at=_now())
        await db.execute(update(RuntimeDispatch).where(
            RuntimeDispatch.id == dispatch_id, RuntimeDispatch.status == "pending",
            RuntimeDispatch.available_at == claimed_until,
        ).values(**values))
        await db.commit()
    return True


async def maintain_delivery_queues() -> None:
    async with get_db_session() as db:
        # A killed handler may have sent externally. Preserve it for inspection,
        # rather than reclaiming it and risking duplicate replies.
        stale = await db.execute(update(TelegramInbox).where(
            TelegramInbox.status == "processing",
            TelegramInbox.claimed_at < _now() - timedelta(seconds=max(settings.TELEGRAM_INBOX_TIMEOUT_SECONDS, 1) + 60),
        ).values(status="review", last_error="Handler interrupted; delivery outcome needs review"))
        await db.execute(update(RuntimeDispatch).where(
            RuntimeDispatch.status == "running",
            RuntimeDispatch.claimed_at < _now() - timedelta(seconds=max(settings.FUNNEL_SCHEDULED_JOB_TIMEOUT_SECONDS, 300) + 60),
        ).values(status="review", last_error="Runtime handler interrupted; delivery outcome needs review"))
        review_count = await db.scalar(select(func.count()).select_from(TelegramInbox).where(TelegramInbox.status == "review"))
        dispatch_reviews = await db.scalar(select(func.count()).select_from(RuntimeDispatch).where(RuntimeDispatch.status == "review"))
        oldest_inbox = await db.scalar(select(func.min(TelegramInbox.created_at)).where(TelegramInbox.status == "pending"))
        oldest_dispatch = await db.scalar(select(func.min(RuntimeDispatch.created_at)).where(
            RuntimeDispatch.status == "pending",
            or_(RuntimeDispatch.last_error.is_(None), RuntimeDispatch.last_error != "waiting_runtime", RuntimeDispatch.available_at <= _now()),
        ))
        cutoff = _now() - timedelta(days=max(settings.TELEGRAM_INBOX_RETENTION_DAYS, 1))
        # Bounded cleanup removes only transport receipts, never CRM history.
        for model in (TelegramInbox, RuntimeDispatch):
            ids = select(model.id).where(model.status == "done", model.completed_at < cutoff).limit(1000)
            await db.execute(delete(model).where(model.id.in_(ids)))
        await db.commit()
    if review_count:
        await send_operational_alert(component="telegram_inbox", title="Telegram intake needs review",
            details={"review_count": review_count, "new_stale": stale.rowcount}, dedupe_key="telegram-inbox-review")
    if dispatch_reviews:
        await send_operational_alert(component="runtime_dispatch", title="Funnel dispatches need review",
            details={"review_count": dispatch_reviews}, dedupe_key="runtime-dispatch-review")
    age = max(((_now() - oldest).total_seconds()
               for oldest in (oldest_inbox, oldest_dispatch) if oldest is not None), default=0)
    logger.info("Telegram delivery heartbeat inbox_oldest=%s dispatch_oldest=%s inbox_review=%s dispatch_review=%s",
                oldest_inbox, oldest_dispatch, review_count, dispatch_reviews)
    if age > 300:
        await send_operational_alert(component="telegram_delivery", title="Telegram processing backlog",
            details={"oldest_age_seconds": int(age), "inbox_oldest": oldest_inbox, "dispatch_oldest": oldest_dispatch},
            dedupe_key="telegram-delivery-backlog")


async def _intake_loop() -> None:
    while True:
        try:
            processed = await process_next_inbox()
            if not processed:
                await asyncio.sleep(0.25)
        except Exception:
            logger.exception("Telegram intake worker unavailable; accepted updates remain in DB")
            await asyncio.sleep(5)


async def _dispatch_loop() -> None:
    while True:
        try:
            if not await dispatch_once():
                await asyncio.sleep(0.25)
        except Exception:
            logger.exception("Runtime dispatcher unavailable; dispatches remain in DB")
            await asyncio.sleep(5)


async def _maintenance_loop() -> None:
    while True:
        try:
            await maintain_delivery_queues()
        except Exception:
            logger.exception("Telegram delivery queue maintenance failed")
        await asyncio.sleep(60)


async def run_loop() -> None:
    tasks = [asyncio.create_task(_intake_loop()) for _ in range(max(1, min(settings.TELEGRAM_INBOX_CONCURRENCY, 16)))]
    tasks += [asyncio.create_task(_dispatch_loop()), asyncio.create_task(_maintenance_loop())]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_arq_client()
