from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, update, delete, func, or_
from sqlalchemy.dialects.postgresql import insert

from app.models.advertising import AdvertisingConfig, AdvertisingSlot, AdvertisingEnrollment, AdvertisingDelivery, AdvertisingAudit
from app.models.bot import Bot
from app.models.chat import Chat
from app.models.lead import Lead, LeadTag
from app.models.lead_status import LeadStatus
from app.models.project import Project
from app.models.tag import Tag
from app.models.broadcast import BroadcastUpload
from app.repositories.funnel_repository import FunnelRepository
from app.schemas.advertising import AdvertisingSettings, SlotWrite


def now():
    return datetime.now(timezone.utc)


class AdvertisingService:
    def __init__(self, db):
        self.db = db

    def audit(self, project_id, event, actor_id=None, **details):
        row = AdvertisingAudit(project_id=project_id, event=event, actor_id=actor_id, details=details)
        self.db.add(row)
        return row

    async def config(self, project_id):
        row = await self.db.get(AdvertisingConfig, project_id, populate_existing=True)
        return AdvertisingSettings.model_validate({**(row.settings_json if row else {}), "enabled": bool(row and row.enabled)})

    async def save_config(self, project_id, data: AdvertisingSettings, actor_id):
        project = await self.db.get(Project, project_id)
        if project is None or project.is_deleted or project.project_format != "submission":
            raise HTTPException(422, "Рекламный сценарий доступен для проектов с подачей")
        if data.enabled and (not data.bot_ids or not data.audience_tag_id):
            raise HTTPException(422, "Выберите ботов и тег рекламной аудитории")
        bots = (await self.db.scalars(select(Bot.id).where(Bot.project_id == project_id,
            Bot.is_deleted.is_(False), Bot.transport_type == "bot_api", Bot.id.in_(data.bot_ids)))).all()
        if set(bots) != set(data.bot_ids):
            raise HTTPException(422, "Выберите действующих ботов этого проекта")
        tags = set(data.protected_tag_ids) | ({data.audience_tag_id} if data.audience_tag_id else set())
        valid = set((await self.db.scalars(select(Tag.id).where(Tag.project_id == project_id, Tag.id.in_(tags)))).all())
        if tags != valid or data.audience_tag_id in data.protected_tag_ids:
            raise HTTPException(422, "Проверьте защитные теги и отдельный тег рекламы")
        if data.audience_tag_id and str(data.audience_tag_id) in (project.tracking_lead_tag_ids or []):
            raise HTTPException(422, "Тег рекламной аудитории не может быть тегом целевого лида")
        await self.db.execute(insert(AdvertisingConfig).values(project_id=project_id, enabled=False,
            settings_json={}).on_conflict_do_nothing())
        row = await self.db.get(AdvertisingConfig, project_id, with_for_update=True, populate_existing=True)
        if data.enabled and not row.enabled:
            row.enabled_at = now()
        row.enabled = data.enabled
        row.settings_json = data.model_dump(mode="json", exclude={"enabled"})
        self.audit(project_id, "settings_saved", actor_id, settings=data.model_dump(mode="json"))
        await self.db.flush()
        return data

    async def save_slot(self, project_id, data: SlotWrite, actor_id, slot_id=None):
        from app.services.broadcast_service import BroadcastService
        content = copy.deepcopy(data.content_json)
        messages = content.get("messages", [])
        if not isinstance(messages, list) or len(messages) != 1 or not isinstance(messages[0], dict) or content.get("after_send_action"):
            raise HTTPException(422, "Слот содержит один пост без запуска воронки")
        message = messages[0]
        if message.get("type", "text") not in {"text", "photo", "video", "voice", "video_note", "document"}:
            raise HTTPException(422, "Неизвестный тип поста")
        if message.get("delay_seconds", 0):
            raise HTTPException(422, "Интервал задаётся у слота, не внутри поста")
        buttons = message.get("buttons") or []
        if not isinstance(buttons, list):
            raise HTTPException(422, "Кнопки должны быть списком")
        for button in buttons:
            if not isinstance(button, dict) or button.get("type") != "url" or not str(button.get("url", "")).startswith(("https://", "http://", "tg://")):
                raise HTTPException(422, "В рекламе доступны только кнопки-ссылки")
        BroadcastService(self.db)._validate_content(content)
        media = message.get("media") or {}
        if not isinstance(media, dict):
            raise HTTPException(422, "Некорректные параметры медиа")
        if media.get("telegram_file_id"):
            raise HTTPException(422, "Загрузите файл: Telegram file_id нельзя переносить между ботами")
        if media.get("upload_id"):
            try:
                upload_id = UUID(str(media["upload_id"]))
            except ValueError:
                raise HTTPException(422, "Некорректный идентификатор медиа") from None
            upload = await self.db.get(BroadcastUpload, upload_id)
            if upload is None or upload.project_id != project_id or upload.media_type != message["type"] or not upload.storage_path:
                raise HTTPException(422, "Медиа не принадлежит проекту или имеет другой тип")
            from pathlib import Path
            from app.core.config import settings
            path = Path(upload.storage_path).resolve()
            if not path.is_relative_to(Path(settings.BROADCAST_UPLOAD_STORAGE_PATH).resolve()) or not path.is_file():
                raise HTTPException(422, "Медиафайл недоступен. Загрузите его заново")
            upload.expires_at = None
        slot = await self.db.get(AdvertisingSlot, slot_id, with_for_update=True) if slot_id else None
        if slot_id and (slot is None or slot.project_id != project_id):
            raise HTTPException(404, "Слот не найден")
        if slot is not None and slot.revision != data.revision:
            raise HTTPException(409, "Слот уже изменён. Обновите страницу")
        if slot is None:
            slot = AdvertisingSlot(project_id=project_id, revision=0)
            self.db.add(slot)
        for key in ("name", "position", "enabled", "delay_minutes"):
            setattr(slot, key, getattr(data, key))
        slot.content_json = content
        slot.revision += 1
        await self.db.flush()
        self.audit(project_id, "slot_saved", actor_id, slot_id=str(slot.id), revision=slot.revision)
        return slot

    async def watch_start(self, chat_id):
        chat = await self.db.get(Chat, chat_id)
        if chat is None:
            return
        cfg = await self.config(chat.project_id)
        if not cfg.enabled or chat.bot_id not in cfg.bot_ids:
            return
        await self.db.execute(insert(AdvertisingEnrollment).values(
            id=uuid4(), project_id=chat.project_id, chat_id=chat.id, status="waiting",
            due_at=now() + timedelta(minutes=cfg.timeout_minutes), source="automatic", stop_main=True,
        ).on_conflict_do_nothing())

    async def owns_chat(self, chat_id):
        return await self.db.scalar(select(AdvertisingEnrollment.id).where(
            AdvertisingEnrollment.chat_id == chat_id,
            AdvertisingEnrollment.started_at.is_not(None),
            AdvertisingEnrollment.status != "returned",
            AdvertisingEnrollment.stop_main.is_(True),
        ).limit(1)) is not None

    async def return_to_main(self, chat_id, *, reason="returned_after_inactivity"):
        rows = (await self.db.scalars(select(AdvertisingEnrollment).where(
            AdvertisingEnrollment.chat_id == chat_id, AdvertisingEnrollment.status != "returned",
        ).with_for_update())).all()
        for row in rows:
            row.status, row.due_at = "returned", None
            if row.marker_tag_id:
                await self.db.execute(delete(LeadTag).where(LeadTag.tag_id == row.marker_tag_id,
                    LeadTag.lead_id.in_(select(Lead.id).where(Lead.chat_id == chat_id))))
            await self.db.execute(update(AdvertisingDelivery).where(
                AdvertisingDelivery.enrollment_id == row.id, AdvertisingDelivery.status.in_(["pending", "sending"]),
            ).values(status="cancelled"))
            self.audit(row.project_id, reason, enrollment_id=str(row.id))
        # Production sessions do not autoflush. Release the live-chat unique key
        # before the same transaction registers the new main-funnel lifecycle.
        await self.db.flush()

    async def protected_reason(self, chat, cfg):
        if chat.is_deleted or chat.reset_at is not None or chat.is_blocked or chat.is_blocked_by_user:
            return "chat_unavailable"
        lead = await self.db.scalar(select(Lead).where(Lead.chat_id == chat.id, Lead.is_deleted.is_(False))
            .execution_options(populate_existing=True))
        if lead is None:
            return "lead_missing"
        project = await self.db.get(Project, chat.project_id, populate_existing=True)
        if project is None or project.is_deleted or project.status != "active" or project.project_format != "submission":
            return "project_unavailable"
        bot = await self.db.get(Bot, chat.bot_id, populate_existing=True)
        if bot is None or bot.is_deleted or bot.transport_type != "bot_api":
            return "bot_unavailable"
        tag_ids = set((await self.db.scalars(select(LeadTag.tag_id).where(LeadTag.lead_id == lead.id))).all())
        if tag_ids.intersection(cfg.protected_tag_ids):
            return "protected_tag"
        if project.tracking_lead_count_mode == "tags":
            if {str(t) for t in tag_ids}.intersection(project.tracking_lead_tag_ids or []):
                return "target_lead"
        else:
            status = await self.db.get(LeadStatus, lead.status_id) if lead.status_id else None
            if status and status.code in (project.tracking_lead_status_codes or []):
                return "target_lead"
        return None

    async def activate(self, enrollment, chat, cfg, *, start_slots=True):
        reason = await self.protected_reason(chat, cfg)
        state = await FunnelRepository(self.db).get_chat_funnel_state(chat.id)
        if not reason and state and state.is_paused and state.paused_by_user_id:
            reason = "manager_paused"
        if reason:
            enrollment.status, enrollment.reason, enrollment.due_at = "protected", reason, None
            return False
        slots = (await self.db.scalars(select(AdvertisingSlot).where(
            AdvertisingSlot.project_id == chat.project_id, AdvertisingSlot.enabled.is_(True),
        ).order_by(AdvertisingSlot.position, AdvertisingSlot.id))).all() if start_slots else []
        if start_slots and not slots:
            enrollment.reason = "no_active_slots"
            enrollment.due_at = now() + timedelta(minutes=5)
            return False
        lead = await self.db.scalar(select(Lead).where(Lead.chat_id == chat.id, Lead.is_deleted.is_(False)))
        if cfg.audience_tag_id:
            added = await self.db.execute(insert(LeadTag).values(lead_id=lead.id, tag_id=cfg.audience_tag_id).on_conflict_do_nothing())
            if added.rowcount:
                enrollment.marker_tag_id = cfg.audience_tag_id
        if enrollment.stop_main:
            from app.repositories.bot_repository import BotRepository
            await BotRepository(self.db).disable_bot_for_chat(chat.id)
            repo = FunnelRepository(self.db)
            await repo.cancel_scheduled_jobs_for_chat(chat_id=chat.id)
            if state:
                await repo.set_chat_funnel_paused(chat_id=chat.id, is_paused=True, paused_at=now(), paused_by_user_id=None)
                await repo.update_chat_funnel_runtime(chat_id=chat.id,
                    runtime_json={**(state.runtime_json or {}), "advertising_enrollment_id": str(enrollment.id)})
        for index, slot in enumerate(slots):
            self.db.add(AdvertisingDelivery(enrollment_id=enrollment.id, slot_id=slot.id,
                position=index, delay_minutes=slot.delay_minutes, status="pending"))
        enrollment.started_at = now()
        enrollment.status = "active" if slots else "completed"
        enrollment.due_at = now() if slots else None
        self.audit(chat.project_id, "advertising_entered", enrollment_id=str(enrollment.id), slots=len(slots), source=enrollment.source)
        await self.db.flush()
        return True

    async def finish_delivery(self, enrollment, delivery, status, error=None):
        delivery.status, delivery.error = status, error
        if status == "sent":
            delivery.sent_at = now()
        await self.db.flush()
        following = await self.db.scalar(select(AdvertisingDelivery).where(
            AdvertisingDelivery.enrollment_id == enrollment.id, AdvertisingDelivery.status == "pending",
        ).order_by(AdvertisingDelivery.position).limit(1))
        enrollment.due_at = now() + timedelta(minutes=following.delay_minutes) if following else None
        if not following:
            enrollment.status = "completed"
        self.audit(enrollment.project_id, "slot_delivery", enrollment_id=str(enrollment.id),
            delivery_id=str(delivery.id), slot_id=str(delivery.slot_id), status=status, error=error)

    async def stop(self, enrollment, reason, status="stopped"):
        enrollment.status, enrollment.reason, enrollment.due_at = status, reason, None
        await self.db.execute(update(AdvertisingDelivery).where(
            AdvertisingDelivery.enrollment_id == enrollment.id, AdvertisingDelivery.status == "pending",
        ).values(status="cancelled", error=reason))
        self.audit(enrollment.project_id, "advertising_stopped", enrollment_id=str(enrollment.id), reason=reason)
