from __future__ import annotations

import asyncio
import csv
import io
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
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
    BroadcastDeliveryAnalytics,
    BroadcastErrorLogRow,
    BroadcastOut,
    BroadcastReport,
    BroadcastRecipientDeliveryOut,
    BroadcastScheduleRequest,
    BroadcastTemplateCreate,
    BroadcastTemplateOut,
    BroadcastTemplateUpdate,
    BroadcastUpdate,
    BroadcastUploadOut,
    SendNowRequest,
)
from app.schemas.message import MessageCreate
from app.services.audience_filter_service import AudienceFilterService
from app.services.audit_service import AuditService
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.message_service import MessageService
from app.services.telegram_sender import TelegramSenderService


ALLOWED_BROADCAST_MEDIA: dict[str, str] = {
    "image/jpeg": "photo",
    "image/png": "photo",
    "image/webp": "photo",
    "video/mp4": "video",
    "video/quicktime": "video",
    "video/webm": "video",
    "video/x-matroska": "video",
    "video/x-msvideo": "video",
    "video/mpeg": "video",
    "video/3gpp": "video",
    "audio/ogg": "voice",
    "audio/mpeg": "voice",
    "audio/mp4": "voice",
    "audio/webm": "voice",
    "audio/wav": "voice",
    "application/pdf": "document",
    "text/plain": "document",
    "application/msword": "document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
}

