"""Evaluation and durable delivery; no open DB transaction during Telegram IO."""
from datetime import datetime, timedelta, timezone
import logging
import asyncio

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import async_session_factory
from app.core.constants import RoleName
from app.models.project import Project
from app.models.tracking import TrackingLink
from app.models.user import User
from app.models.traffic_quality import TrafficQualitySettings, TrafficQualityState, TrafficQualityDelivery, TrafficQualityAcknowledgement
from app.services.access_control import has_project_access
from app.services.system_setting_service import SystemSettingService
from app.services.traffic_quality_service import TrafficQualityService, rule_hash
from app.schemas.traffic_quality import effective_rules
from app.services.operational_alert_service import send_operational_alert

logger = logging.getLogger(__name__)


async def evaluate_quality(session_factory=async_session_factory):
    async with session_factory() as db:
        candidates = (await db.execute(select(TrackingLink.id, TrackingLink.project_id).join(
            TrafficQualitySettings, TrafficQualitySettings.project_id == TrackingLink.project_id,
        ).join(Project, Project.id == TrackingLink.project_id).where(
            TrackingLink.is_active.is_(True), Project.is_deleted.is_(False),
            TrafficQualitySettings.config["enabled"].as_boolean().is_(True),
        ))).all()
    for link_id, project_id in candidates:
        try:
            async with session_factory() as db:
                link = await db.scalar(select(TrackingLink).where(TrackingLink.id == link_id).with_for_update(skip_locked=True))
                if link is None or not link.is_active:
                    continue
                service = TrafficQualityService(db)
                config = await service.config(project_id)
                project = await db.get(Project, project_id)
                if config.enabled and project and not project.is_deleted:
                    async with asyncio.timeout(90):
                        await service.check_link(project, link, config)
                await db.commit()
        except Exception as exc:
            logger.exception("traffic_quality evaluation failed project_id=%s link_id=%s", project_id, link_id)
            await send_operational_alert(component="traffic_quality", title="Traffic quality calculation failed",
                details={"project_id": project_id, "link_id": link_id, "error_type": type(exc).__name__},
                dedupe_key=f"traffic-quality:{project_id}:{type(exc).__name__}")


async def deliver_quality(limit=100, session_factory=async_session_factory):
    for _ in range(limit):
        now = datetime.now(timezone.utc)
        async with session_factory() as db:
            delivery = await db.scalar(select(TrafficQualityDelivery).where(
                TrafficQualityDelivery.status.in_(("pending", "sending", "retry")),
                TrafficQualityDelivery.available_at <= now,
            ).order_by(TrafficQualityDelivery.available_at).with_for_update(skip_locked=True).limit(1))
            if delivery is None:
                return
            service = TrafficQualityService(db)
            config = await service.config(delivery.project_id)
            link = await db.get(TrackingLink, delivery.link_id)
            project = await db.get(Project, delivery.project_id)
            user = await db.scalar(select(User).options(selectinload(User.role), selectinload(User.project_accesses)).where(User.id == delivery.recipient_id))
            allowed = bool(config.enabled and link and link.is_active and project and not project.is_deleted
                           and user and not user.is_deleted and has_project_access(user, delivery.project_id))
            if allowed:
                allowed = (link.buyer_id == user.id and user.role_name == RoleName.BUYER) if delivery.bot_kind == "buyer" else user.role_name in {RoleName.ADMIN, RoleName.SUPER_ADMIN}
            rules = effective_rules(config, await service.overrides(link.id)) if allowed else []
            by_id = {str(rule.id): rule for rule in rules}
            defer_until = None
            for item in delivery.payload.get("rules", []):
                rule = by_id.get(item["rule_id"])
                if not rule or not service.applies(rule, link) or rule_hash(rule, config.timezone) != item["config_hash"]:
                    allowed = False
                    break
                state = await db.get(TrafficQualityState, (link.id, rule.id))
                if not state or state.active != item["active"] or state.generation != item["generation"] or state.status in ("configuration_error", "insufficient_data"):
                    allowed = False
                    break
                ack = await db.get(TrafficQualityAcknowledgement, (link.id, delivery.recipient_id))
                if state.active and ack and ack.until > now and ack.generations.get(str(state.rule_id)) == state.generation:
                    defer_until = ack.until
            if not allowed:
                delivery.status, delivery.error = "cancelled", "Правило, состояние или доступ получателя изменились"
                await db.commit()
                continue
            if defer_until:
                delivery.status, delivery.available_at = "pending", defer_until
                await db.commit()
                continue
            settings_service = SystemSettingService(db)
            if delivery.bot_kind == "buyer":
                token = (await settings_service.get_effective_buyer_bot_config()).token
            else:
                token = (await settings_service.get_effective_global_config()).admin_bot_token
            delivery.attempts += 1
            recipient_chat_id = user.buyer_telegram_id if delivery.bot_kind == "buyer" else user.telegram_id
            if not token or not recipient_chat_id:
                delivery.status = "failed" if delivery.attempts >= 8 else "retry"
                delivery.error = "Не настроен бот или Telegram ID получателя"
                delivery.available_at = now + timedelta(hours=1)
                await db.commit()
                continue
            delivery.status, delivery.available_at = "sending", now + timedelta(minutes=5)
            delivery_id, attempt = delivery.id, delivery.attempts
            telegram_id, body, kind, link_id = int(recipient_chat_id), delivery.body, delivery.bot_kind, link.id
            await db.commit()
        # Lease was committed before the HTTP request. Telegram has no idempotency
        # key: a timeout after acceptance can result in a duplicate on retry.
        error, permanent = None, False
        try:
            buttons = [[{"text": "Статистика ссылки", "callback_data": f"quality:stats:{link_id}"}],
                       [{"text": "Принял (24 ч)", "callback_data": f"quality:ack:{link_id}"},
                        {"text": "Напомнить через час", "callback_data": f"quality:snooze:{link_id}"}]]
            payload = {"chat_id": telegram_id, "text": body[:4000]}
            if kind == "buyer":
                payload["reply_markup"] = {"inline_keyboard": buttons}
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)
                data = response.json()
                if not response.is_success or not data.get("ok"):
                    error = str(data.get("description") or f"Telegram HTTP {response.status_code}").replace(token, "[redacted]")[:500]
                    permanent = response.status_code in (400, 401, 403, 404)
        except Exception as exc:
            error = type(exc).__name__
        async with session_factory() as db:
            delivery = await db.get(TrafficQualityDelivery, delivery_id)
            if delivery and delivery.status == "sending" and delivery.attempts == attempt:
                delivery.error = error
                if error:
                    delivery.status = "failed" if permanent or attempt >= 8 else "retry"
                    delivery.available_at = datetime.now(timezone.utc) + timedelta(seconds=min(3600, 30 * 2 ** attempt))
                    logger.warning("traffic_quality delivery failed id=%s attempt=%s status=%s error=%s", delivery_id, attempt, delivery.status, error)
                else:
                    delivery.status, delivery.sent_at = "sent", datetime.now(timezone.utc)
                await db.commit()


async def run_quality_cycle():
    await evaluate_quality()
    await deliver_quality()
