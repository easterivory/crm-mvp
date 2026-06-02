"""Polling worker for sending lead postbacks to partner CRMs."""
import asyncio
import logging
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from app.core.config import settings
from app.core.database import get_db_session
from app.services.postback_service import PostbackService

try:
    from arq.connections import RedisSettings
except ImportError:  # pragma: no cover - production installs arq from requirements.txt
    RedisSettings = None

logger = logging.getLogger(__name__)


async def run_once() -> int:
    async with get_db_session() as db:
        processed = await PostbackService(db).process_pending_submissions()
        await db.commit()
        return processed


async def run_loop(interval_seconds: float = 2.0) -> None:
    logger.info("Starting postback worker")
    while True:
        try:
            processed = await run_once()
            if processed:
                logger.info("Processed partner postback submissions count=%s", processed)
        except Exception:
            logger.exception("Postback worker loop failed")
        await asyncio.sleep(interval_seconds)


async def send_lead_postback(
    ctx: dict,
    lead_id: str,
    partner_integration_id: str,
) -> dict:
    """Compatibility entrypoint for ARQ-style callers."""
    try:
        lead_uuid = UUID(lead_id)
        partner_uuid = UUID(partner_integration_id)
    except (TypeError, ValueError) as exc:
        return {"status": "failed", "error": str(exc)}

    async with get_db_session() as db:
        service = PostbackService(db)
        integration = await service.repo.get_by_id(partner_uuid)
        if integration is None:
            return {"status": "failed", "error": "Partner integration not found"}
        submission = await service.repo.create_submission(
            lead_id=lead_uuid,
            partner_integration_id=partner_uuid,
            status="pending",
        )
        await service.process_submission(submission.id)
        await db.commit()
        return {"status": submission.status, "submission_id": str(submission.id)}


def _redis_settings_from_url() -> Any:
    if RedisSettings is None:
        return None
    parsed = urlparse(settings.REDIS_URL)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int((parsed.path or "/0").lstrip("/") or "0"),
        password=parsed.password,
        ssl=parsed.scheme == "rediss",
    )


class WorkerSettings:
    """ARQ compatibility settings."""
    functions = [send_lead_postback]
    redis_settings = _redis_settings_from_url()
