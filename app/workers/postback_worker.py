"""Polling worker for sending lead postbacks to partner CRMs."""
import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import selectinload

from app.core.arq_queues import JOBS_QUEUE_NAME
from app.core.config import settings
from app.core.database import get_db_session
from app.core.logging_config import configure_file_logging
from app.models.lead import Lead
from app.models.channel_tracking import TelegramChannelSubscriptionEvent
from app.models.partner import PartnerIntegration
from app.models.tracking import TrackingLink
from app.services.facebook_capi_service import FacebookCAPIError, FacebookCAPIService
from app.services.channel_join_funnel_service import ChannelJoinFunnelService
from app.services.funnel_start_recovery_service import FunnelStartRecoveryService
from app.services.google_sheets_service import GoogleSheetsService
from app.services.lead_confidence_service import LeadConfidenceService
from app.services.operational_alert_service import (
    prime_operational_alert_config,
    send_operational_alert,
)
from app.services.postback_service import PostbackService
from app.services.telegram_service import TelegramService
from app.services.telegram_sender import TelegramSenderService
from app.repositories.bot_repository import BotRepository
from app.workers.broadcast_worker import process_broadcast, process_due_broadcasts
from app.workers.funnel_scheduled_worker import process_funnel_scheduled_job_task

try:
    from arq import Retry, cron
    from arq.connections import RedisSettings
except ImportError:  # pragma: no cover - production installs arq from requirements.txt
    Retry = None
    cron = None
    RedisSettings = None

logger = logging.getLogger(__name__)
configure_file_logging()


async def _on_worker_startup(ctx: dict) -> None:
    _ = ctx
    await prime_operational_alert_config()


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
            submitted_manually=False,
            submission_source="api",
        )
        await service.process_submission(submission.id)
        await db.commit()
        return {"status": submission.status, "submission_id": str(submission.id)}


async def auto_submit_lead_task(
    ctx: dict,
    lead_id: str,
    partner_integration_id: str,
    forced_manual: bool = False,
) -> dict:
    del ctx
    try:
        lead_uuid = UUID(lead_id)
        partner_uuid = UUID(partner_integration_id)
    except (TypeError, ValueError) as exc:
        return {"status": "failed", "error": str(exc)}

    async with get_db_session() as db:
        integration_result = await db.execute(
            select(PartnerIntegration).where(PartnerIntegration.id == partner_uuid)
        )
        integration = integration_result.scalar_one_or_none()
        if integration is None:
            return {"status": "skipped", "reason": "partner_not_found"}
        if not integration.is_active or not integration.is_auto_submit_enabled:
            return {"status": "skipped", "reason": "auto_submit_disabled"}

        service = PostbackService(db)
        lead = await service.repo.get_lead_in_project(
            lead_uuid,
            integration.project_id,
            for_update=True,
        )
        if lead is None:
            return {"status": "skipped", "reason": "lead_unavailable"}
        if not forced_manual:
            confidence = LeadConfidenceService(db)
            confidence_result = await confidence.calculate_confidence(lead)
            eligible, routing_reasons = await confidence.auto_submit_eligibility(
                lead=lead,
                result=confidence_result,
                rules=integration.auto_submit_rules or {},
                required_fields=integration.required_fields or [],
            )
            if not eligible:
                reason = "; ".join(routing_reasons)
                await service.repo.upsert_manual_required_decision(
                    lead_id=lead.id,
                    partner_integration_id=integration.id,
                    reason=reason,
                )
                await db.commit()
                return {
                    "status": "skipped",
                    "reason": "manual_required",
                    "routing_reasons": routing_reasons,
                }

        submissions = await service.repo.list_submissions_for_lead_partner(
            lead_id=lead.id,
            partner_integration_id=integration.id,
            project_id=integration.project_id,
            for_update=True,
        )
        blocking_statuses = {
            "pending",
            "processing",
            "success",
            "accepted",
            "submitted",
            "duplicate",
        }
        if any(str(item.status).lower() in blocking_statuses for item in submissions):
            return {"status": "skipped", "reason": "submission_already_exists"}

        await service.repo.clear_manual_required_decision(
            lead_id=lead.id,
            partner_integration_id=integration.id,
        )
        submission = await service.repo.create_submission(
            lead_id=lead.id,
            partner_integration_id=integration.id,
            status="pending",
            submitted_by_user_id=lead.manager_id,
            submission_source="vip" if forced_manual else "auto",
            submitted_manually=forced_manual,
        )
        result = await service.process_submission(submission.id)
        await db.commit()
        return result


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


