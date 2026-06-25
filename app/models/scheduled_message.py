from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKey


class ScheduledMessage(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    """Persistent operator message waiting for delivery by the worker."""

    __tablename__ = "scheduled_messages"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','sent','failed','cancelled')",
            name="ck_scheduled_messages_status",
        ),
        CheckConstraint(
            "media_type IN ('text','photo','video','voice','video_note','document')",
            name="ck_scheduled_messages_media_type",
        ),
        Index("ix_scheduled_messages_status_scheduled_at", "status", "scheduled_at"),
        Index("ix_scheduled_messages_chat_id", "chat_id"),
        Index("ix_scheduled_messages_project_id", "project_id"),
        Index("ix_scheduled_messages_created_by_user_id", "created_by_user_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    media_type: Mapped[str] = mapped_column(String(30), nullable=False, default="text", server_default="text")
    file_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    storage_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    auto_translate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
