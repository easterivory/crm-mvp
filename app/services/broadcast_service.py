from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import MessageType, RoleName, SenderType
from app.models.broadcast import Broadcast
from app.models.chat import Chat
from app.models.lead import Lead
from app.models.user import User
from app.repositories.bot_repository import BotRepository
from app.repositories.broadcast_repository import BroadcastRepository
from app.repositories.funnel_repository import FunnelRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.broadcast import (
    AudienceFilter,
    AudiencePreviewRequest,
    AudiencePreviewResponse,
    BroadcastActionResponse,
    BroadcastCreate,
    BroadcastOut,
    BroadcastReport,
    BroadcastScheduleRequest,
    BroadcastTemplateCreate,
    BroadcastTemplateOut,
    BroadcastTemplateUpdate,
    BroadcastUpdate,
    SendNowRequest,
)
from app.schemas.message import MessageCreate
from app.services.audience_filter_service import AudienceFilterService
from app.services.audit_service import AuditService
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.message_service import MessageService
from app.services.telegram_sender import TelegramSenderService


class BroadcastService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = BroadcastRepository(db)
        self.bot_repo = BotRepository(db)
        self.funnel_repo = FunnelRepository(db)
        self.project_repo = ProjectRepository(db)
        self.audience = AudienceFilterService(db)
        self.audit = AuditService(db)
        self.telegram_sender = TelegramSenderService(db)
        self.funnel_runtime = FunnelRuntimeService(db)

    async def list_broadcasts(
        self,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[BroadcastOut], int]:
        items = await self.repo.list_by_project(project_id, limit=limit, offset=offset)
        total = await self.repo.count_by_project(project_id)
        return [BroadcastOut.model_validate(item) for item in items], total

    async def get_broadcast(self, broadcast_id: UUID, project_id: UUID) -> BroadcastOut:
        broadcast = await self._get_or_404(broadcast_id, project_id)
        return BroadcastOut.model_validate(broadcast)

    async def report(self, broadcast_id: UUID, project_id: UUID) -> BroadcastReport:
        broadcast = await self._get_or_404(broadcast_id, project_id)
        counts = await self.repo.status_counts(broadcast.id)
        return BroadcastReport(
            total_recipients=sum(counts.values()),
            pending=counts.get("pending", 0),
            sent=counts.get("sent", 0),
            failed=counts.get("failed", 0),
            skipped=counts.get("skipped", 0),
            cancelled=0,
            started_at=broadcast.started_at,
            finished_at=broadcast.sent_at,
            error_examples=await self.repo.error_examples(broadcast.id),
        )

    async def list_templates(
        self,
        *,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> list[BroadcastTemplateOut]:
        templates = await self.repo.list_templates_by_project(project_id, limit=limit, offset=offset)
        return [BroadcastTemplateOut.model_validate(item) for item in templates]

    async def create_template(
        self,
        *,
        actor: User,
        project_id: UUID,
        data: BroadcastTemplateCreate,
    ) -> BroadcastTemplateOut:
        self._ensure_can_manage(actor)
        if data.project_id != project_id:
            raise HTTPException(status_code=422, detail="project_id does not match current project")
        self._validate_content(data.content_json)
        template = await self.repo.create_template(
            project_id=project_id,
            name=data.name,
            content_json=data.content_json,
            created_by_user_id=actor.id,
        )
        await self._audit(
            project_id=project_id,
            actor=actor,
            action="broadcast_template.created",
            entity_id=template.id,
            meta={"name": template.name},
        )
        return BroadcastTemplateOut.model_validate(template)

    async def update_template(
        self,
        *,
        template_id: UUID,
        actor: User,
        project_id: UUID,
        data: BroadcastTemplateUpdate,
    ) -> BroadcastTemplateOut:
        self._ensure_can_manage(actor)
        existing = await self.repo.get_template_in_project(template_id, project_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Broadcast template not found")
        values = data.model_dump(exclude_unset=True)
        if "content_json" in values:
            self._validate_content(values["content_json"])
        template = await self.repo.update_template_in_project(template_id, project_id, **values)
        assert template is not None
        await self._audit(
            project_id=project_id,
            actor=actor,
            action="broadcast_template.updated",
            entity_id=template.id,
            meta={"name": template.name},
        )
        return BroadcastTemplateOut.model_validate(template)

    async def delete_template(
        self,
        *,
        template_id: UUID,
        actor: User,
        project_id: UUID,
    ) -> None:
        self._ensure_can_manage(actor)
        deleted = await self.repo.delete_template_in_project(template_id, project_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Broadcast template not found")
        await self._audit(
            project_id=project_id,
            actor=actor,
            action="broadcast_template.deleted",
            entity_id=template_id,
        )

    async def create_broadcast(
        self,
        *,
        actor: User,
        project_id: UUID,
        data: BroadcastCreate,
    ) -> BroadcastOut:
        self._ensure_can_manage(actor)
        if data.project_id != project_id:
            raise HTTPException(status_code=422, detail="project_id does not match current project")
        if data.bot_id is not None:
            await self._ensure_bot(project_id, data.bot_id)

        broadcast = await self.repo.create(
            project_id=project_id,
            bot_id=data.bot_id,
            name=data.name,
            content_json=data.content_json,
            audience_filter_json=data.audience_filter_json,
            schedule_type=data.schedule_type,
            scheduled_at=data.scheduled_at,
            timezone_mode=data.timezone_mode,
            status="draft",
            created_by_user_id=actor.id,
        )
        await self._audit(
            project_id=project_id,
            actor=actor,
            action="broadcast.created",
            entity_id=broadcast.id,
            meta={"name": broadcast.name},
        )
        return BroadcastOut.model_validate(broadcast)

    async def update_broadcast(
        self,
        *,
        broadcast_id: UUID,
        actor: User,
        project_id: UUID,
        data: BroadcastUpdate,
    ) -> BroadcastOut:
        self._ensure_can_manage(actor)
        broadcast = await self._get_or_404(broadcast_id, project_id)
        if broadcast.status not in {"draft", "audience_ready", "scheduled"}:
            raise HTTPException(status_code=422, detail="Broadcast cannot be edited in current status")
        values = data.model_dump(exclude_unset=True)
        if "bot_id" in values and values["bot_id"] is not None:
            await self._ensure_bot(project_id, values["bot_id"])
        if values:
            values["status"] = "draft" if broadcast.status == "audience_ready" else broadcast.status
            broadcast = await self.repo.update_in_project(broadcast_id, project_id, **values)
        return BroadcastOut.model_validate(broadcast)

    async def preview_audience(
        self,
        *,
        project_id: UUID,
        data: AudiencePreviewRequest,
    ) -> AudiencePreviewResponse:
        if data.project_id != project_id:
            raise HTTPException(status_code=422, detail="project_id does not match current project")
        if data.bot_id is not None:
            await self._ensure_bot(project_id, data.bot_id)
        return await self.audience.preview(
            project_id=project_id,
            bot_id=data.bot_id,
            audience_filter=data.audience_filter,
        )

    async def preview_broadcast_audience(
        self,
        *,
        broadcast_id: UUID,
        project_id: UUID,
    ) -> AudiencePreviewResponse:
        broadcast = await self._get_or_404(broadcast_id, project_id)
        return await self.audience.preview(
            project_id=project_id,
            bot_id=broadcast.bot_id,
            audience_filter=broadcast.audience_filter_json,
        )

    async def send_now(
        self,
        *,
        broadcast_id: UUID,
        actor: User,
        project_id: UUID,
        data: SendNowRequest | None = None,
    ) -> BroadcastActionResponse:
        self._ensure_can_manage(actor)
        broadcast = await self._get_or_404(broadcast_id, project_id)
        audience = await self._snapshot_recipients(broadcast, project_id)
        self._validate_large_audience_confirmation(audience.count, data.confirmation if data else None)
        updated = await self.repo.update_in_project(
            broadcast.id,
            project_id,
            status="sending",
            schedule_type="now",
            scheduled_at=None,
            audience_count=audience.count,
            started_at=datetime.now(timezone.utc),
        )
        await self._audit(
            project_id=project_id,
            actor=actor,
            action="broadcast.send_now",
            entity_id=broadcast.id,
            meta={"audience_count": audience.count},
        )
        return BroadcastActionResponse(
            broadcast=BroadcastOut.model_validate(updated),
            audience=audience,
        )

    async def schedule(
        self,
        *,
        broadcast_id: UUID,
        actor: User,
        project_id: UUID,
        data: BroadcastScheduleRequest,
    ) -> BroadcastActionResponse:
        self._ensure_can_manage(actor)
        if data.scheduled_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=422, detail="scheduled_at must be in the future")
        broadcast = await self._get_or_404(broadcast_id, project_id)
        audience = await self._snapshot_recipients(broadcast, project_id)
        self._validate_large_audience_confirmation(audience.count, data.confirmation)
        updated = await self.repo.update_in_project(
            broadcast.id,
            project_id,
            status="scheduled",
            schedule_type="scheduled",
            scheduled_at=data.scheduled_at,
            timezone_mode=data.timezone_mode,
            audience_count=audience.count,
        )
        await self._audit(
            project_id=project_id,
            actor=actor,
            action="broadcast.scheduled",
            entity_id=broadcast.id,
            meta={"audience_count": audience.count, "scheduled_at": data.scheduled_at.isoformat()},
        )
        return BroadcastActionResponse(
            broadcast=BroadcastOut.model_validate(updated),
            audience=audience,
        )

    async def cancel(
        self,
        *,
        broadcast_id: UUID,
        actor: User,
        project_id: UUID,
    ) -> BroadcastOut:
        self._ensure_can_manage(actor)
        broadcast = await self._get_or_404(broadcast_id, project_id)
        if broadcast.status not in {"scheduled", "sending", "paused", "draft", "audience_ready"}:
            raise HTTPException(status_code=422, detail="Broadcast cannot be cancelled")
        updated = await self.repo.update_in_project(
            broadcast_id,
            project_id,
            status="cancelled",
        )
        await self.repo.mark_pending_skipped(broadcast_id, "Broadcast cancelled")
        await self._audit(
            project_id=project_id,
            actor=actor,
            action="broadcast.cancelled",
            entity_id=broadcast_id,
        )
        return BroadcastOut.model_validate(updated)

    async def pause(
        self,
        *,
        broadcast_id: UUID,
        actor: User,
        project_id: UUID,
    ) -> BroadcastOut:
        self._ensure_can_manage(actor)
        broadcast = await self._get_or_404(broadcast_id, project_id)
        if broadcast.status != "sending":
            raise HTTPException(status_code=422, detail="Only sending broadcasts can be paused")
        updated = await self.repo.update_in_project(broadcast_id, project_id, status="paused")
        await self._audit(project_id=project_id, actor=actor, action="broadcast.paused", entity_id=broadcast_id)
        return BroadcastOut.model_validate(updated)

    async def resume(
        self,
        *,
        broadcast_id: UUID,
        actor: User,
        project_id: UUID,
    ) -> BroadcastOut:
        self._ensure_can_manage(actor)
        broadcast = await self._get_or_404(broadcast_id, project_id)
        if broadcast.status != "paused":
            raise HTTPException(status_code=422, detail="Only paused broadcasts can be resumed")
        updated = await self.repo.update_in_project(broadcast_id, project_id, status="sending")
        await self._audit(project_id=project_id, actor=actor, action="broadcast.resumed", entity_id=broadcast_id)
        return BroadcastOut.model_validate(updated)

    async def process_due_broadcasts(self) -> int:
        processed = 0
        broadcasts = await self.repo.list_due_broadcasts(limit=20)
        for broadcast in broadcasts:
            if broadcast.status == "scheduled":
                broadcast = await self.repo.update_in_project(
                    broadcast.id,
                    broadcast.project_id,
                    status="sending",
                    started_at=datetime.now(timezone.utc),
                )
            if broadcast is None or broadcast.status != "sending":
                continue
            processed += await self._process_broadcast_batch(broadcast)
        return processed

    async def _process_broadcast_batch(self, broadcast: Broadcast) -> int:
        recipients = await self.repo.list_pending_recipients(
            broadcast.id,
            limit=settings.BROADCAST_BATCH_SIZE,
            max_attempts=settings.BROADCAST_MAX_ATTEMPTS,
        )
        if not recipients:
            counts = await self.repo.status_counts(broadcast.id)
            final_status = "failed" if counts.get("sent", 0) == 0 and counts.get("failed", 0) > 0 else "sent"
            await self.repo.update_in_project(
                broadcast.id,
                broadcast.project_id,
                status=final_status,
                sent_at=datetime.now(timezone.utc),
            )
            return 0

        sent = 0
        for recipient in recipients:
            fresh = await self.repo.get_in_project(broadcast.id, broadcast.project_id)
            if fresh is None or fresh.status in {"cancelled", "paused"}:
                break
            try:
                context = await self.repo.get_recipient_context(recipient)
                if context is None:
                    await self.repo.mark_recipient_failed(recipient.id, "Chat not found")
                    continue
                chat, lead = context
                await self._send_to_recipient(broadcast, recipient.chat_id, chat, lead)
                await self.repo.mark_recipient_sent(recipient.id)
                sent += 1
            except Exception as exc:
                await self.repo.mark_recipient_error(
                    recipient,
                    str(exc),
                    max_attempts=settings.BROADCAST_MAX_ATTEMPTS,
                )
            if settings.BROADCAST_SEND_INTERVAL_MS > 0:
                await asyncio.sleep(settings.BROADCAST_SEND_INTERVAL_MS / 1000)

        if await self.repo.count_pending_recipients(broadcast.id) == 0:
            counts = await self.repo.status_counts(broadcast.id)
            final_status = "failed" if counts.get("sent", 0) == 0 and counts.get("failed", 0) > 0 else "sent"
            await self.repo.update_in_project(
                broadcast.id,
                broadcast.project_id,
                status=final_status,
                sent_at=datetime.now(timezone.utc),
            )
        return sent

    async def _send_to_recipient(
        self,
        broadcast: Broadcast,
        chat_id: UUID,
        chat: Chat,
        lead: Lead | None,
    ) -> None:
        messages = self._content_messages(broadcast.content_json)
        service = MessageService(self.db)
        for message_index, message in enumerate(messages):
            delay_seconds = self._message_delay_seconds(message)
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
            text = await self._render_text(str(message.get("text") or ""), broadcast, chat, lead)
            if not text.strip():
                continue
            reply_markup = self._reply_markup_for_buttons(
                broadcast=broadcast,
                message_index=message_index,
                buttons=self._normalize_buttons(message.get("buttons") or []),
            )
            await service.create_message(
                chat_id=chat_id,
                project_id=broadcast.project_id,
                data=MessageCreate(
                    message_type=MessageType.TEXT,
                    sender_type=SenderType.BOT,
                    body=text,
                    reply_markup=reply_markup,
                ),
                send_to_telegram=False,
            )
            sent = await self.telegram_sender.send_message(
                project_id=broadcast.project_id,
                bot_id=broadcast.bot_id,
                external_chat_id=chat.external_chat_id,
                text=text,
                reply_markup=reply_markup,
            )
            if not sent:
                raise RuntimeError("Telegram sendMessage failed")
        await self._run_after_send_action(broadcast=broadcast, chat=chat)

    async def _snapshot_recipients(
        self,
        broadcast: Broadcast,
        project_id: UUID,
    ) -> AudiencePreviewResponse:
        self._validate_sendable(broadcast)
        assert broadcast.bot_id is not None
        recipients = await self.audience.resolve_recipients(
            project_id=project_id,
            bot_id=broadcast.bot_id,
            audience_filter=AudienceFilter.model_validate(broadcast.audience_filter_json or {}),
        )
        if not recipients:
            raise HTTPException(status_code=422, detail="Audience is empty")
        await self.repo.replace_recipients(broadcast.id, recipients)
        return await self.audience.preview(
            project_id=project_id,
            bot_id=broadcast.bot_id,
            audience_filter=broadcast.audience_filter_json,
        )

    def _validate_sendable(self, broadcast: Broadcast) -> None:
        if broadcast.bot_id is None:
            raise HTTPException(status_code=422, detail="Bot is required before sending")
        self._validate_content(broadcast.content_json)
        if broadcast.status in {"sending", "sent", "cancelled"}:
            raise HTTPException(status_code=422, detail="Broadcast cannot be sent in current status")

    def _validate_content(self, content: dict[str, Any]) -> None:
        messages = self._content_messages(content)
        if not any(str(message.get("text") or "").strip() for message in messages):
            raise HTTPException(status_code=422, detail="Broadcast content is empty")
        action = content.get("after_send_action") if isinstance(content, dict) else None
        if isinstance(action, dict) and action.get("type") == "start_funnel" and not action.get("funnel_id"):
            raise HTTPException(status_code=422, detail="start_funnel action requires funnel_id")

    @staticmethod
    def _content_messages(content: dict[str, Any]) -> list[dict[str, Any]]:
        raw_messages = content.get("messages") if isinstance(content, dict) else None
        if isinstance(raw_messages, list):
            return [item for item in raw_messages if isinstance(item, dict)]
        text = content.get("text") if isinstance(content, dict) else None
        return [{"type": "text", "text": text or ""}]

    async def _render_text(
        self,
        template: str,
        broadcast: Broadcast,
        chat: Chat,
        lead: Lead | None,
    ) -> str:
        custom_fields = lead.custom_fields if lead is not None and isinstance(lead.custom_fields, dict) else {}
        project = await self.project_repo.get_active(broadcast.project_id)
        bot = (
            await self.bot_repo.get_by_id_in_project(broadcast.bot_id, broadcast.project_id)
            if broadcast.bot_id is not None
            else None
        )
        values = {
            "first_name": lead.name if lead and lead.name else chat.contact_name or "",
            "name": lead.name if lead and lead.name else chat.contact_name or "",
            "username": lead.username if lead and lead.username else "",
            "phone": lead.phone if lead and lead.phone else "",
            "lead_status": lead.status.code if lead is not None and lead.status is not None else "",
            "project": project.name if project is not None else str(broadcast.project_id),
            "bot": bot.name if bot is not None else str(broadcast.bot_id or ""),
        }

        def replace(match: re.Match[str]) -> str:
            key = match.group(1).strip()
            if key.startswith("custom."):
                return str(custom_fields.get(key.removeprefix("custom."), ""))
            return str(values.get(key, match.group(0)))

        return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", replace, template)

    @staticmethod
    def _message_delay_seconds(message: dict[str, Any]) -> int:
        try:
            return max(int(message.get("delay_seconds") or 0), 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _normalize_buttons(raw_buttons: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_buttons, list):
            return []
        buttons: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_buttons):
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("label") or raw.get("text") or f"Кнопка {index + 1}").strip()
            if not label:
                continue
            button = {
                "id": str(raw.get("id") or f"btn_{index + 1}"),
                "label": label,
                "type": str(raw.get("type") or ("url" if raw.get("url") else "callback")),
                "url": raw.get("url"),
                "payload": raw.get("payload"),
                "funnel_id": raw.get("funnel_id"),
                "funnel_version_id": raw.get("funnel_version_id"),
                "mode": raw.get("mode") or raw.get("start_mode"),
            }
            buttons.append(button)
        return buttons

    def _reply_markup_for_buttons(
        self,
        *,
        broadcast: Broadcast,
        message_index: int,
        buttons: list[dict[str, Any]],
    ) -> dict | None:
        if not buttons:
            return None
        rows = []
        for button_index, button in enumerate(buttons):
            item = {"text": button["label"]}
            if button.get("type") == "url" and button.get("url"):
                item["url"] = button["url"]
            else:
                item["callback_data"] = f"bcf:{broadcast.id.hex}:{message_index}:{button_index}"
            rows.append([item])
        return {"inline_keyboard": rows}

    async def _run_after_send_action(self, *, broadcast: Broadcast, chat: Chat) -> None:
        action = (broadcast.content_json or {}).get("after_send_action")
        if not isinstance(action, dict) or action.get("type") != "start_funnel":
            return
        await self._start_funnel_for_chat(
            project_id=broadcast.project_id,
            bot_id=broadcast.bot_id,
            chat_id=chat.id,
            funnel_id=action.get("funnel_id"),
            funnel_version_id=action.get("funnel_version_id"),
            mode=str(action.get("mode") or "skip_if_active"),
            source="after_send",
            broadcast_id=broadcast.id,
        )

    async def process_start_funnel_callback(
        self,
        *,
        project_id: UUID,
        bot_id: UUID,
        chat_id: UUID,
        callback_data: str | None,
    ) -> bool:
        parsed = self._parse_broadcast_callback(callback_data)
        if parsed is None:
            return False
        broadcast_id, message_index, button_index = parsed
        broadcast = await self.repo.get_in_project(broadcast_id, project_id)
        if broadcast is None or broadcast.bot_id != bot_id:
            return False
        messages = self._content_messages(broadcast.content_json)
        if message_index < 0 or message_index >= len(messages):
            return False
        buttons = self._normalize_buttons(messages[message_index].get("buttons") or [])
        if button_index < 0 or button_index >= len(buttons):
            return False
        button = buttons[button_index]
        if button.get("type") != "start_funnel":
            await self.audit.log(
                project_id=project_id,
                actor_id=None,
                action="broadcast.button_clicked",
                entity_type="broadcast",
                entity_id=broadcast.id,
                meta={
                    "chat_id": str(chat_id),
                    "button_id": button.get("id"),
                    "payload": button.get("payload"),
                    "type": button.get("type"),
                },
            )
            return True
        await self._start_funnel_for_chat(
            project_id=project_id,
            bot_id=bot_id,
            chat_id=chat_id,
            funnel_id=button.get("funnel_id"),
            funnel_version_id=button.get("funnel_version_id"),
            mode=str(button.get("mode") or "skip_if_active"),
            source="button",
            broadcast_id=broadcast.id,
        )
        return True

    async def _start_funnel_for_chat(
        self,
        *,
        project_id: UUID,
        bot_id: UUID | None,
        chat_id: UUID,
        funnel_id: Any,
        funnel_version_id: Any,
        mode: str,
        source: str,
        broadcast_id: UUID,
    ) -> bool:
        if bot_id is None or not funnel_id:
            return False
        try:
            parsed_funnel_id = UUID(str(funnel_id))
            parsed_version_id = UUID(str(funnel_version_id)) if funnel_version_id else None
        except (TypeError, ValueError):
            raise RuntimeError("Invalid start_funnel action ids")

        funnel, version = await self.funnel_repo.get_published_version_for_broadcast(
            project_id=project_id,
            bot_id=bot_id,
            funnel_id=parsed_funnel_id,
            version_id=parsed_version_id,
        )
        if funnel is None or version is None:
            raise RuntimeError("Broadcast funnel is unavailable or unpublished")

        state = await self.funnel_repo.get_chat_funnel_state(chat_id)
        normalized_mode = mode if mode in {"restart", "skip_if_active", "skip_if_completed"} else "skip_if_active"
        if state is not None and state.completed_at is None and normalized_mode == "skip_if_active":
            return False
        if (
            state is not None
            and state.completed_at is not None
            and normalized_mode == "skip_if_completed"
            and state.funnel_id == funnel.id
            and state.funnel_version_id == version.id
        ):
            return False
        if normalized_mode == "restart":
            await self.funnel_runtime.reset_chat_state(chat_id)

        await self.funnel_runtime.start_funnel_for_chat(
            chat_id=chat_id,
            funnel_id=funnel.id,
            funnel_version_id=version.id,
        )
        await self.audit.log(
            project_id=project_id,
            actor_id=None,
            action="broadcast.funnel_started",
            entity_type="broadcast",
            entity_id=broadcast_id,
            meta={
                "chat_id": str(chat_id),
                "funnel_id": str(funnel.id),
                "funnel_version_id": str(version.id),
                "source": source,
                "mode": normalized_mode,
            },
        )
        return True

    @staticmethod
    def _parse_broadcast_callback(callback_data: str | None) -> tuple[UUID, int, int] | None:
        if not callback_data or not callback_data.startswith("bcf:"):
            return None
        parts = callback_data.split(":")
        if len(parts) != 4:
            return None
        try:
            return UUID(hex=parts[1]), int(parts[2]), int(parts[3])
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _validate_large_audience_confirmation(count: int, confirmation: str | None) -> None:
        if count > 1000 and confirmation != "ПОДТВЕРЖДАЮ":
            raise HTTPException(
                status_code=422,
                detail="Large audience requires confirmation text",
            )

    async def _get_or_404(self, broadcast_id: UUID, project_id: UUID) -> Broadcast:
        broadcast = await self.repo.get_in_project(broadcast_id, project_id)
        if broadcast is None:
            raise HTTPException(status_code=404, detail="Broadcast not found")
        return broadcast

    async def _ensure_bot(self, project_id: UUID, bot_id: UUID) -> None:
        bot = await self.bot_repo.get_by_id_in_project(bot_id, project_id)
        if bot is None:
            raise HTTPException(status_code=404, detail="Bot not found in this project")

    async def _audit(
        self,
        *,
        project_id: UUID,
        actor: User,
        action: str,
        entity_id: UUID,
        meta: dict[str, Any] | None = None,
    ) -> None:
        await self.audit.log(
            project_id=project_id,
            actor_id=actor.id,
            action=action,
            entity_type="broadcast",
            entity_id=entity_id,
            meta=meta,
        )

    @staticmethod
    def _ensure_can_manage(actor: User) -> None:
        if actor.role_name not in {
            RoleName.SUPER_ADMIN,
            RoleName.ADMIN,
            RoleName.MANAGER,
            RoleName.OPERATOR,
        }:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