async def send_fb_capi_channel_event_task(
    ctx: dict,
    tracking_link_id: str,
    telegram_user_id: str,
    event_name: str,
    first_name: str | None = None,
    last_name: str | None = None,
    custom_data: dict | None = None,
    event_time: int | None = None,
    event_id: str | None = None,
) -> dict:
    try:
        tracking_link_uuid = UUID(tracking_link_id)
        normalized_user_id = str(int(telegram_user_id))
    except (TypeError, ValueError) as exc:
        return {"status": "failed", "error": str(exc)}
    try:
        async with get_db_session() as db:
            result = await db.execute(
                select(TrackingLink).where(TrackingLink.id == tracking_link_uuid)
            )
            link = result.scalar_one_or_none()
            if link is None:
                return {"status": "failed", "error": "Tracking link not found"}
            if link.destination_type != "channel":
                return {"status": "skipped", "error": "Not a channel tracking link"}
            if not link.fb_pixel_id or not link.fb_capi_token:
                return {"status": "skipped", "error": "Facebook CAPI is not configured"}
            response = await FacebookCAPIService.send_external_event(
                pixel_id=link.fb_pixel_id,
                token=link.fb_capi_token,
                event_name=event_name,
                external_id=normalized_user_id,
                first_name=first_name,
                last_name=last_name,
                event_time=event_time,
                custom_data=custom_data or {},
                event_id=event_id,
                proxy_url=link.fb_proxy_url,
                test_event_code=link.fb_test_event_code,
            )
            return {
                "status": "completed",
                "tracking_link_id": str(tracking_link_uuid),
                "response": response,
            }
    except FacebookCAPIError as exc:
        job_try = int(ctx.get("job_try") or 1)
        if exc.retryable and job_try < 3 and Retry is not None:
            raise Retry(defer=min(30 * job_try, 90)) from exc
        return {"status": "failed", "error": str(exc)[:1000]}
    except Exception as exc:
        logger.exception(
            "Facebook channel CAPI task crashed tracking_link_id=%s event_name=%s",
            tracking_link_id,
            event_name,
        )
        return {"status": "failed", "error": str(exc)[:1000]}


