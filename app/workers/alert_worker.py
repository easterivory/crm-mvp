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
from app.models.traffic_quality import TrafficQualitySettings
from app.workers.traffic_quality_worker import run_quality_cycle

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 300  # 5 minutes


async def run_once() -> None:
    """An error in one project must not poison another project's transaction."""
    async with async_session_factory() as db:
        ids = list((await db.scalars(select(Project.id).where(Project.is_deleted.is_(False)))).all())
    for project_id in ids:
        try:
            async with async_session_factory() as db:
                project = await db.get(Project, project_id)
                if not project or project.is_deleted:
                    continue
                await AlertService(db).check_and_create(project_id)
                quality = await db.get(TrafficQualitySettings, project_id)
                if not quality or not quality.config.get("enabled", False):
                    await LowConversionAdminAlertService(db).check_project(project)
                await db.commit()
        except Exception:
            logger.exception("alert_worker: error on project %s", project_id)
    await run_quality_cycle()


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
