"""Read-only diagnosis and explicitly authorised, effect-free single-job recovery."""
import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import String, cast, select

from app.core.constants import RoleName
from app.models import AuditLog, Bot, Chat, Message, Project
from app.models.funnel import ChatFunnelState
from app.models.telegram_delivery import RuntimeDispatch
from app.services.access_control import require_project_access


async def runtime_snapshot(db, chat_id):
    try: chat_id = UUID(str(chat_id))
    except (TypeError, ValueError): return None
    latest_query = select(Message.id).where(Message.chat_id == chat_id, Message.sender_type == "user").order_by(
        Message.created_at.desc(), Message.id.desc()).limit(1).scalar_subquery()
    edit_query = select(Message.edited_at).where(Message.chat_id == chat_id, Message.sender_type == "user").order_by(
        Message.created_at.desc(), Message.id.desc()).limit(1).scalar_subquery()
    pair = (await db.execute(select(Chat, ChatFunnelState, latest_query, edit_query,
        Bot.active_funnel_version_id, Bot.is_deleted, Project.status, Project.is_deleted).select_from(Chat)
        .outerjoin(ChatFunnelState, ChatFunnelState.chat_id == Chat.id).outerjoin(Bot, Bot.id == Chat.bot_id)
        .join(Project, Project.id == Chat.project_id).where(Chat.id == chat_id).execution_options(populate_existing=True))).first()
    if pair is None: return None
    chat, state, latest, edited_at, active_version, bot_deleted, project_status, project_deleted = pair
    data = {"chat": {k: str(getattr(chat, k)) for k in ("bot_id", "reset_at", "is_deleted", "is_blocked", "is_blocked_by_user", "current_cycle_started_at")},
        "state": {k: getattr(state, k) for k in ("id", "funnel_version_id", "current_step_id", "entered_step_at",
            "is_paused", "waiting_for_answer", "completed_at", "runtime_json")} if state else None, "latest_user_message_id": latest,
        "latest_user_message_edited_at": edited_at,
        "bot_active_version": active_version, "bot_deleted": bot_deleted,
        "project_status": project_status, "project_deleted": project_deleted}
    return hashlib.sha256(json.dumps(data, default=str, sort_keys=True).encode()).hexdigest()


def review_access(actor, project_id):
    require_project_access(actor, project_id)
    if actor.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}: raise HTTPException(403)


class RuntimeReviewService:
    def __init__(self, db): self.db = db

    def query(self, project_id):
        return select(RuntimeDispatch, Chat).join(Chat,
            RuntimeDispatch.payload_json["chat_id"].astext == cast(Chat.id, String)).where(Chat.project_id == project_id)

    async def describe(self, row, chat):
        snapshot = await runtime_snapshot(self.db, chat.id)
        details = row.diagnostics_json or {}
        eligible = bool(row.status == "review" and row.kind in {"input", "start"}
            and details.get("safe_to_replay") is True and details.get("snapshot") == snapshot
            and not chat.is_deleted and not chat.is_blocked and not chat.is_blocked_by_user and chat.reset_at is None)
        return {"id": row.id, "chat_id": chat.id, "bot_id": chat.bot_id, "kind": row.kind, "status": row.status,
            "attempts": row.attempts, "failure_count": row.failure_count, "created_at": row.created_at,
            "last_error": row.last_error, "diagnostics": details, "fingerprint": snapshot, "can_retry": eligible}

    async def list(self, project_id, actor, status="review", limit=50, offset=0):
        review_access(actor, project_id)
        rows = (await self.db.execute(self.query(project_id).where(RuntimeDispatch.status == status)
            .order_by(RuntimeDispatch.created_at, RuntimeDispatch.id).limit(limit).offset(offset))).all()
        return [await self.describe(row, chat) for row, chat in rows]

    async def retry(self, project_id, actor, dispatch_id, fingerprint, reason):
        review_access(actor, project_id)
        pair = (await self.db.execute(self.query(project_id).where(RuntimeDispatch.id == dispatch_id))).first()
        if pair is None: raise HTTPException(404)
        row, chat = pair
        # Same order as runtime: chat first, then transport row. Never contact Redis here.
        await self.db.refresh(chat, with_for_update={"key_share": True})
        await self.db.refresh(row, with_for_update=True)
        result = await self.describe(row, chat)
        if not result["can_retry"] or fingerprint != result["fingerprint"]:
            raise HTTPException(409, "Повтор небезопасен: результат отправки неизвестен или состояние чата изменилось")
        if not reason.strip(): raise HTTPException(422, "Укажите основание повтора")
        self.db.add(AuditLog(project_id=project_id, actor_id=actor.id, action="runtime_dispatch_retry",
            entity_type="chat", entity_id=chat.id, meta={"dispatch_id": str(row.id), "reason": reason,
                "previous_diagnostics": row.diagnostics_json, "failure_count": row.failure_count}))
        row.status, row.claimed_at, row.completed_at = "pending", None, None
        row.available_at = datetime.now(timezone.utc)
        row.failure_count, row.last_error = 0, None
        row.diagnostics_json = {"recovery_actor_id": str(actor.id), "recovery_at": datetime.now(timezone.utc).isoformat()}
        await self.db.flush()
        return {"id": row.id, "status": row.status}
