from __future__ import annotations

import asyncio
import logging

from arq import cron

from app.core.config import settings
from app.core.logging_config import configure_file_logging
from app.services.backup_service import (
    BackupError,
    create_database_backup,
    ensure_required_backup_tools,
    send_telegram_message,
    telegram_delivery_configured,
)
from app.services.backup_queue import backup_redis_settings
from app.utils.backup_manager import run_configured_telegram_backup

logger = logging.getLogger(__name__)
configure_file_logging()


async def run_tg_backup_job(ctx: dict, force: bool = False) -> dict:
    """ARQ task used by both the daily cron and the Root manual trigger."""
    try:
        return await run_configured_telegram_backup(force=force)
    except Exception as exc:
        logger.exception("Telegram database backup failed")
        raise BackupError(str(exc)) from exc


class WorkerSettings:
    functions = [run_tg_backup_job]
    cron_jobs = [cron(run_tg_backup_job, hour=3, minute=0, run_at_startup=False)]
    redis_settings = backup_redis_settings()


async def _safe_run_backup_once() -> None:
    try:
        result = await asyncio.to_thread(create_database_backup)
        logger.info("Scheduled database backup completed: %s", result.path)
    except Exception as exc:
        logger.exception("Scheduled database backup failed")
        if telegram_delivery_configured():
            try:
                await asyncio.to_thread(
                    send_telegram_message,
                    f"Database backup failed: {exc}",
                )
            except BackupError:
                logger.exception("Failed to send database backup failure notification")


async def run_loop() -> None:
    if not settings.BACKUP_ENABLED:
        logger.info("Database backup worker is disabled. Set BACKUP_ENABLED=true to enable it.")
        await asyncio.Event().wait()

    ensure_required_backup_tools()
    interval_seconds = max(settings.BACKUP_INTERVAL_HOURS, 1) * 60 * 60
    logger.info(
        "Starting database backup worker: interval_hours=%s storage=%s telegram=%s",
        settings.BACKUP_INTERVAL_HOURS,
        settings.BACKUP_STORAGE_PATH,
        telegram_delivery_configured(),
    )

    if settings.BACKUP_RUN_ON_STARTUP:
        await _safe_run_backup_once()

    while True:
        await asyncio.sleep(interval_seconds)
        await _safe_run_backup_once()
