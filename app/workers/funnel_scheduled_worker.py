"""Worker for delayed funnel runtime jobs."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db_session
from app.repositories.funnel_repository import FunnelRepository
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.operational_alert_service import (
    prime_operational_alert_config,
    send_operational_alert,
)

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


async def _execute_claimed_job(job_id: UUID) -> dict[str, str | bool]:
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
        failure_persisted = await _mark_job_failed(job_id, error)
        await send_operational_alert(
            component="funnel_scheduled_worker",
            title="Delayed funnel job failed",
            details={
                "job_id": job_id,
                "error": error,
                "failure_status_persisted": failure_persisted,
                "transaction_cleanup": "rollback attempted; failure write used a fresh session",
            },
            dedupe_key=f"funnel-scheduled-job:{exc.__class__.__name__}",
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
