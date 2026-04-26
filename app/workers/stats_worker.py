"""
StatsWorker — runs as an asyncio loop, independent of the FastAPI process.

Aggregates daily statistics per project and upserts into daily_stats table.
Runs every INTERVAL_SECONDS. Uses its own DB session per cycle.
"""
import asyncio
import logging

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.project import Project
from app.services.stats_service import StatsService

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600  # 1 hour


async def run_once() -> None:
    """Aggregate daily stats for all active projects in a single cycle."""
    async with async_session_factory() as db:
        try:
            result = await db.execute(
                select(Project).where(Project.is_deleted.is_(False))
            )
            projects = list(result.scalars().all())

            stats_service = StatsService(db)
            for project in projects:
                try:
                    await stats_service.aggregate_today(project.id)
                except Exception:
                    logger.exception("stats_worker: error on project %s", project.id)

            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("stats_worker: cycle failed")


async def run_loop() -> None:
    logger.info("stats_worker started (interval=%ds)", INTERVAL_SECONDS)
    while True:
        try:
            await run_once()
        except Exception:
            # Catch anything run_once() didn't catch itself (e.g. pool exhausted,
            # session factory failure). Short sleep before retry to avoid log spam.
            logger.exception("stats_worker: unexpected error in run_once()")
            await asyncio.sleep(5)
        await asyncio.sleep(INTERVAL_SECONDS)
