"""Worker for delayed funnel runtime jobs."""
import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from app.core.database import get_db_session
from app.repositories.funnel_repository import FunnelRepository
from app.services.funnel_runtime_service import FunnelRuntimeService

logger = logging.getLogger(__name__)


async def run_once(limit: int = 100) -> int:
    processed = 0
    async with get_db_session() as db:
        repo = FunnelRepository(db)
        jobs = await repo.list_due_scheduled_jobs(
            now=datetime.now(timezone.utc),
            limit=limit,
        )
        for job in jobs:
            if not await repo.claim_scheduled_job(job.id):
                logger.info("Skipped already claimed funnel scheduled job job_id=%s", job.id)
                continue
            runtime = FunnelRuntimeService(db)
            try:
                await runtime.process_scheduled_job(job)
            except Exception as exc:
                logger.exception("Funnel scheduled job failed job_id=%s", job.id)
                await repo.mark_scheduled_job_failed(job.id, str(exc))
            else:
                await repo.mark_scheduled_job_done(job.id)
                processed += 1
        await db.commit()
    return processed


async def process_funnel_scheduled_job_task(ctx: dict, job_id: str) -> dict:
    try:
        job_uuid = UUID(job_id)
    except (TypeError, ValueError) as exc:
        return {"status": "failed", "error": str(exc)}

    async with get_db_session() as db:
        repo = FunnelRepository(db)
        job = await repo.get_scheduled_job(job_uuid)
        if job is None:
            return {"status": "not_found", "job_id": job_id}
        if job.status != "pending":
            return {"status": "skipped", "job_id": job_id, "job_status": job.status}

        if not await repo.claim_scheduled_job(job.id):
            refreshed = await repo.get_scheduled_job(job.id)
            return {
                "status": "skipped",
                "job_id": job_id,
                "job_status": refreshed.status if refreshed is not None else "not_found",
            }
        runtime = FunnelRuntimeService(db)
        try:
            await runtime.process_scheduled_job(job)
        except Exception as exc:
            logger.exception("Funnel scheduled ARQ job failed job_id=%s", job.id)
            await repo.mark_scheduled_job_failed(job.id, str(exc))
            await db.commit()
            return {"status": "failed", "job_id": job_id, "error": str(exc)[:1000]}

        await repo.mark_scheduled_job_done(job.id)
        await db.commit()
        return {"status": "completed", "job_id": job_id}


async def run_loop(interval_seconds: float = 1.0) -> None:
    logger.info("Starting funnel scheduled worker")
    while True:
        try:
            processed = await run_once()
            if processed:
                logger.info("Processed funnel scheduled jobs count=%s", processed)
        except Exception:
            logger.exception("Funnel scheduled worker loop failed")
        await asyncio.sleep(interval_seconds)
