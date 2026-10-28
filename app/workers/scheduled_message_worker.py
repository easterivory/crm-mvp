from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from app.core.database import get_db_session, engine
from app.repositories.scheduled_message_repository import ScheduledMessageRepository
from app.services.scheduled_message_service import ScheduledMessageService

logger = logging.getLogger(__name__)


async def run_once(limit: int = 100) -> int:
    # Session lock survives delivery commits and is released if the process dies.
    # This also prevents recovery from touching another live worker's deliveries.
    key = 7261042901
    async with engine.connect() as connection:
        acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        await connection.commit()
        if not acquired:
            return 0
        try:
            async with get_db_session() as db:
                recovered = await ScheduledMessageRepository(db).recover_interrupted()
                await db.commit()
                if recovered:
                    logger.warning("Interrupted scheduled deliveries marked failed count=%s; automatic resend disabled", recovered)
                processed = await ScheduledMessageService(db).process_due_messages(limit=limit)
                await db.commit()
                return processed
        finally:
            try:
                await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                await connection.commit()
            except BaseException:
                await connection.invalidate()
                raise


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
