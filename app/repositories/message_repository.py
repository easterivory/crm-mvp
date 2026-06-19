from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import extract, func, select, update
from sqlalchemy.orm import aliased

from app.core.constants import SenderType
from app.models.chat import Chat
from app.models.message import Message, MessageUpload
from app.repositories.base import BaseRepository


class MessageRepository(BaseRepository[Message]):
    model = Message

    async def list_by_chat(
        self,
        chat_id: UUID,
        limit: int = 50,
        offset: int = 0,
        since: Optional[datetime] = None,
    ) -> list[Message]:
        stmt = select(Message).where(Message.chat_id == chat_id)
        if since is not None:
            stmt = stmt.where(Message.created_at >= since)
        stmt = (
            stmt.order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        rows = list(result.scalars().all())
        return sorted(rows, key=self._chronological_message_key)

    @staticmethod
    def _chronological_message_key(message: Message) -> tuple:
        return (
            message.created_at,
            *MessageRepository._external_message_order(message.external_message_id),
            str(message.id),
        )

    @staticmethod
    def _external_message_order(value: str | None) -> tuple[int, int, str]:
        raw_value = (value or "").strip()
        if raw_value.isdigit():
            return (0, int(raw_value), "")
        return (1, 0, raw_value)

    async def count_by_chat(
        self,
        chat_id: UUID,
        since: Optional[datetime] = None,
    ) -> int:
        stmt = select(func.count(Message.id)).where(Message.chat_id == chat_id)
        if since is not None:
            stmt = stmt.where(Message.created_at >= since)
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def get_first_user_message(self, chat_id: UUID) -> Optional[Message]:
        result = await self.db.execute(
            select(Message)
            .where(Message.chat_id == chat_id, Message.sender_type == "user")
            .order_by(Message.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_first_manager_reply(self, chat_id: UUID) -> Optional[Message]:
        result = await self.db.execute(
            select(Message)
            .where(Message.chat_id == chat_id, Message.sender_type == "manager")
            .order_by(Message.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_first_response_time(self, chat_id: UUID) -> Optional[float]:
        first_user_at = (
            select(func.min(Message.created_at))
            .where(
                Message.chat_id == chat_id,
                Message.sender_type == SenderType.USER,
            )
            .scalar_subquery()
        )
        first_manager_reply_at = (
            select(func.min(Message.created_at))
            .where(
                Message.chat_id == chat_id,
                Message.sender_type == SenderType.MANAGER,
                Message.created_at > first_user_at,
            )
            .scalar_subquery()
        )

        result = await self.db.execute(
            select(extract("epoch", first_manager_reply_at - first_user_at)).where(
                first_user_at.is_not(None),
                first_manager_reply_at.is_not(None),
            )
        )
        value = result.scalar_one_or_none()
        return float(value) if value is not None else None

    async def avg_response_seconds(self, chat_id: UUID) -> Optional[float]:
        user_message = aliased(Message)
        manager_message = aliased(Message)

        next_manager_reply_at = (
            select(func.min(manager_message.created_at))
            .where(
                manager_message.chat_id == user_message.chat_id,
                manager_message.sender_type == SenderType.MANAGER,
                manager_message.created_at > user_message.created_at,
            )
            .correlate(user_message)
            .scalar_subquery()
        )

        result = await self.db.execute(
            select(
                func.avg(extract("epoch", next_manager_reply_at - user_message.created_at))
            ).where(
                user_message.chat_id == chat_id,
                user_message.sender_type == SenderType.USER,
                next_manager_reply_at.is_not(None),
            )
        )
        value = result.scalar_one_or_none()
        return float(value) if value is not None else None

    async def avg_response_seconds_for_project_date(
        self,
        project_id: UUID,
        target_date: date,
    ) -> Optional[float]:
        start_at = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
        end_at = start_at + timedelta(days=1)

        user_message = aliased(Message)
        manager_message = aliased(Message)

        next_manager_reply_at = (
            select(func.min(manager_message.created_at))
            .where(
                manager_message.chat_id == user_message.chat_id,
                manager_message.sender_type == SenderType.MANAGER,
                manager_message.created_at > user_message.created_at,
            )
            .correlate(user_message)
            .scalar_subquery()
        )

        result = await self.db.execute(
            select(
                func.avg(extract("epoch", next_manager_reply_at - user_message.created_at))
            )
            .join(Chat, Chat.id == user_message.chat_id)
            .where(
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                user_message.sender_type == SenderType.USER,
                user_message.created_at >= start_at,
                user_message.created_at < end_at,
                next_manager_reply_at.is_not(None),
            )
        )
        value = result.scalar_one_or_none()
        return float(value) if value is not None else None

    async def get_by_external_id(
        self, chat_id: UUID, external_message_id: str
    ) -> Optional[Message]:
        result = await self.db.execute(
            select(Message).where(
                Message.chat_id == chat_id,
                Message.external_message_id == external_message_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_message(
        self,
        *,
        chat_id: UUID,
        external_message_id: str | None,
        message_type: str,
        sender_type: str,
        sender_id: UUID | None,
        operator_id: UUID | None,
        body: str | None,
        translated_text: str | None,
        original_text: str | None,
        caption: str | None,
        telegram_file_id: str | None,
        file_unique_id: str | None,
        file_name: str | None,
        mime_type: str | None,
        file_size: int | None,
        media_group_id: str | None,
        raw_payload_json: dict | None,
    ) -> Message:
        return await self.create(
            chat_id=chat_id,
            external_message_id=external_message_id,
            message_type=message_type,
            sender_type=sender_type,
            sender_id=sender_id,
            operator_id=operator_id,
            body=body,
            translated_text=translated_text,
            original_text=original_text,
            caption=caption,
            telegram_file_id=telegram_file_id,
            file_unique_id=file_unique_id,
            file_name=file_name,
            mime_type=mime_type,
            file_size=file_size,
            media_group_id=media_group_id,
            raw_payload_json=raw_payload_json,
        )

    async def get_by_id_in_project(
        self,
        message_id: UUID,
        project_id: UUID,
    ) -> Optional[Message]:
        result = await self.db.execute(
            select(Message)
            .join(Chat, Chat.id == Message.chat_id)
            .where(
                Message.id == message_id,
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def create_upload(
        self,
        *,
        project_id: UUID,
        chat_id: UUID,
        created_by_user_id: UUID | None,
        file_name: str,
        mime_type: str,
        file_size: int,
        media_type: str,
        storage_path: str,
        expires_at: datetime | None,
    ) -> MessageUpload:
        upload = MessageUpload(
            project_id=project_id,
            chat_id=chat_id,
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

    async def get_upload_for_send(
        self,
        *,
        upload_id: UUID,
        chat_id: UUID,
        project_id: UUID,
    ) -> Optional[MessageUpload]:
        result = await self.db.execute(
            select(MessageUpload).where(
                MessageUpload.id == upload_id,
                MessageUpload.chat_id == chat_id,
                MessageUpload.project_id == project_id,
                MessageUpload.status == "uploaded",
            )
        )
        return result.scalar_one_or_none()

    async def update_upload_path(
        self,
        upload_id: UUID,
        project_id: UUID,
        storage_path: str,
    ) -> Optional[MessageUpload]:
        await self.db.execute(
            update(MessageUpload)
            .where(MessageUpload.id == upload_id, MessageUpload.project_id == project_id)
            .values(storage_path=storage_path)
        )
        result = await self.db.execute(
            select(MessageUpload).where(
                MessageUpload.id == upload_id,
                MessageUpload.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()

    async def mark_upload_sent(
        self,
        upload_id: UUID,
        project_id: UUID,
        message_id: UUID,
    ) -> None:
        await self.db.execute(
            update(MessageUpload)
            .where(MessageUpload.id == upload_id, MessageUpload.project_id == project_id)
            .values(status="sent", sent_message_id=message_id)
        )

    async def mark_upload_failed(
        self,
        upload_id: UUID,
        project_id: UUID,
    ) -> None:
        await self.db.execute(
            update(MessageUpload)
            .where(MessageUpload.id == upload_id, MessageUpload.project_id == project_id)
            .values(status="failed")
        )

    async def mark_expired_uploads(self, now: datetime) -> list[MessageUpload]:
        result = await self.db.execute(
            select(MessageUpload).where(
                MessageUpload.status == "uploaded",
                MessageUpload.expires_at.is_not(None),
                MessageUpload.expires_at <= now,
            )
        )
        uploads = list(result.scalars().all())
        if uploads:
            await self.db.execute(
                update(MessageUpload)
                .where(MessageUpload.id.in_([upload.id for upload in uploads]))
                .values(status="expired")
            )
        return uploads
