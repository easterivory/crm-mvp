"""Polling worker for sending lead postbacks to partner CRMs."""
import asyncio
import logging
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.arq_queues import JOBS_QUEUE_NAME
from app.core.config import settings
from app.core.database import get_db_session
from app.core.logging_config import configure_file_logging
from app.models.lead import Lead
from app.models.tracking import TrackingLink
from app.services.facebook_capi_service import FacebookCAPIError, FacebookCAPIService
from app.services.google_sheets_service import GoogleSheetsService
from app.services.postback_service import PostbackService
from app.services.telegram_service import TelegramService
from app.workers.broadcast_worker import process_broadcast, process_due_broadcasts
from app.workers.funnel_scheduled_worker import process_funnel_scheduled_job_task

try:
    from arq import Retry
    from arq.connections import RedisSettings
except ImportError:  # pragma: no cover - production installs arq from requirements.txt
    Retry = None
    RedisSettings = None

logger = logging.getLogger(__name__)
configure_file_logging()


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


async def export_lead_to_sheets_task(
    ctx: dict,
    lead_id: str,
    project_id: str,
) -> dict:
    try:
        lead_uuid = UUID(lead_id)
        project_uuid = UUID(project_id)
    except (TypeError, ValueError) as exc:
        return {"status": "failed", "error": str(exc)}

    try:
        async with get_db_session() as db:
            await GoogleSheetsService(db).export_lead_to_sheet(
                lead_id=lead_uuid,
                project_id=project_uuid,
            )
            await db.commit()
        return {"status": "completed", "lead_id": str(lead_uuid)}
    except Exception as exc:
        logger.exception(
            "Google Sheets export task failed lead_id=%s project_id=%s",
            lead_id,
            project_id,
        )
        return {"status": "failed", "error": str(exc)[:1000]}


async def send_fb_capi_event_task(
    ctx: dict,
    lead_id: str,
    tracking_link_id: str,
    event_name: str,
    custom_data: dict | None = None,
    event_time: int | None = None,
    event_id: str | None = None,
    event_source_url: str | None = None,
) -> dict:
    try:
        lead_uuid = UUID(lead_id)
        tracking_link_uuid = UUID(tracking_link_id)
    except (TypeError, ValueError) as exc:
        return {"status": "failed", "error": str(exc)}

    try:
        async with get_db_session() as db:
            lead_result = await db.execute(
                select(Lead)
                .options(selectinload(Lead.chat))
                .where(Lead.id == lead_uuid, Lead.is_deleted.is_(False))
            )
            lead = lead_result.scalar_one_or_none()
            if lead is None:
                return {"status": "failed", "error": "Lead not found"}
            if lead.chat is None or lead.chat.tracking_link_id != tracking_link_uuid:
                return {
                    "status": "failed",
                    "error": "Lead is not attached to the requested tracking link",
                }

            link_result = await db.execute(
                select(TrackingLink).where(TrackingLink.id == tracking_link_uuid)
            )
            link = link_result.scalar_one_or_none()
            if link is None:
                return {"status": "failed", "error": "Tracking link not found"}
            if not link.fb_pixel_id or not link.fb_capi_token:
                return {"status": "skipped", "error": "Facebook CAPI is not configured"}

            response = await FacebookCAPIService.send_event(
                pixel_id=link.fb_pixel_id,
                token=link.fb_capi_token,
                event_name=event_name,
                lead=lead,
                event_time=event_time,
                custom_data=custom_data or {},
                event_id=event_id,
                event_source_url=event_source_url,
                proxy_url=link.fb_proxy_url,
                test_event_code=link.fb_test_event_code,
            )
            return {
                "status": "completed",
                "lead_id": str(lead_uuid),
                "tracking_link_id": str(tracking_link_uuid),
                "response": response,
            }
    except FacebookCAPIError as exc:
        logger.warning(
            "Facebook CAPI task failed lead_id=%s tracking_link_id=%s event_name=%s error=%s",
            lead_id,
            tracking_link_id,
            event_name,
            exc,
        )
        job_try = int(ctx.get("job_try") or 1)
        if exc.retryable and job_try < 3 and Retry is not None:
            raise Retry(defer=min(30 * job_try, 90)) from exc
        return {"status": "failed", "error": str(exc)[:1000]}
    except Exception as exc:
        logger.exception(
            "Facebook CAPI task crashed lead_id=%s tracking_link_id=%s event_name=%s",
            lead_id,
            tracking_link_id,
            event_name,
        )
        return {"status": "failed", "error": str(exc)[:1000]}


async def process_user_input_task(
    ctx: dict,
    chat_id: str,
    trigger_message_id: str,
) -> dict:
    try:
        chat_uuid = UUID(chat_id)
        message_uuid = UUID(trigger_message_id)
    except (TypeError, ValueError) as exc:
        return {"status": "failed", "error": str(exc)}

    try:
        async with get_db_session() as db:
            result = await TelegramService(db).process_debounced_user_input(
                chat_id=chat_uuid,
                trigger_message_id=message_uuid,
            )
            await db.commit()
        return {"status": result, "chat_id": chat_id, "message_id": trigger_message_id}
    except Exception as exc:
        logger.exception(
            "Debounced Telegram input task failed chat_id=%s message_id=%s",
            chat_id,
            trigger_message_id,
        )
        raise RuntimeError(str(exc)) from exc


async def process_funnel_start_task(
    ctx: dict,
    chat_id: str,
    trigger_message_id: str,
    fresh_lifecycle: bool = False,
) -> dict:
    try:
        chat_uuid = UUID(chat_id)
        message_uuid = UUID(trigger_message_id)
    except (TypeError, ValueError) as exc:
        return {"status": "failed", "error": str(exc)}

    try:
        async with get_db_session() as db:
            result = await TelegramService(db).process_queued_funnel_start(
                chat_id=chat_uuid,
                trigger_message_id=message_uuid,
                fresh_lifecycle=bool(fresh_lifecycle),
            )
            await db.commit()
        return {"status": result, "chat_id": chat_id, "message_id": trigger_message_id}
    except Exception as exc:
        logger.exception(
            "Queued funnel start failed chat_id=%s message_id=%s",
            chat_id,
            trigger_message_id,
        )
        raise RuntimeError(str(exc)) from exc


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
    functions = [
        send_lead_postback,
        export_lead_to_sheets_task,
        send_fb_capi_event_task,
        process_user_input_task,
        process_funnel_start_task,
        process_broadcast,
        process_due_broadcasts,
        process_funnel_scheduled_job_task,
    ]
    redis_settings = _redis_settings_from_url()
    queue_name = JOBS_QUEUE_NAME