DANGEROUS_EXTENSIONS = {
    ".exe",
    ".bat",
    ".cmd",
    ".com",
    ".scr",
    ".js",
    ".jar",
    ".sh",
    ".php",
    ".py",
}


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
        sent_count = counts.get("sent", 0)
        failed_count = counts.get("failed", 0)
        return BroadcastReport(
            status=broadcast.status,
            total_recipients=broadcast.total_recipients or sum(counts.values()),
            sent_count=sent_count,
            failed_count=failed_count,
            pending=counts.get("pending", 0),
            sent=sent_count,
            failed=failed_count,
            skipped=counts.get("skipped", 0),
            cancelled=counts.get("skipped", 0) if broadcast.status == "cancelled" else 0,
            started_at=broadcast.started_at,
            finished_at=broadcast.sent_at,
            error_examples=await self.repo.error_examples(broadcast.id),
        )

    async def delivery_analytics(
        self,
        broadcast_id: UUID,
        project_id: UUID,
    ) -> BroadcastDeliveryAnalytics:
        broadcast = await self._get_or_404(broadcast_id, project_id)
        rows = await self.repo.delivery_analytics_rows(broadcast.id)
        recipients: list[BroadcastRecipientDeliveryOut] = []
        delivered = 0
        read = 0
        replied = 0
        pending = 0
        failed = 0
        skipped = 0

        for recipient, chat, lead_name in rows:
            is_delivered = recipient.status == "sent"
            is_read = bool(is_delivered and chat.is_read)
            has_reply = bool(
                is_delivered
                and recipient.sent_at is not None
                and chat.last_client_message_at is not None
                and chat.last_client_message_at > recipient.sent_at
            )
            if is_delivered:
                delivered += 1
            elif recipient.status == "pending":
                pending += 1
            elif recipient.status == "failed":
                failed += 1
            elif recipient.status == "skipped":
                skipped += 1
            if is_read:
                read += 1
            if has_reply:
                replied += 1

            recipients.append(
                BroadcastRecipientDeliveryOut(
                    id=recipient.id,
                    chat_id=recipient.chat_id,
                    lead_id=recipient.lead_id,
                    external_chat_id=chat.external_chat_id,
                    external_user_id=chat.external_user_id,
                    lead_name=lead_name,
                    status=recipient.status,
                    attempts=recipient.attempts,
                    last_error=recipient.last_error,
                    sent_at=recipient.sent_at,
                    is_read=is_read,
                    replied=has_reply,
                    last_client_message_at=chat.last_client_message_at,
                )
            )

        return BroadcastDeliveryAnalytics(
            broadcast_id=broadcast.id,
            total_recipients=broadcast.total_recipients or len(recipients),
            delivered=delivered,
            read=read,
            replied=replied,
            pending=pending,
            failed=failed,
            skipped=skipped,
            recipients=recipients,
        )

    async def error_log(
        self,
        broadcast_id: UUID,
        project_id: UUID,
        limit: int = 200,
    ) -> list[BroadcastErrorLogRow]:
        broadcast = await self._get_or_404(broadcast_id, project_id)
        rows = await self.repo.error_log_rows(broadcast.id, limit=limit)
        return [
            BroadcastErrorLogRow(
                id=recipient.id,
                chat_id=recipient.chat_id,
                lead_id=recipient.lead_id,
                external_chat_id=chat.external_chat_id,
                external_user_id=chat.external_user_id,
                lead_name=lead_name,
                status=recipient.status,
                attempts=recipient.attempts,
                error=recipient.last_error or "",
                created_at=recipient.created_at,
                sent_at=recipient.sent_at,
            )
            for recipient, chat, lead_name in rows
        ]

    async def error_csv(self, broadcast_id: UUID, project_id: UUID) -> str:
        await self._get_or_404(broadcast_id, project_id)
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["telegram_user_id", "status", "error"])
        for user_id, status, error in await self.repo.delivery_error_rows(broadcast_id):
            writer.writerow([user_id, status, error])
        return output.getvalue()

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
        if self._content_has_media(data.content_json):
            raise HTTPException(status_code=422, detail="Шаблоны поддерживают только текстовый контент.")
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
            if self._content_has_media(values["content_json"]):
                raise HTTPException(status_code=422, detail="Шаблоны поддерживают только текстовый контент.")
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

    async def delete_broadcast(
        self,
        *,
        broadcast_id: UUID,
        actor: User,
        project_id: UUID,
    ) -> None:
        self._ensure_can_delete(actor)
        deleted = await self.repo.soft_delete_in_project(broadcast_id, project_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Broadcast not found")
        await self.repo.mark_pending_skipped(broadcast_id, "Broadcast archived")
        await self._audit(
            project_id=project_id,
            actor=actor,
            action="broadcast.archived",
            entity_id=broadcast_id,
        )

    async def permanently_delete_broadcast(
        self,
        *,
        broadcast_id: UUID,
        actor: User,
        project_id: UUID,
    ) -> None:
        self._ensure_can_delete(actor)
        broadcast = await self.repo.get_any_in_project(broadcast_id, project_id)
        if broadcast is None:
            raise HTTPException(status_code=404, detail="Broadcast not found")
        if broadcast.status in {"scheduled", "processing", "paused"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cancel or finish broadcast before permanent deletion",
            )
        await self._audit(
            project_id=project_id,
            actor=actor,
            action="broadcast.permanently_deleted",
            entity_id=broadcast_id,
            meta={"name": broadcast.name, "status": broadcast.status},
        )
        deleted = await self.repo.hard_delete_in_project(broadcast_id, project_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Broadcast not found")

    async def upload_media(
        self,
        *,
        actor: User,
        project_id: UUID,
        file: UploadFile,
        media_type: str | None = None,
        persistent: bool = False,
    ) -> BroadcastUploadOut:
        self._ensure_can_manage(actor)
        file_name = os.path.basename(file.filename or "upload")
        suffix = Path(file_name).suffix.lower()
        if suffix in DANGEROUS_EXTENSIONS:
            raise HTTPException(status_code=422, detail="Этот тип файла нельзя загружать.")

        mime_type = file.content_type or "application/octet-stream"
        resolved_media_type = self._resolve_upload_media_type(mime_type, media_type)
        if resolved_media_type is None:
            raise HTTPException(status_code=422, detail="Неподдерживаемый тип файла.")

        max_size = self._max_upload_size(resolved_media_type)
        storage_root = Path(settings.BROADCAST_UPLOAD_STORAGE_PATH)
        storage_root.mkdir(parents=True, exist_ok=True)
        project_dir = storage_root / str(project_id)
        project_dir.mkdir(parents=True, exist_ok=True)

        upload_id = UUID(int=0)
        temp_path = project_dir / f".tmp_{uuid4().hex}"
        size = 0
        try:
            with temp_path.open("wb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_size:
                        raise HTTPException(status_code=413, detail="Файл слишком большой.")
                    output.write(chunk)
            expires_at = None if persistent else (
                datetime.now(timezone.utc) + timedelta(hours=settings.BROADCAST_UPLOAD_TTL_HOURS)
            )
            upload = await self.repo.create_upload(
                project_id=project_id,
                created_by_user_id=actor.id,
                file_name=file_name,
                mime_type=mime_type,
                file_size=size,
                media_type=resolved_media_type,
                storage_path="",
                expires_at=expires_at,
            )
            upload_id = upload.id
            final_path = project_dir / f"{upload.id.hex}{suffix or '.bin'}"
            temp_path.replace(final_path)
            upload = await self.repo.update_upload_path(upload.id, project_id, str(final_path))
            assert upload is not None
            return BroadcastUploadOut(
                upload_id=upload.id,
                project_id=upload.project_id,
                file_name=upload.file_name,
                mime_type=upload.mime_type,
                file_size=upload.file_size,
                media_type=upload.media_type,
                status=upload.status,
                expires_at=upload.expires_at,
            )
        finally:
            if temp_path.exists() and upload_id.int == 0:
                temp_path.unlink(missing_ok=True)

    async def cleanup_expired_uploads(self) -> int:
        uploads = await self.repo.mark_expired_uploads(datetime.now(timezone.utc))
        removed = 0
        for upload in uploads:
            try:
                path = Path(upload.storage_path)
                if path.exists():
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        return removed

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
            snippet_id=data.snippet_id,
            media_type=data.media_type,
            file_id=data.file_id,
            trigger_funnel_id=data.trigger_funnel_id,
            stop_on_reply=data.stop_on_reply,
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
        if broadcast.status not in {"draft", "scheduled"}:
            raise HTTPException(status_code=422, detail="Broadcast cannot be edited in current status")
        values = data.model_dump(exclude_unset=True)
        if "bot_id" in values and values["bot_id"] is not None:
            await self._ensure_bot(project_id, values["bot_id"])
        if values:
            values["status"] = broadcast.status
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
            status="processing",
            schedule_type="now",
            scheduled_at=None,
            audience_count=audience.count,
            total_recipients=audience.count,
            sent_count=0,
            failed_count=0,
            started_at=datetime.now(timezone.utc),
            sent_at=None,
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
            total_recipients=audience.count,
            sent_count=0,
            failed_count=0,
            started_at=None,
            sent_at=None,
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
        if broadcast.status not in {"scheduled", "processing", "paused", "draft"}:
            raise HTTPException(status_code=422, detail="Broadcast cannot be cancelled")
        updated = await self.repo.update_in_project(
            broadcast_id,
            project_id,
            status="cancelled",
        )
        await self.repo.mark_pending_skipped(broadcast_id, "Broadcast cancelled")
        updated = await self.repo.sync_progress_counts(broadcast_id, project_id) or updated
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
        if broadcast.status != "processing":
            raise HTTPException(status_code=422, detail="Only processing broadcasts can be paused")
        updated = await self.repo.update_in_project(broadcast_id, project_id, status="paused")
        updated = await self.repo.sync_progress_counts(broadcast_id, project_id) or updated
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
        updated = await self.repo.update_in_project(
            broadcast_id,
            project_id,
            status="processing",
            started_at=broadcast.started_at or datetime.now(timezone.utc),
        )
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
                    status="processing",
                    started_at=datetime.now(timezone.utc),
                )
            if broadcast is None or broadcast.status != "processing":
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
            await self.repo.update_in_project(
                broadcast.id,
                broadcast.project_id,
                status="completed",
                sent_count=counts.get("sent", 0),
                failed_count=counts.get("failed", 0),
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
                await self.repo.increment_progress_counts(
                    broadcast.id,
                    broadcast.project_id,
                    sent_delta=1,
                )
                sent += 1
            except Exception as exc:
                await self.repo.mark_recipient_error(
                    recipient,
                    str(exc),
                    max_attempts=settings.BROADCAST_MAX_ATTEMPTS,
                )
                await self.repo.sync_progress_counts(broadcast.id, broadcast.project_id)
            if settings.BROADCAST_SEND_INTERVAL_MS > 0:
                await asyncio.sleep(settings.BROADCAST_SEND_INTERVAL_MS / 1000)

        if await self.repo.count_pending_recipients(broadcast.id) == 0:
            counts = await self.repo.status_counts(broadcast.id)
            await self.repo.update_in_project(
                broadcast.id,
                broadcast.project_id,
                status="completed",
                sent_count=counts.get("sent", 0),
                failed_count=counts.get("failed", 0),
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
            reply_markup = self._reply_markup_for_buttons(
                broadcast=broadcast,
                message_index=message_index,
                buttons=self._normalize_buttons(message.get("buttons") or []),
            )
            message_type = self._broadcast_message_type(message)
            if message_type == MessageType.TEXT:
                text = await self._render_text(str(message.get("text") or ""), broadcast, chat, lead)
                if not text.strip():
                    continue
                sent = await self.telegram_sender.send_message(
                    project_id=broadcast.project_id,
                    bot_id=broadcast.bot_id,
                    external_chat_id=chat.external_chat_id,
                    text=text,
                    reply_markup=reply_markup,
                )
                if not sent:
                    raise RuntimeError("Telegram sendMessage failed")
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
                continue

            media_result = await self._send_broadcast_media(
                broadcast=broadcast,
                chat=chat,
                lead=lead,
                message=message,
                message_type=message_type,
                reply_markup=reply_markup,
            )
            await service.create_message(
                chat_id=chat_id,
                project_id=broadcast.project_id,
                data=MessageCreate(
                    message_type=message_type,
                    sender_type=SenderType.BOT,
                    body=None,
                    caption=media_result["caption"],
                    telegram_file_id=media_result["telegram_file_id"],
                    file_name=media_result["file_name"],
                    mime_type=media_result["mime_type"],
                    file_size=media_result["file_size"],
                    raw_payload_json=media_result["raw_payload_json"],
                    reply_markup=reply_markup,
                ),
                send_to_telegram=False,
            )
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
        if broadcast.status in {"processing", "paused", "completed", "cancelled"}:
            raise HTTPException(status_code=422, detail="Broadcast cannot be sent in current status")

    def _validate_content(self, content: dict[str, Any]) -> None:
        messages = self._content_messages(content)
        has_sendable_content = False
        for message in messages:
            message_type = self._broadcast_message_type(message)
            if message_type == MessageType.TEXT:
                if str(message.get("text") or "").strip():
                    has_sendable_content = True
                continue
            media = message.get("media")
            if not isinstance(media, dict):
                raise HTTPException(status_code=422, detail="Media message requires media metadata")
            if not media.get("upload_id") and not media.get("telegram_file_id"):
                raise HTTPException(status_code=422, detail="Media message requires upload_id or telegram_file_id")
            has_sendable_content = True
        if not has_sendable_content:
            raise HTTPException(status_code=422, detail="Broadcast content is empty")
        action = content.get("after_send_action") if isinstance(content, dict) else None
        if isinstance(action, dict) and action.get("type") == "start_funnel" and not action.get("funnel_id"):
            raise HTTPException(status_code=422, detail="start_funnel action requires funnel_id")

    async def _send_broadcast_media(
        self,
        *,
        broadcast: Broadcast,
        chat: Chat,
        lead: Lead | None,
        message: dict[str, Any],
        message_type: str,
        reply_markup: dict | None,
    ) -> dict[str, Any]:
        media = message.get("media")
        if not isinstance(media, dict):
            raise RuntimeError("Media message is missing media metadata")

        source = str(media.get("source") or "upload")
        media_file: str | Path
        upload_id: UUID | None = None
        file_name = str(media.get("file_name") or "").strip() or None
        mime_type = str(media.get("mime_type") or "").strip() or None
        file_size = self._safe_int(media.get("file_size"))
        if source == "telegram_file_id":
            telegram_file_id = str(media.get("telegram_file_id") or "").strip()
            if not telegram_file_id:
                raise RuntimeError("Media message is missing telegram_file_id")
            media_file = telegram_file_id
        else:
            try:
                upload_id = UUID(str(media.get("upload_id") or ""))
            except (TypeError, ValueError) as exc:
                raise RuntimeError("Media message has invalid upload_id") from exc
            upload = await self.repo.get_upload_in_project(upload_id, broadcast.project_id)
            if upload is None:
                raise RuntimeError("Broadcast upload is missing or unavailable")
            if upload.media_type != message_type:
                raise RuntimeError("Broadcast upload media type does not match message type")
            if (
                upload.status == "uploaded"
                and upload.expires_at is not None
                and upload.expires_at <= datetime.now(timezone.utc)
            ):
                raise RuntimeError("Broadcast upload has expired")
            path = Path(upload.storage_path)
            if not upload.storage_path or not path.exists():
                raise RuntimeError("Broadcast upload file is missing from private storage")
            media_file = path
            file_name = upload.file_name
            mime_type = upload.mime_type
            file_size = upload.file_size

        raw_caption = message.get("caption")
        if raw_caption is None:
            raw_caption = message.get("text")
        caption = await self._render_text(str(raw_caption or ""), broadcast, chat, lead)

        if message_type == MessageType.PHOTO:
            telegram_result = await self.telegram_sender.send_photo(
                project_id=broadcast.project_id,
                bot_id=broadcast.bot_id,
                external_chat_id=chat.external_chat_id,
                photo=media_file,
                caption=caption,
                reply_markup=reply_markup,
                file_name=file_name,
                mime_type=mime_type,
            )
        elif message_type == MessageType.VIDEO:
            telegram_result = await self.telegram_sender.send_video(
                project_id=broadcast.project_id,
                bot_id=broadcast.bot_id,
                external_chat_id=chat.external_chat_id,
                video=media_file,
                caption=caption,
                reply_markup=reply_markup,
                file_name=file_name,
                mime_type=mime_type,
            )
        elif message_type == MessageType.VOICE:
            telegram_result = await self.telegram_sender.send_voice(
                project_id=broadcast.project_id,
                bot_id=broadcast.bot_id,
                external_chat_id=chat.external_chat_id,
                voice=media_file,
                caption=caption,
                reply_markup=reply_markup,
                file_name=file_name,
                mime_type=mime_type,
            )
        elif message_type == MessageType.VIDEO_NOTE:
            telegram_result = await self.telegram_sender.send_video_note(
                project_id=broadcast.project_id,
                bot_id=broadcast.bot_id,
                external_chat_id=chat.external_chat_id,
                video_note=media_file,
                reply_markup=reply_markup,
                file_name=file_name,
                mime_type=mime_type,
            )
        elif message_type == MessageType.DOCUMENT:
            telegram_result = await self.telegram_sender.send_document(
                project_id=broadcast.project_id,
                bot_id=broadcast.bot_id,
                external_chat_id=chat.external_chat_id,
                document=media_file,
                caption=caption,
                reply_markup=reply_markup,
                file_name=file_name,
                mime_type=mime_type,
            )
        else:
            raise RuntimeError("Unsupported broadcast media type")

        if not telegram_result:
            raise RuntimeError(f"Telegram send{message_type.title()} failed")

        if upload_id is not None:
            await self.repo.mark_upload_used(upload_id, broadcast.project_id)

        return {
            "caption": None if message_type == MessageType.VIDEO_NOTE else caption or None,
            "telegram_file_id": self._extract_telegram_file_id(message_type, telegram_result)
            or (str(media.get("telegram_file_id") or "").strip() or None),
            "file_name": file_name,
            "mime_type": mime_type,
            "file_size": file_size,
            "raw_payload_json": {"telegram_result": telegram_result, "broadcast_media": media},
        }

    @staticmethod
    def _content_messages(content: dict[str, Any]) -> list[dict[str, Any]]:
        raw_messages = content.get("messages") if isinstance(content, dict) else None
        if isinstance(raw_messages, list):
            return [item for item in raw_messages if isinstance(item, dict)]
        text = content.get("text") if isinstance(content, dict) else None
        return [{"type": "text", "text": text or ""}]

    @staticmethod
    def _content_has_media(content: dict[str, Any]) -> bool:
        return any(
            BroadcastService._broadcast_message_type(message)
            in {
                MessageType.PHOTO,
                MessageType.VIDEO,
                MessageType.VOICE,
                MessageType.VIDEO_NOTE,
                MessageType.DOCUMENT,
            }
            for message in BroadcastService._content_messages(content)
        )

    @staticmethod
    def _broadcast_message_type(message: dict[str, Any]) -> str:
        message_type = str(message.get("type") or MessageType.TEXT).strip().lower()
        if message_type in {
            MessageType.PHOTO,
            MessageType.VIDEO,
            MessageType.VOICE,
            MessageType.VIDEO_NOTE,
            MessageType.DOCUMENT,
        }:
            return message_type
        return MessageType.TEXT

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_telegram_file_id(message_type: str, result: dict[str, Any]) -> str | None:
        if message_type == MessageType.PHOTO:
            photos = result.get("photo")
            if isinstance(photos, list) and photos:
                largest = photos[-1]
                if isinstance(largest, dict):
                    return largest.get("file_id")
            return None
        media_payload = result.get(message_type)
        if isinstance(media_payload, dict):
            return media_payload.get("file_id")
        return None

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
        if broadcast.trigger_funnel_id is not None:
            await self._start_funnel_for_chat(
                project_id=broadcast.project_id,
                bot_id=broadcast.bot_id,
                chat_id=chat.id,
                funnel_id=broadcast.trigger_funnel_id,
                funnel_version_id=None,
                mode="skip_if_active",
                source="campaign_trigger",
                broadcast_id=broadcast.id,
            )
            return
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

    @staticmethod
    def _max_upload_size(media_type: str) -> int:
        if media_type == "photo":
            return settings.BROADCAST_PHOTO_MAX_BYTES
        if media_type in {"video", "video_note"}:
            return settings.BROADCAST_VIDEO_MAX_BYTES
        return settings.BROADCAST_DOCUMENT_MAX_BYTES

    @staticmethod
    def _resolve_upload_media_type(mime_type: str, requested_type: str | None) -> str | None:
        if requested_type is None:
            return ALLOWED_BROADCAST_MEDIA.get(mime_type)

        normalized = requested_type.strip().lower()
        if normalized not in {"photo", "video", "voice", "video_note", "document"}:
            raise HTTPException(status_code=422, detail="Неподдерживаемый способ отправки файла.")
        if normalized == "document":
            return normalized
        if normalized == "photo" and mime_type.startswith("image/"):
            return normalized
        if normalized in {"video", "video_note"} and mime_type.startswith("video/"):
            return normalized
        if normalized == "voice" and mime_type.startswith("audio/"):
            return normalized
        raise HTTPException(status_code=422, detail="Тип файла не соответствует выбранному способу отправки.")

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

    @staticmethod
    def _ensure_can_delete(actor: User) -> None:
        BroadcastService._ensure_can_manage(actor)
        if actor.role_name == RoleName.MANAGER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Managers cannot delete broadcasts",
            )
