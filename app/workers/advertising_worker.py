"""Durable slot claims; ambiguous sends are never automatically replayed."""
import asyncio
import logging
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, text

from app.core.database import engine, get_db_session
from app.core.config import settings
from app.models.advertising import AdvertisingEnrollment, AdvertisingDelivery, AdvertisingSlot
from app.models.broadcast import Broadcast
from app.models.chat import Chat
from app.models.lead import Lead
from app.services.advertising_service import AdvertisingService, now
from app.services.telegram_sender import TelegramDeliveryError

logger = logging.getLogger(__name__)
LOCK_KEY = 7261030001


async def process_enrollment(enrollment_id, session_factory=get_db_session, sender=None):
    async with session_factory() as db:
        await db.execute(text("SET LOCAL lock_timeout = '2s'"))
        row = await db.get(AdvertisingEnrollment, enrollment_id)
        if row is None:
            return
        chat = await db.scalar(select(Chat).where(Chat.id == row.chat_id).with_for_update(key_share=True))
        await db.refresh(row)
        service = AdvertisingService(db, row.scenario_id)
        cfg = await service.config(row.project_id)
        if not cfg.enabled:
            return
        if row.status not in {"waiting", "active"} or row.due_at is None or row.due_at > now():
            return
        if chat.bot_id not in cfg.bot_ids:
            await service.stop(row, "bot_removed_from_scenario")
            await db.commit()
            return
        if row.status == "waiting":
            await service.activate(row, chat, cfg)
            await db.commit()
            return
        reason = await service.protected_reason(chat, cfg)
        if reason:
            await service.stop(row, reason, "protected")
            await db.commit()
            return
        delivery = await db.scalar(select(AdvertisingDelivery).where(
            AdvertisingDelivery.enrollment_id == row.id,
            AdvertisingDelivery.status.in_(["pending", "sending"]),
        ).order_by(AdvertisingDelivery.position).limit(1))
        if delivery is None:
            row.status, row.due_at = "completed", None
            await db.commit()
            return
        if delivery.status == "sending":
            progress = dict(delivery.progress_json or {})
            claimed_at = datetime.fromisoformat(progress["claimed_at"]) if progress.get("claimed_at") else None
            if claimed_at and (now() - claimed_at).total_seconds() < max(settings.ADVERTISING_DELIVERY_STALE_SECONDS, 60):
                return
            if not progress or progress.get("in_flight"):
                await service.finish_delivery(row, delivery, "uncertain", "Worker interrupted; automatic resend suppressed")
                await db.commit()
                logger.error("Advertising delivery uncertain enrollment_id=%s delivery_id=%s", row.id, delivery.id)
                return
        slot = await db.get(AdvertisingSlot, delivery.slot_id)
        if not slot.enabled:
            await service.finish_delivery(row, delivery, "skipped", "Slot disabled")
            await db.commit()
            return
        from app.services.broadcast_service import BroadcastService
        progress = dict(delivery.progress_json or {})
        index = int(progress.get("next_index", 0))
        if index == 0:
            if delivery.revision != slot.revision:
                progress.pop("delay_applied", None)
            delivery.content_snapshot, delivery.revision = slot.content_json, slot.revision
        messages = BroadcastService._content_messages(delivery.content_snapshot)
        if index >= len(messages):
            await service.finish_delivery(row, delivery, "sent")
            await db.commit()
            return
        delay = BroadcastService._message_delay_seconds(messages[index])
        if delay > 0 and progress.get("delay_applied") != index:
            progress["delay_applied"] = index
            delivery.progress_json = dict(progress)
            delivery.status = "pending"
            row.due_at = now() + timedelta(seconds=delay)
            await db.commit()
            return
        owner = str(uuid4())
        progress.update(owner=owner, claimed_at=now().isoformat(), next_index=index, in_flight=False)
        delivery.progress_json = dict(progress)
        delivery.status = "sending"
        lead = await db.scalar(select(Lead).where(Lead.chat_id == chat.id, Lead.is_deleted.is_(False)))
        delivery_id = delivery.id
        chat_id = chat.id
        # The claim and final protection check are durable before any network I/O.
        # From here onward neither the chat row nor a DB transaction is held.
        await db.commit()
        await db.execute(text("SET LOCAL lock_timeout = '2s'"))
        await db.refresh(chat, with_for_update={"key_share": True})
        await db.refresh(row)
        await db.refresh(delivery)
        if delivery.status != "sending" or (delivery.progress_json or {}).get("owner") != owner:
            return
        cfg = await service.config(row.project_id)
        reason = await service.protected_reason(chat, cfg)
        if row.status != "active" or not cfg.enabled or chat.bot_id not in cfg.bot_ids or reason:
            delivery.status, delivery.error = "cancelled", reason or "Scenario changed before send"
            if row.status == "active":
                await service.stop(row, delivery.error)
            await db.commit()
            return
        await db.refresh(slot)
        if not slot.enabled:
            await service.finish_delivery(row, delivery, "skipped", "Slot disabled before send")
            await db.commit()
            return
        if index == 0 and slot.revision != delivery.revision:
            delivery.content_snapshot, delivery.revision = slot.content_json, slot.revision
            messages = BroadcastService._content_messages(delivery.content_snapshot)
        progress["in_flight"] = True
        delivery.progress_json = dict(progress)
        await db.commit()
        try:
            if sender:
                await sender(db, chat, delivery)
            else:
                broadcast = Broadcast(id=slot.id, project_id=row.project_id, bot_id=chat.bot_id,
                    content_json={"messages": [messages[index]]}, trigger_funnel_id=None)
                broadcast_service = BroadcastService(db)
                broadcast_service.telegram_sender.release_transaction_before_network = True
                await broadcast_service._send_to_recipient(broadcast, chat.id, chat, lead,
                    message_index_offset=index, skip_delay=True, run_after_send=False)
            # Message history and progress commit together; a lost commit stays uncertain.
            progress.update(next_index=index + 1, in_flight=False, owner=None)
            delivery.progress_json = dict(progress)
            delivery.status = "sending" if index + 1 == len(messages) else "pending"
            await db.commit()
        except Exception as exc:
            await db.rollback()
            async with session_factory() as failure_db:
                await failure_db.execute(text("SET LOCAL lock_timeout = '2s'"))
                await failure_db.execute(select(Chat.id).where(Chat.id == chat_id).with_for_update(key_share=True))
                failed_row = await failure_db.get(AdvertisingEnrollment, enrollment_id)
                failed = await failure_db.get(AdvertisingDelivery, delivery_id)
                if not failed or (failed.progress_json or {}).get("owner") != owner:
                    return
                failure_service = AdvertisingService(failure_db, failed_row.scenario_id)
                definite = isinstance(exc, TelegramDeliveryError) and (exc.definitely_not_sent or exc.error_code in {400, 401, 403, 404, 429})
                retry = isinstance(exc, TelegramDeliveryError) and (exc.definitely_not_sent or exc.error_code == 429)
                progress = dict(failed.progress_json or {})
                failures = int(progress.get("failures", 0)) + 1
                progress.update(failures=failures, in_flight=not definite, owner=None)
                failed.progress_json = dict(progress)
                reason = str(exc) if isinstance(exc, TelegramDeliveryError) else type(exc).__name__
                if retry and failures < max(1, settings.ADVERTISING_DELIVERY_MAX_ATTEMPTS) and failed_row.status == "active":
                    failed.status, failed.error = "pending", reason
                    failed_row.due_at = now() + timedelta(seconds=max(5 * 2 ** (failures - 1), exc.retry_after or 0))
                else:
                    outcome = "failed" if definite else "uncertain"
                    if failed_row.status == "active":
                        await failure_service.finish_delivery(failed_row, failed, outcome, reason)
                        if isinstance(exc, TelegramDeliveryError) and exc.error_code in {401, 403, 404}:
                            await failure_service.stop(failed_row, "telegram_unavailable")
                    else:
                        failed.status, failed.error = outcome, reason
                await failure_db.commit()
                logger.warning("Advertising message failed enrollment_id=%s delivery_id=%s index=%s status=%s failures=%s",
                    enrollment_id, delivery_id, index, failed.status, failures)
            return
        # Reacquire only after committing message history (FK locks cannot deadlock here).
        await db.execute(text("SET LOCAL lock_timeout = '2s'"))
        await db.execute(select(Chat.id).where(Chat.id == chat_id).with_for_update(key_share=True))
        await db.refresh(row)
        await db.refresh(delivery)
        if index + 1 == len(messages):
            if delivery.status != "sending":
                return
            if row.status == "active":
                await service.finish_delivery(row, delivery, "sent")
            else:
                delivery.status, delivery.sent_at = "sent", now()
            logger.info("Advertising slot sent enrollment_id=%s delivery_id=%s revision=%s", row.id, delivery.id, delivery.revision)
        elif row.status != "active" and delivery.status == "pending":
            delivery.status, delivery.error = "cancelled", "Scenario stopped after previous message"
        await db.commit()


