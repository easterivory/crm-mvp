from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload

from app.models.broadcast import Broadcast, BroadcastRecipient, BroadcastTemplate, BroadcastUpload
from app.models.chat import Chat
from app.models.lead import Lead
from app.repositories.base import BaseRepository


class BroadcastRepository(BaseRepository[Broadcast]):
    model = Broadcast

    async def list_by_project(
        self,
        project_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Broadcast]:
        result = await self.db.execute(
            select(Broadcast)
            .options(selectinload(Broadcast.created_by))
            .where(Broadcast.project_id == project_id)
            .order_by(Broadcast.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_project(self, project_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count(Broadcast.id)).where(Broadcast.project_id == project_id)
        )
        return result.scalar_one()

    async def get_in_project(
        self,
        broadcast_id: UUID,
        project_id: UUID,
    ) -> Optional[Broadcast]:
        result = await self.db.execute(
            select(Broadcast)
            .options(selectinload(Broadcast.created_by))
            .where(
                Broadcast.id == broadcast_id,
                Broadcast.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()

    async def update_in_project(
        self,
        broadcast_id: UUID,
        project_id: UUID,
        **values,
    ) -> Optional[Broadcast]:
        await self.db.execute(
            update(Broadcast)
            .where(Broadcast.id == broadcast_id, Broadcast.project_id == project_id)
            .values(**values)
        )
        return await self.get_in_project(broadcast_id, project_id)

    async def replace_recipients(
        self,
        broadcast_id: UUID,
        recipients: Sequence[tuple[UUID, UUID | None]],
    ) -> None:
        await self.db.execute(
            delete(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == broadcast_id)
        )
        for chat_id, lead_id in recipients:
            self.db.add(
                BroadcastRecipient(
                    broadcast_id=broadcast_id,
                    chat_id=chat_id,
                    lead_id=lead_id,
                    status="pending",
                )
            )
        await self.db.flush()

    async def list_templates_by_project(
        self,
        project_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BroadcastTemplate]:
        result = await self.db.execute(
            select(BroadcastTemplate)
            .options(selectinload(BroadcastTemplate.created_by))
            .where(BroadcastTemplate.project_id == project_id)
            .order_by(BroadcastTemplate.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_template_in_project(
        self,
        template_id: UUID,
        project_id: UUID,
    ) -> Optional[BroadcastTemplate]:
        result = await self.db.execute(
            select(BroadcastTemplate)
            .options(selectinload(BroadcastTemplate.created_by))
            .where(
                BroadcastTemplate.id == template_id,
                BroadcastTemplate.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_template(
        self,
        *,
        project_id: UUID,
        name: str,
        content_json: dict,
        created_by_user_id: UUID | None,
    ) -> BroadcastTemplate:
        template = BroadcastTemplate(
            project_id=project_id,
            name=name,
            content_json=content_json,
            created_by_user_id=created_by_user_id,
        )
        self.db.add(template)
        await self.db.flush()
        await self.db.refresh(template)
        return template

    async def update_template_in_project(
        self,
        template_id: UUID,
        project_id: UUID,
        **values,
    ) -> Optional[BroadcastTemplate]:
        await self.db.execute(
            update(BroadcastTemplate)
            .where(BroadcastTemplate.id == template_id, BroadcastTemplate.project_id == project_id)
            .values(**values)
        )
        return await self.get_template_in_project(template_id, project_id)

    async def delete_template_in_project(self, template_id: UUID, project_id: UUID) -> bool:
        result = await self.db.execute(
            delete(BroadcastTemplate).where(
                BroadcastTemplate.id == template_id,
                BroadcastTemplate.project_id == project_id,
            )
        )
        return bool(result.rowcount)

    async def create_upload(
        self,
        *,
        project_id: UUID,
        created_by_user_id: UUID | None,
        file_name: str,
        mime_type: str,
        file_size: int,
        media_type: str,
        storage_path: str,
        expires_at: datetime | None,
    ) -> BroadcastUpload:
        upload = BroadcastUpload(
            project_id=project_id,
            created_by_user_id=created_by_user_id,
            file_name=file_name,
            mime_type=mime_type,
            file_size=file_size,
            media_type=media_type,
            storage_path=storage_path,
            expires_at=expires_at,
        )
        self.db.add(upload)
        await self.db.flush()
        await self.db.refresh(upload)
        return upload

    async def get_upload_in_project(
        self,
        upload_id: UUID,
        project_id: UUID,
    ) -> Optional[BroadcastUpload]:
        result = await self.db.execute(
            select(BroadcastUpload).where(
                BroadcastUpload.id == upload_id,
                BroadcastUpload.project_id == project_id,
                BroadcastUpload.status.in_(("uploaded", "used")),
            )
        )
        return result.scalar_one_or_none()

    async def update_upload_path(
        self,
        upload_id: UUID,
        project_id: UUID,
        storage_path: str,
    ) -> Optional[BroadcastUpload]:
        await self.db.execute(
            update(BroadcastUpload)
            .where(BroadcastUpload.id == upload_id, BroadcastUpload.project_id == project_id)
            .values(storage_path=storage_path)
        )
        return await self.get_upload_in_project(upload_id, project_id)

    async def mark_upload_used(self, upload_id: UUID, project_id: UUID) -> None:
        await self.db.execute(
            update(BroadcastUpload)
            .where(BroadcastUpload.id == upload_id, BroadcastUpload.project_id == project_id)
            .values(status="used")
        )

    async def mark_expired_uploads(self, now: datetime) -> list[BroadcastUpload]:
        result = await self.db.execute(
            select(BroadcastUpload).where(
                BroadcastUpload.status == "uploaded",
                BroadcastUpload.expires_at.is_not(None),
                BroadcastUpload.expires_at <= now,
            )
        )
        uploads = list(result.scalars().all())
        if uploads:
            await self.db.execute(
                update(BroadcastUpload)
                .where(BroadcastUpload.id.in_([upload.id for upload in uploads]))
                .values(status="expired")
            )
        return uploads

    async def list_due_broadcasts(self, limit: int = 20) -> list[Broadcast]:
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(Broadcast)
            .where(
                Broadcast.status.in_(("processing", "scheduled")),
                (Broadcast.status == "processing")
                | ((Broadcast.status == "scheduled") & (Broadcast.scheduled_at <= now)),
            )
            .order_by(Broadcast.scheduled_at.asc().nullsfirst(), Broadcast.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_pending_recipients(
        self,
        broadcast_id: UUID,
        limit: int,
        max_attempts: int,
    ) -> list[BroadcastRecipient]:
        result = await self.db.execute(
            select(BroadcastRecipient)
            .where(
                BroadcastRecipient.broadcast_id == broadcast_id,
                BroadcastRecipient.status == "pending",
                BroadcastRecipient.attempts < max_attempts,
            )
            .order_by(BroadcastRecipient.created_at.asc(), BroadcastRecipient.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_pending_recipients(self, broadcast_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count(BroadcastRecipient.id)).where(
                BroadcastRecipient.broadcast_id == broadcast_id,
                BroadcastRecipient.status == "pending",
            )
        )
        return result.scalar_one()

    async def mark_recipient_sent(self, recipient_id: UUID) -> None:
        await self.db.execute(
            update(BroadcastRecipient)
            .where(BroadcastRecipient.id == recipient_id)
            .values(status="sent", sent_at=datetime.now(timezone.utc), last_error=None)
        )

    async def mark_recipient_failed(self, recipient_id: UUID, error: str) -> None:
        await self.db.execute(
            update(BroadcastRecipient)
            .where(BroadcastRecipient.id == recipient_id)
            .values(
                status="failed",
                attempts=BroadcastRecipient.attempts + 1,
                last_error=error[:1000],
            )
        )

    async def increment_progress_counts(
        self,
        broadcast_id: UUID,
        project_id: UUID,
        *,
        sent_delta: int = 0,
        failed_delta: int = 0,
    ) -> Optional[Broadcast]:
        values = {}
        if sent_delta:
            values["sent_count"] = Broadcast.sent_count + sent_delta
        if failed_delta:
            values["failed_count"] = Broadcast.failed_count + failed_delta
        if not values:
            return await self.get_in_project(broadcast_id, project_id)

        await self.db.execute(
            update(Broadcast)
            .where(Broadcast.id == broadcast_id, Broadcast.project_id == project_id)
            .values(**values)
        )
        return await self.get_in_project(broadcast_id, project_id)

    async def sync_progress_counts(
        self,
        broadcast_id: UUID,
        project_id: UUID,
    ) -> Optional[Broadcast]:
        counts = await self.status_counts(broadcast_id)
        await self.db.execute(
            update(Broadcast)
            .where(Broadcast.id == broadcast_id, Broadcast.project_id == project_id)
            .values(
                sent_count=counts.get("sent", 0),
                failed_count=counts.get("failed", 0),
            )
        )
        return await self.get_in_project(broadcast_id, project_id)

    async def mark_pending_skipped(self, broadcast_id: UUID, reason: str) -> None:
        await self.db.execute(
            update(BroadcastRecipient)
            .where(
                BroadcastRecipient.broadcast_id == broadcast_id,
                BroadcastRecipient.status == "pending",
            )
            .values(status="skipped", last_error=reason[:1000])
        )

    async def mark_recipient_error(
        self,
        recipient: BroadcastRecipient,
        error: str,
        *,
        max_attempts: int,
    ) -> None:
        attempts = recipient.attempts + 1
        await self.db.execute(
            update(BroadcastRecipient)
            .where(BroadcastRecipient.id == recipient.id)
            .values(
                status="failed" if attempts >= max_attempts else "pending",
                attempts=attempts,
                last_error=error[:1000],
            )
        )

    async def status_counts(self, broadcast_id: UUID) -> dict[str, int]:
        result = await self.db.execute(
            select(BroadcastRecipient.status, func.count(BroadcastRecipient.id))
            .where(BroadcastRecipient.broadcast_id == broadcast_id)
            .group_by(BroadcastRecipient.status)
        )
        return {str(status): int(count) for status, count in result.all()}

    async def error_examples(self, broadcast_id: UUID, limit: int = 5) -> list[str]:
        result = await self.db.execute(
            select(BroadcastRecipient.last_error)
            .where(
                BroadcastRecipient.broadcast_id == broadcast_id,
                BroadcastRecipient.last_error.is_not(None),
            )
            .order_by(BroadcastRecipient.created_at.desc())
            .limit(limit)
        )
        return [str(item) for item in result.scalars().all() if item]

    async def delivery_error_rows(self, broadcast_id: UUID) -> list[tuple[str, str, str]]:
        result = await self.db.execute(
            select(
                Chat.external_user_id,
                BroadcastRecipient.status,
                BroadcastRecipient.last_error,
            )
            .join(Chat, Chat.id == BroadcastRecipient.chat_id)
            .where(
                BroadcastRecipient.broadcast_id == broadcast_id,
                BroadcastRecipient.status.in_(("failed", "skipped")),
            )
            .order_by(BroadcastRecipient.created_at.asc(), BroadcastRecipient.id.asc())
        )
        return [
            (str(user_id), str(status), str(error or ""))
            for user_id, status, error in result.all()
        ]

    async def has_client_reply_after(
        self,
        broadcast_id: UUID,
        since: datetime,
    ) -> bool:
        result = await self.db.execute(
            select(func.count(Chat.id))
            .join(BroadcastRecipient, BroadcastRecipient.chat_id == Chat.id)
            .where(
                BroadcastRecipient.broadcast_id == broadcast_id,
                Chat.last_client_message_at.is_not(None),
                Chat.last_client_message_at > since,
            )
            .limit(1)
        )
        return result.scalar_one() > 0

    async def get_recipient_context(self, recipient: BroadcastRecipient):
        result = await self.db.execute(
            select(Chat, Lead)
            .options(selectinload(Lead.status))
            .outerjoin(Lead, Lead.chat_id == Chat.id)
            .where(Chat.id == recipient.chat_id)
        )
        return result.one_or_none()
