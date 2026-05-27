"""Worker for delayed funnel runtime jobs."""
import asyncio
import logging
from datetime import datetime, timezone

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
            await repo.mark_scheduled_job_running(job.id)
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