async def run_once(limit=30):
    async with engine.connect() as connection:
        if not await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}):
            await connection.rollback()
            return
        await connection.commit()
        try:
            from app.services.advertising_backfill import process_backfill
            try:
                async with get_db_session() as db:
                    await db.execute(text("SET LOCAL lock_timeout = '2s'"))
                    await process_backfill(db)
                    await db.commit()
            except Exception:
                logger.exception("Advertising backfill batch rolled back; slot processing continues")
            async with get_db_session() as db:
                from app.models.advertising import AdvertisingConfig
                ids = list((await db.scalars(select(AdvertisingEnrollment.id).join(
                    AdvertisingConfig, AdvertisingConfig.id == AdvertisingEnrollment.scenario_id,
                ).where(AdvertisingConfig.enabled.is_(True), AdvertisingEnrollment.status.in_(["waiting", "active"]),
                    AdvertisingEnrollment.due_at <= now()).order_by(AdvertisingEnrollment.due_at).limit(limit))).all())
            for enrollment_id in ids:
                try:
                    await process_enrollment(enrollment_id)
                except Exception:
                    logger.exception("Advertising enrollment failed enrollment_id=%s", enrollment_id)
                await asyncio.sleep(0.1)
        finally:
            try:
                await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
                await connection.commit()
            except BaseException:
                await connection.invalidate()
                raise


async def run_loop():
    while True:
        try:
            await run_once()
        except Exception:
            logger.exception("Advertising worker cycle failed")
        await asyncio.sleep(2)
