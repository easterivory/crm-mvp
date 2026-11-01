"""Explicit, bounded historical runs; never activated by saving project settings."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import select, or_

from app.models.advertising import AdvertisingAudit, AdvertisingEnrollment
from app.models.chat import Chat
from app.models.lead import Lead, LeadTag
from app.models.lead_status import LeadStatus
from app.models.funnel import ChatFunnelState
from app.models.project import Project
from app.services.advertising_service import AdvertisingService, now


async def eligible_chats(db, project_id, cfg, before):
    project = await db.get(Project, project_id)
    protected = set(cfg.protected_tag_ids)
    if project.tracking_lead_count_mode == "tags":
        protected.update(UUID(t) for t in project.tracking_lead_tag_ids or [])
    stmt = select(Chat.id).join(Lead, Lead.chat_id == Chat.id).where(
        Chat.project_id == project_id, Chat.bot_id.in_(cfg.bot_ids), Chat.created_at < before,
        Chat.is_deleted.is_(False), Chat.reset_at.is_(None), Chat.is_blocked.is_(False), Chat.is_blocked_by_user.is_(False),
        Lead.is_deleted.is_(False),
        ~select(LeadTag.lead_id).where(LeadTag.lead_id == Lead.id, LeadTag.tag_id.in_(protected)).exists(),
        ~select(AdvertisingEnrollment.id).where(AdvertisingEnrollment.chat_id == Chat.id,
            AdvertisingEnrollment.status != "returned").exists(),
        ~select(ChatFunnelState.id).where(ChatFunnelState.chat_id == Chat.id,
            ChatFunnelState.is_paused.is_(True), ChatFunnelState.paused_by_user_id.is_not(None)).exists(),
    )
    if project.tracking_lead_count_mode != "tags":
        stmt = stmt.where(~select(LeadStatus.id).where(LeadStatus.id == Lead.status_id,
            LeadStatus.code.in_(project.tracking_lead_status_codes or [])).exists())
    return stmt.order_by(Chat.id)


async def process_backfill(db, limit=25):
    run = await db.scalar(select(AdvertisingAudit).where(AdvertisingAudit.event == "backfill_preview",
        AdvertisingAudit.details["state"].astext == "queued").order_by(AdvertisingAudit.created_at).limit(1).with_for_update(skip_locked=True))
    if run is None:
        return
    service = AdvertisingService(db)
    cfg = await service.config(run.project_id)
    progress = dict(run.details)
    if not cfg.enabled or progress["settings"] != cfg.model_dump(mode="json"):
        run.details = {**progress, "state": "stopped_settings_changed"}
        return
    options = progress["options"]
    stmt = await eligible_chats(db, run.project_id, cfg, datetime.fromisoformat(options["created_before"]))
    if progress.get("cursor"):
        stmt = stmt.where(Chat.id > UUID(progress["cursor"]))
    ids = list((await db.scalars(stmt.limit(limit))).all())
    for chat_id in ids:
        chat = await db.scalar(select(Chat).where(Chat.id == chat_id).with_for_update())
        if await db.scalar(select(AdvertisingEnrollment.id).where(AdvertisingEnrollment.chat_id == chat_id,
            AdvertisingEnrollment.status != "returned").limit(1)):
            continue
        enrollment = AdvertisingEnrollment(project_id=run.project_id, chat_id=chat_id,
            source="backfill", stop_main=options["stop_main"], status="waiting", due_at=now())
        db.add(enrollment)
        await db.flush()
        await service.activate(enrollment, chat, cfg, start_slots=options["start_slots"])
        progress["processed"] += 1
    if ids:
        progress["cursor"] = str(ids[-1])
    if len(ids) < limit:
        progress["state"] = "completed"
    run.details = progress
