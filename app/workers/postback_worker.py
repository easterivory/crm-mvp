"""Polling worker for sending lead postbacks to partner CRMs."""
import asyncio
import logging
from uuid import UUID

from app.core.database import get_db_session
from app.services.partner_service import PartnerService

logger = logging.getLogger(__name__)


async def run_once() -> int:
    async with get_db_session() as db:
        processed = await PartnerService(db).process_pending_submissions()
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
        service = PartnerService(db)
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


class WorkerSettings:
    """ARQ compatibility settings."""
    functions = [send_lead_postback]
    redis_settings = None  # Will be set from config