async def process_channel_join_request_action_task(
    ctx: dict,
    event_id: str,
) -> dict:
    try:
        event_uuid = UUID(event_id)
    except (TypeError, ValueError) as exc:
        return {"status": "failed", "error": str(exc)}

    job_try = int(ctx.get("job_try") or 1)
    async with get_db_session() as db:
        result = await db.execute(
            select(TelegramChannelSubscriptionEvent)
            .options(selectinload(TelegramChannelSubscriptionEvent.channel))
            .where(TelegramChannelSubscriptionEvent.id == event_uuid)
        )
        event = result.scalar_one_or_none()
        if event is None or event.event_type != "join_request":
            return {"status": "skipped", "error": "Join-request event not found"}

        message_pending = bool(
            event.request_message_text and event.request_message_sent_at is None
        )
        approval_requested = bool(
            event.auto_approve_requested and event.request_approved_at is None
        )
        approval_pending = bool(
            approval_requested
            and (
                not event.auto_start_requested
                or (
                    event.funnel_start_processed_at is not None
                    and not event.funnel_start_error
                )
            )
        )
        funnel_start_pending = bool(
            event.auto_start_requested and event.funnel_start_processed_at is None
        )
        if not message_pending and not approval_pending and not funnel_start_pending:
            return {"status": "completed", "event_id": str(event.id)}

        raw_payload = event.raw_payload if isinstance(event.raw_payload, dict) else {}
        try:
            user_chat_id = int(raw_payload.get("user_chat_id"))
        except (TypeError, ValueError):
            event.request_action_error = "Telegram update has no valid user_chat_id"
            await db.commit()
            return {"status": "failed", "error": event.request_action_error}

        token = await BotRepository(db).get_bot_token_by_id(
            event.tracker_bot_id,
            event.project_id,
        )
        if not token:
            event.request_action_error = "Tracker bot token is not configured"
            await db.commit()
            return {"status": "failed", "error": event.request_action_error}

        channel_chat_id = event.channel.telegram_chat_id
        telegram_user_id = event.telegram_user_id
        message_text = event.request_message_text
        await db.commit()
        sender = TelegramSenderService(db)

        message_error: str | None = None
        funnel_error: str | None = None
        if message_pending and message_text:
            try:
                await sender.send_join_request_message(
                    token,
                    user_chat_id=user_chat_id,
                    text=message_text,
                )
                event.request_message_sent_at = datetime.now(timezone.utc)
                event.request_action_error = None
                await db.commit()
            except Exception as exc:
                message_error = str(exc)[:1000]
                event.request_action_error = message_error
                await db.commit()
                if job_try < 3 and Retry is not None:
                    raise Retry(defer=min(5 * job_try, 15)) from exc

        if funnel_start_pending:
            try:
                start_result = await ChannelJoinFunnelService(db).start_for_join_request(
                    event=event,
                    user_chat_id=user_chat_id,
                )
                event.funnel_start_processed_at = datetime.now(timezone.utc)
                event.funnel_start_chat_id = start_result.chat_id
                event.funnel_started_at = (
                    datetime.now(timezone.utc) if start_result.started else None
                )
                event.funnel_start_error = start_result.error
                funnel_error = start_result.error
                event.request_action_error = funnel_error or message_error
                await db.commit()
                if funnel_error:
                    await send_operational_alert(
                        component="channel_join_funnel",
                        title="Channel join funnel did not start",
                        details={
                            "event_id": event.id,
                            "project_id": event.project_id,
                            "tracker_bot_id": event.tracker_bot_id,
                            "error": funnel_error,
                        },
                        dedupe_key=(
                            f"channel-join-funnel:{event.tracker_bot_id}:{funnel_error}"
                        ),
                    )
            except Exception as exc:
                await db.rollback()
                event = await db.get(TelegramChannelSubscriptionEvent, event_uuid)
                if event is None:
                    return {"status": "failed", "error": "Join-request event disappeared"}
                funnel_error = str(exc)[:1000]
                event.funnel_start_error = funnel_error
                event.request_action_error = funnel_error
                if job_try >= 3 or Retry is None:
                    event.funnel_start_processed_at = datetime.now(timezone.utc)
                await db.commit()
                if job_try < 3 and Retry is not None:
                    raise Retry(defer=min(5 * job_try, 15)) from exc
                logger.exception(
                    "Channel join funnel failed after retries event_id=%s",
                    event_id,
                )
                await send_operational_alert(
                    component="channel_join_funnel",
                    title="Channel join funnel failed after retries",
                    details={
                        "event_id": event_id,
                        "project_id": event.project_id,
                        "tracker_bot_id": event.tracker_bot_id,
                        "error": funnel_error,
                    },
                    dedupe_key=(
                        f"channel-join-funnel:{event.tracker_bot_id}:{type(exc).__name__}"
                    ),
                )

        approval_pending = bool(
            approval_requested
            and (
                not event.auto_start_requested
                or (
                    event.funnel_start_processed_at is not None
                    and not event.funnel_start_error
                )
            )
        )
        if approval_pending:
            try:
                await sender.approve_chat_join_request(
                    token,
                    chat_id=channel_chat_id,
                    user_id=telegram_user_id,
                )
                event.request_approved_at = datetime.now(timezone.utc)
                event.request_action_error = funnel_error or message_error
                await db.commit()
            except Exception as exc:
                approval_error = str(exc)[:1000]
                if "USER_ALREADY_PARTICIPANT" in approval_error.upper():
                    event.request_approved_at = datetime.now(timezone.utc)
                    event.request_action_error = funnel_error or message_error
                    await db.commit()
                else:
                    event.request_action_error = approval_error
                    await db.commit()
                    if job_try < 3 and Retry is not None:
                        raise Retry(defer=min(5 * job_try, 15)) from exc
                    return {
                        "status": "failed",
                        "event_id": str(event.id),
                        "error": approval_error,
                    }

        return {
            "status": "partial" if message_error or funnel_error else "completed",
            "event_id": str(event.id),
            "message_sent": event.request_message_sent_at is not None,
            "funnel_started": event.funnel_started_at is not None,
            "approved": event.request_approved_at is not None,
            "error": funnel_error or message_error,
        }


