from __future__ import annotations

import asyncio
import logging

from app.core.database import get_db_session
from app.services.scheduled_message_service import ScheduledMessageService

logger = logging.getLogger(__name__)


async def run_once(limit: int = 100) -> int:
    async with get_db_session() as db:
        processed = await ScheduledMessageService(db).process_due_messages(limit=limit)
        await db.commit()
        return processed


async def run_loop(interval_seconds: float = 1.0) -> None:
    logger.info("Starting scheduled message worker")
    while True:
        try:
            processed = await run_once()
            if processed:
                logger.info("Processed scheduled messages count=%s", processed)
        except Exception:
            logger.exception("Scheduled message worker loop failed")
        await asyncio.sleep(interval_seconds)
