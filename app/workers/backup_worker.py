from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.services.backup_service import (
    BackupError,
    create_database_backup,
    ensure_required_backup_tools,
    send_telegram_message,
    telegram_delivery_configured,
)

logger = logging.getLogger(__name__)


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