async def recover_channel_join_request_actions_task(ctx: dict) -> dict:
    now = datetime.now(timezone.utc)
    message_cutoff = now - timedelta(minutes=5)
    async with get_db_session() as db:
        result = await db.execute(
            select(
                TelegramChannelSubscriptionEvent.id,
                TelegramChannelSubscriptionEvent.occurred_at,
            )
            .where(
                TelegramChannelSubscriptionEvent.event_type == "join_request",
                TelegramChannelSubscriptionEvent.occurred_at >= message_cutoff,
                or_(
                    and_(
                        TelegramChannelSubscriptionEvent.request_message_text.is_not(None),
                        TelegramChannelSubscriptionEvent.request_message_sent_at.is_(None),
                    ),
                    and_(
                        TelegramChannelSubscriptionEvent.auto_approve_requested.is_(True),
                        TelegramChannelSubscriptionEvent.request_approved_at.is_(None),
                        or_(
                            TelegramChannelSubscriptionEvent.auto_start_requested.is_(False),
                            and_(
                                TelegramChannelSubscriptionEvent.funnel_start_processed_at.is_not(None),
                                TelegramChannelSubscriptionEvent.funnel_start_error.is_(None),
                            ),
                        ),
                    ),
                    and_(
                        TelegramChannelSubscriptionEvent.auto_start_requested.is_(True),
                        TelegramChannelSubscriptionEvent.funnel_start_processed_at.is_(None),
                    ),
                ),
            )
            .order_by(TelegramChannelSubscriptionEvent.occurred_at.asc())
            .limit(100)
        )
        pending = list(result.all())

    completed = 0
    for event_id, occurred_at in pending:
        age = now - occurred_at
        recovery_ctx = {
            **ctx,
            "job_try": 3 if age >= timedelta(minutes=4) else 1,
        }
        try:
            result = await process_channel_join_request_action_task(
                recovery_ctx,
                str(event_id),
            )
            if result.get("status") in {"completed", "partial"}:
                completed += 1
        except Exception:
            logger.warning(
                "Deferred channel join-request recovery will retry event_id=%s",
                event_id,
                exc_info=True,
            )
    return {"status": "completed", "processed": completed, "pending": len(pending)}


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


async def recover_missed_funnel_starts_task(ctx: dict) -> dict:
    """Safety net for the commit-to-queue gap in Telegram webhook handling."""
    # Keep automatic recovery ids stable within an hour so a delayed jobs queue
    # cannot accumulate copies every minute. ARQ retries transient failures;
    # the manual recovery action can create a new scope after a code fix.
    scope = datetime.now(timezone.utc).strftime("auto-%Y%m%d%H")
    try:
        async with get_db_session() as db:
            result = await FunnelStartRecoveryService(db).recover(
                lookback_hours=24,
                limit=500,
                job_scope=scope,
            )
            await db.commit()
        return {"status": "completed", **asdict(result), "scheduled": result.scheduled}
    except Exception as exc:
        logger.exception("Automatic funnel start recovery failed")
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
        auto_submit_lead_task,
        export_lead_to_sheets_task,
        send_fb_capi_event_task,
        send_fb_capi_channel_event_task,
        process_channel_join_request_action_task,
        recover_channel_join_request_actions_task,
        process_user_input_task,
        process_funnel_start_task,
        recover_missed_funnel_starts_task,
        process_broadcast,
        process_due_broadcasts,
        process_funnel_scheduled_job_task,
    ]
    redis_settings = _redis_settings_from_url()
    queue_name = JOBS_QUEUE_NAME
    on_startup = _on_worker_startup
    cron_jobs = (
        [
            cron(recover_missed_funnel_starts_task, second=20, run_at_startup=True),
            cron(
                recover_channel_join_request_actions_task,
                second=40,
                run_at_startup=True,
            ),
        ]
        if cron is not None
        else []
    )
