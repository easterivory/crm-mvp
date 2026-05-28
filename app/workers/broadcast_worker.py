"""Worker for broadcast recipient delivery."""
import asyncio
import logging

from app.core.database import get_db_session
from app.services.broadcast_service import BroadcastService

logger = logging.getLogger(__name__)


async def run_once() -> int:
    async with get_db_session() as db:
        service = BroadcastService(db)
        processed = await service.process_due_broadcasts()
        await db.commit()
        return processed


async def run_loop(interval_seconds: float = 1.0) -> None:
    logger.info("Starting broadcast worker")
    while True:
        try:
            processed = await run_once()
            if processed:
                logger.info("Processed broadcast recipients count=%s", processed)
        except Exception:
            logger.exception("Broadcast worker loop failed")
        await asyncio.sleep(interval_seconds)
