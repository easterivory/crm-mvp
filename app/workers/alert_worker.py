"""
AlertWorker — runs as an asyncio loop, independent of the FastAPI process.

Checks SLA conditions and low-conversion transitions for every active project.
Runs every INTERVAL_SECONDS. Uses its own DB session per cycle.
"""
import asyncio
import logging

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.project import Project
from app.services.alert_service import AlertService
from app.services.admin_bot_service import LowConversionAdminAlertService

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 300  # 5 minutes


async def run_once() -> None:
    """Process all projects in a single cycle."""
    async with async_session_factory() as db:
        try:
            result = await db.execute(
                select(Project).where(Project.is_deleted.is_(False))
            )
            projects = list(result.scalars().all())

            alert_service = AlertService(db)
            conversion_alert_service = LowConversionAdminAlertService(db)
            for project in projects:
                try:
                    await alert_service.check_and_create(project.id)
                    await conversion_alert_service.check_project(project)
                except Exception:
                    logger.exception("alert_worker: error on project %s", project.id)

            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("alert_worker: cycle failed")


async def run_loop() -> None:
    logger.info("alert_worker started (interval=%ds)", INTERVAL_SECONDS)
    while True:
        try:
            await run_once()
        except Exception:
            # Catch anything run_once() didn't catch itself (e.g. pool exhausted,
            # session factory failure). Short sleep before retry to avoid log spam.
            logger.exception("alert_worker: unexpected error in run_once()")
            await asyncio.sleep(5)
        await asyncio.sleep(INTERVAL_SECONDS)
