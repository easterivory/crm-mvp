"""Durable slot claims; ambiguous sends are never automatically replayed."""
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select, text

from app.core.database import engine, get_db_session
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
        chat = await db.scalar(select(Chat).where(Chat.id == row.chat_id).with_for_update())
        await db.refresh(row)
        service = AdvertisingService(db)
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
            await service.finish_delivery(row, delivery, "uncertain", "Worker interrupted; automatic resend suppressed")
            await db.commit()
            logger.error("Advertising delivery uncertain enrollment_id=%s delivery_id=%s", row.id, delivery.id)
            return
        slot = await db.get(AdvertisingSlot, delivery.slot_id)
        if not slot.enabled:
            await service.finish_delivery(row, delivery, "skipped", "Slot disabled")
            await db.commit()
            return
        delivery.content_snapshot, delivery.revision = slot.content_json, slot.revision
        delivery.status = "sending"
        await db.commit()
        # Claim survives crashes. Recheck the chat after reacquiring the normal runtime lock.
        await db.execute(text("SET LOCAL lock_timeout = '2s'"))
        chat = await db.scalar(select(Chat).where(Chat.id == row.chat_id).with_for_update().execution_options(populate_existing=True))
        await db.refresh(row)
        await db.refresh(delivery)
        cfg = await service.config(row.project_id)
        reason = await service.protected_reason(chat, cfg)
        if delivery.status != "sending":
            return
        if row.status != "active" or not cfg.enabled or chat.bot_id not in cfg.bot_ids or reason:
            delivery.status, delivery.error = "cancelled", reason or "Scenario changed before send"
            if row.status == "active":
                await service.stop(row, delivery.error)
            await db.commit()
            return
        slot = await db.get(AdvertisingSlot, delivery.slot_id, populate_existing=True)
        if not slot.enabled:
            await service.finish_delivery(row, delivery, "skipped", "Slot disabled before send")
            await db.commit()
            return
        lead = await db.scalar(select(Lead).where(Lead.chat_id == chat.id, Lead.is_deleted.is_(False)))
        delivery_id = delivery.id
        try:
            if sender:
                await sender(db, chat, delivery)
            else:
                from app.services.broadcast_service import BroadcastService
                broadcast = Broadcast(id=slot.id, project_id=row.project_id, bot_id=chat.bot_id,
                    content_json=delivery.content_snapshot, trigger_funnel_id=None)
                await BroadcastService(db)._send_to_recipient(broadcast, chat.id, chat, lead)
            await service.finish_delivery(row, delivery, "sent")
            await db.commit()
            logger.info("Advertising slot sent enrollment_id=%s delivery_id=%s revision=%s", row.id, delivery.id, delivery.revision)
        except Exception as exc:
            # The Telegram result may be lost even when its send succeeded.
            await db.rollback()
            if isinstance(exc, TelegramDeliveryError) and exc.error_code in {400, 401, 403, 404, 429}:
                await db.execute(text("SET LOCAL lock_timeout = '2s'"))
                chat = await db.scalar(select(Chat).join(AdvertisingEnrollment,
                    AdvertisingEnrollment.chat_id == Chat.id).where(AdvertisingEnrollment.id == enrollment_id)
                    .with_for_update(of=Chat).execution_options(populate_existing=True))
                row = await db.get(AdvertisingEnrollment, enrollment_id, populate_existing=True)
                delivery = await db.get(AdvertisingDelivery, delivery_id, populate_existing=True)
                if delivery and delivery.status == "sending" and row.status == "active":
                    if exc.error_code == 429:
                        delivery.status, delivery.error = "pending", str(exc)
                        row.due_at = now() + timedelta(seconds=max(1, exc.retry_after or 60))
                        service.audit(row.project_id, "slot_rate_limited", enrollment_id=str(row.id),
                            delivery_id=str(delivery.id), retry_at=row.due_at.isoformat())
                    else:
                        await service.finish_delivery(row, delivery, "failed", str(exc))
                        if exc.error_code in {401, 403, 404}:
                            await service.stop(row, "telegram_unavailable")
                    await db.commit()
                logger.warning("Advertising delivery rejected enrollment_id=%s delivery_id=%s code=%s",
                    enrollment_id, delivery_id, exc.error_code)
                return
            logger.exception("Advertising send interrupted enrollment_id=%s", enrollment_id)
            # Leave the committed sending claim for conservative recovery on next cycle.


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
                    AdvertisingConfig, AdvertisingConfig.project_id == AdvertisingEnrollment.project_id,
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
