"""Worker for delayed funnel runtime jobs."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db_session
from app.repositories.funnel_repository import FunnelRepository
from app.services.funnel_runtime_service import (
    FunnelRuntimeDeliveryError,
    FunnelRuntimeService,
)
from app.services.operational_alert_service import (
    prime_operational_alert_config,
    send_operational_alert,
)
from app.services.telegram_sender import TelegramDeliveryError

logger = logging.getLogger(__name__)


def _error_text(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    if not message and isinstance(exc, TimeoutError):
        message = (
            "scheduled job exceeded "
            f"{settings.FUNNEL_SCHEDULED_JOB_TIMEOUT_SECONDS} seconds"
        )
    return f"{exc.__class__.__name__}: {message or 'no error details'}"


async def _rollback_session(db: AsyncSession) -> None:
    timeout_seconds = max(settings.FUNNEL_SCHEDULED_DB_OPERATION_TIMEOUT_SECONDS, 1)
    try:
        async with asyncio.timeout(timeout_seconds):
            await db.rollback()
        return
    except Exception:
        logger.exception("Could not roll back failed funnel scheduled job session")

    try:
        async with asyncio.timeout(timeout_seconds):
            await db.invalidate()
    except Exception:
        logger.exception("Could not invalidate failed funnel scheduled job session")


async def _recover_stale_jobs() -> tuple[int, int]:
    timeout_seconds = max(settings.FUNNEL_SCHEDULED_DB_OPERATION_TIMEOUT_SECONDS, 1)
    async with asyncio.timeout(timeout_seconds):
        async with get_db_session() as db:
            try:
                recovered = await FunnelRepository(db).recover_stale_running_jobs(
                    stale_before=datetime.now(timezone.utc)
                    - timedelta(seconds=max(settings.FUNNEL_SCHEDULED_JOB_STALE_SECONDS, 1)),
                    max_attempts=max(settings.FUNNEL_SCHEDULED_JOB_MAX_ATTEMPTS, 1),
                )
                await db.commit()
                return recovered
            except Exception:
                await _rollback_session(db)
                raise


async def _list_due_job_ids(limit: int) -> list[UUID]:
    timeout_seconds = max(settings.FUNNEL_SCHEDULED_DB_OPERATION_TIMEOUT_SECONDS, 1)
    async with asyncio.timeout(timeout_seconds):
        async with get_db_session() as db:
            try:
                jobs = await FunnelRepository(db).list_due_scheduled_jobs(
                    now=datetime.now(timezone.utc),
                    limit=limit,
                )
                job_ids = [job.id for job in jobs]
                await db.rollback()
                return job_ids
            except Exception:
                await _rollback_session(db)
                raise


async def _claim_job(job_id: UUID) -> bool:
    timeout_seconds = max(settings.FUNNEL_SCHEDULED_DB_OPERATION_TIMEOUT_SECONDS, 1)
    async with asyncio.timeout(timeout_seconds):
        async with get_db_session() as db:
            try:
                claimed = await FunnelRepository(db).claim_scheduled_job(job_id)
                await db.commit()
                return claimed
            except Exception:
                await _rollback_session(db)
                raise


async def _job_status(job_id: UUID) -> str:
    timeout_seconds = max(settings.FUNNEL_SCHEDULED_DB_OPERATION_TIMEOUT_SECONDS, 1)
    async with asyncio.timeout(timeout_seconds):
        async with get_db_session() as db:
            try:
                job = await FunnelRepository(db).get_scheduled_job(job_id)
                # AsyncSession.rollback() expires loaded ORM attributes. Snapshot the
                # scalar while the query greenlet is still active so a normal claim
                # race cannot trigger an implicit async refresh (MissingGreenlet).
                job_status = job.status if job is not None else "not_found"
                await db.rollback()
                return job_status
            except Exception:
                await _rollback_session(db)
                raise


async def _mark_job_failed(job_id: UUID, error: str) -> bool:
    timeout_seconds = max(settings.FUNNEL_SCHEDULED_DB_OPERATION_TIMEOUT_SECONDS, 1)
    try:
        async with asyncio.timeout(timeout_seconds):
            async with get_db_session() as db:
                try:
                    repo = FunnelRepository(db)
                    job = await repo.get_scheduled_job(job_id)
                    if job is None:
                        await db.rollback()
                        return False
                    await repo.mark_scheduled_job_failed(job_id, error)
                    await db.commit()
                    return True
                except Exception:
                    await _rollback_session(db)
                    raise
    except Exception:
        logger.exception("Could not persist funnel scheduled job failure job_id=%s", job_id)
        return False


def _telegram_delivery_error(exc: Exception) -> TelegramDeliveryError | None:
    if isinstance(exc, FunnelRuntimeDeliveryError):
        return exc.telegram_error
    if isinstance(exc, TelegramDeliveryError):
        return exc
    return None


def _delivery_retry_delay_seconds(error: TelegramDeliveryError, attempts: int) -> int:
    base = max(settings.FUNNEL_SCHEDULED_DELIVERY_RETRY_BASE_SECONDS, 1)
    cap = max(settings.FUNNEL_SCHEDULED_WORKER_MAX_BACKOFF_SECONDS, base)
    exponential_delay = min(base * (2 ** max(attempts - 1, 0)), cap)
    return max(exponential_delay, error.retry_after or 0, 1)


def _delivery_alert_details(error: TelegramDeliveryError) -> dict[str, Any]:
    return {
        "telegram_method": error.method,
        "telegram_http_status": error.status_code,
        "telegram_error_code": error.error_code,
        "telegram_description": error.description,
        "telegram_retry_after_seconds": error.retry_after,
        "telegram_failure_is_transient": error.transient,
        "telegram_user_blocked_bot": error.blocked,
    }


async def _resolve_delivery_failure(
    job_id: UUID,
    exc: Exception,
    error_text: str,
) -> dict[str, Any]:
    telegram_error = _telegram_delivery_error(exc)
    if telegram_error is None:
        return {"status": "not_telegram_failure", "failure_status_persisted": False}

    timeout_seconds = max(settings.FUNNEL_SCHEDULED_DB_OPERATION_TIMEOUT_SECONDS, 1)
    try:
        async with asyncio.timeout(timeout_seconds):
            async with get_db_session() as db:
                try:
                    repo = FunnelRepository(db)
                    job = await repo.get_scheduled_job(job_id)
                    if job is None:
                        await db.rollback()
                        return {
                            "status": "not_found",
                            "failure_status_persisted": False,
                        }

                    job_status = job.status
                    attempts = int(job.attempts or 0)
                    chat_id = job.chat_id
                    funnel_version_id = job.funnel_version_id
                    original_step_id = job.step_id
                    original_job_type = job.job_type
                    original_payload = dict(job.payload_json or {})
                    if job_status != "running":
                        await db.rollback()
                        return {
                            "status": "skipped",
                            "job_status": job_status,
                            "attempts": attempts,
                            "failure_status_persisted": False,
                        }

                    if telegram_error.blocked:
                        persisted = await repo.mark_scheduled_job_cancelled(job_id, error_text)
                        await db.commit()
                        return {
                            "status": "cancelled",
                            "attempts": attempts,
                            "chat_id": str(chat_id),
                            "failure_status_persisted": persisted,
                        }

                    max_attempts = max(settings.FUNNEL_SCHEDULED_JOB_MAX_ATTEMPTS, 1)
                    if not telegram_error.transient or attempts >= max_attempts:
                        await repo.mark_scheduled_job_failed(job_id, error_text)
                        await db.commit()
                        return {
                            "status": "failed",
                            "attempts": attempts,
                            "max_attempts": max_attempts,
                            "chat_id": str(chat_id),
                            "job_type": original_job_type,
                            "step_id": str(original_step_id),
                            "failure_status_persisted": True,
                        }

                    state = await repo.get_chat_funnel_state(chat_id)
                    state_is_retryable = (
                        state is not None
                        and state.completed_at is None
                        and not state.is_paused
                        and state.funnel_version_id == funnel_version_id
                    )
                    if not state_is_retryable:
                        terminal_error = (
                            f"{error_text}; automatic retry skipped because the funnel state "
                            "is missing, paused, completed, or belongs to another version"
                        )
                        await repo.mark_scheduled_job_failed(job_id, terminal_error)
                        await db.commit()
                        return {
                            "status": "failed",
                            "attempts": attempts,
                            "max_attempts": max_attempts,
                            "chat_id": str(chat_id),
                            "job_type": original_job_type,
                            "step_id": str(original_step_id),
                            "failure_status_persisted": True,
                            "retry_blocked_by_funnel_state": True,
                        }

                    assert state is not None
                    current_step_id = state.current_step_id
                    if (
                        isinstance(exc, FunnelRuntimeDeliveryError)
                        and current_step_id == exc.retry_step_id
                    ):
                        retry_job_type = exc.retry_job_type
                        retry_step_id = exc.retry_step_id
                        retry_payload = exc.retry_payload
                    elif current_step_id == original_step_id:
                        retry_job_type = original_job_type
                        retry_step_id = original_step_id
                        retry_payload = original_payload
                    else:
                        # A delay/timeout may have committed its transition before the
                        # external send. Resume at the committed destination instead of
                        # repeating the preceding action and its side effects.
                        retry_job_type = "resume_step"
                        retry_step_id = current_step_id
                        retry_payload = {}

                    retry_in_seconds = _delivery_retry_delay_seconds(
                        telegram_error,
                        attempts,
                    )
                    persisted = await repo.requeue_scheduled_job(
                        job_id=job_id,
                        run_at=datetime.now(timezone.utc)
                        + timedelta(seconds=retry_in_seconds),
                        error=(
                            f"{error_text}; retry {attempts + 1}/{max_attempts} "
                            f"scheduled in {retry_in_seconds}s"
                        ),
                        job_type=retry_job_type,
                        step_id=retry_step_id,
                        payload_json=retry_payload,
                    )
                    await db.commit()
                    return {
                        "status": "retry_scheduled" if persisted else "persistence_failed",
                        "attempts": attempts,
                        "max_attempts": max_attempts,
                        "retry_in_seconds": retry_in_seconds,
                        "chat_id": str(chat_id),
                        "job_type": retry_job_type,
                        "step_id": str(retry_step_id),
                        "failure_status_persisted": persisted,
                    }
                except Exception:
                    await _rollback_session(db)
                    raise
    except Exception:
        logger.exception(
            "Could not resolve Telegram delivery failure for funnel scheduled job job_id=%s",
            job_id,
        )
        return {"status": "persistence_failed", "failure_status_persisted": False}


async def _execute_claimed_job(job_id: UUID) -> dict[str, Any]:
    try:
        async with get_db_session() as db:
            try:
                async with asyncio.timeout(
                    max(settings.FUNNEL_SCHEDULED_JOB_TIMEOUT_SECONDS, 1)
                ):
                    repo = FunnelRepository(db)
                    job = await repo.get_scheduled_job(job_id)
                    if job is None:
                        await db.rollback()
                        return {"status": "not_found", "job_id": str(job_id)}
                    job_status = job.status
                    if job_status != "running":
                        await db.rollback()
                        return {
                            "status": "skipped",
                            "job_id": str(job_id),
                            "job_status": job_status,
                        }

                    runtime = FunnelRuntimeService(
                        db,
                        release_transaction_before_external_io=True,
                        raise_on_telegram_delivery_error=True,
                    )
                    await runtime.process_scheduled_job(job)
                    # The runtime may commit before Telegram I/O. Use the immutable
                    # function argument instead of touching an ORM instance after
                    # that transaction boundary.
                    await repo.mark_scheduled_job_done(job_id)
                    await db.commit()
                    return {"status": "completed", "job_id": str(job_id)}
            except Exception:
                await _rollback_session(db)
                raise
    except Exception as exc:
        error = _error_text(exc)
        logger.exception("Funnel scheduled job failed job_id=%s", job_id)
        telegram_error = _telegram_delivery_error(exc)
        if telegram_error is not None:
            resolution = await _resolve_delivery_failure(job_id, exc, error)
            if resolution["status"] == "retry_scheduled":
                logger.warning(
                    "Transient Telegram delivery failure requeued job_id=%s "
                    "attempts=%s retry_in_seconds=%s job_type=%s step_id=%s error=%s",
                    job_id,
                    resolution.get("attempts"),
                    resolution.get("retry_in_seconds"),
                    resolution.get("job_type"),
                    resolution.get("step_id"),
                    telegram_error,
                )
                return {"job_id": str(job_id), **resolution}
            if resolution["status"] == "cancelled":
                logger.info(
                    "Cancelled delayed funnel job after Telegram user block "
                    "job_id=%s chat_id=%s",
                    job_id,
                    resolution.get("chat_id"),
                )
                return {"job_id": str(job_id), **resolution}
            failure_persisted = bool(resolution.get("failure_status_persisted"))
        else:
            resolution = {}
            failure_persisted = await _mark_job_failed(job_id, error)

        alert_details: dict[str, Any] = {
            "job_id": job_id,
            "error": error,
            "failure_status_persisted": failure_persisted,
            "transaction_cleanup": "rollback attempted; failure write used a fresh session",
            **{
                key: value
                for key, value in resolution.items()
                if key not in {"status", "failure_status_persisted"}
            },
        }
        if telegram_error is not None:
            alert_details.update(_delivery_alert_details(telegram_error))
        await send_operational_alert(
            component="funnel_scheduled_worker",
            title="Delayed funnel job failed",
            details=alert_details,
            dedupe_key=(
                "funnel-scheduled-job:telegram:"
                f"{telegram_error.method}:"
                f"{telegram_error.error_code or telegram_error.status_code or 'network'}"
                if telegram_error is not None
                else f"funnel-scheduled-job:{exc.__class__.__name__}"
            ),
        )
        return {
            "status": "failed",
            "job_id": str(job_id),
            "error": error[:1000],
            "failure_status_persisted": failure_persisted,
        }


async def run_once(limit: int = 100) -> int:
    requeued, exhausted = await _recover_stale_jobs()
    if requeued or exhausted:
        logger.warning(
            "Recovered stale funnel jobs requeued=%s exhausted=%s",
            requeued,
            exhausted,
        )
        await send_operational_alert(
            component="funnel_scheduled_worker",
            title="Stale delayed funnel jobs detected",
            details={"requeued": requeued, "retry_limit_reached": exhausted},
            dedupe_key="funnel-scheduled-stale-recovery",
        )

    processed = 0
    for job_id in await _list_due_job_ids(limit):
        if not await _claim_job(job_id):
            logger.info("Skipped already claimed funnel scheduled job job_id=%s", job_id)
            continue
        result = await _execute_claimed_job(job_id)
        if result["status"] == "completed":
            processed += 1
    return processed


async def process_funnel_scheduled_job_task(ctx: dict, job_id: str) -> dict:
    _ = ctx
    try:
        job_uuid = UUID(job_id)
    except (TypeError, ValueError) as exc:
        return {"status": "failed", "error": str(exc)}

    try:
        if not await _claim_job(job_uuid):
            return {
                "status": "skipped",
                "job_id": job_id,
                "job_status": await _job_status(job_uuid),
            }
        return await _execute_claimed_job(job_uuid)
    except Exception as exc:
        error = _error_text(exc)
        logger.exception("Funnel scheduled ARQ task failed before execution job_id=%s", job_id)
        await send_operational_alert(
            component="funnel_scheduled_arq",
            title="Delayed funnel task infrastructure failure",
            details={"job_id": job_id, "error": error},
            dedupe_key=f"funnel-scheduled-arq:{exc.__class__.__name__}",
        )
        return {"status": "failed", "job_id": job_id, "error": error[:1000]}


async def run_loop(interval_seconds: float = 1.0) -> None:
    logger.info("Starting funnel scheduled worker")
    await prime_operational_alert_config()
    failure_streak = 0
    while True:
        sleep_seconds = interval_seconds
        try:
            processed = await run_once()
            failure_streak = 0
            if processed:
                logger.info("Processed funnel scheduled jobs count=%s", processed)
        except Exception as exc:
            failure_streak += 1
            max_backoff = max(settings.FUNNEL_SCHEDULED_WORKER_MAX_BACKOFF_SECONDS, 1)
            sleep_seconds = min(
                max(interval_seconds, 0.1) * (2 ** min(failure_streak - 1, 8)),
                max_backoff,
            )
            logger.exception(
                "Funnel scheduled worker loop failed; retrying in %.1f seconds",
                sleep_seconds,
            )
            await send_operational_alert(
                component="funnel_scheduled_worker",
                title="Delayed funnel worker loop is unhealthy",
                details={
                    "error": _error_text(exc),
                    "failure_streak": failure_streak,
                    "retry_in_seconds": round(sleep_seconds, 1),
                },
                dedupe_key=f"funnel-scheduled-loop:{exc.__class__.__name__}",
            )
        await asyncio.sleep(sleep_seconds)
