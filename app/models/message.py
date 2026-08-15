from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import MessageType, SenderType
from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class Message(Base, UUIDPrimaryKey, TimestampMixin):
    """
    A single message inside a Chat.

    external_message_id — Telegram's own message id.
    Deduplicated via a PARTIAL UNIQUE index (only when NOT NULL),
    so system messages without an external id do not conflict.

    body is NULLABLE to support media messages (images, stickers, etc.)
    that have no text content.
    """
    __tablename__ = "messages"
    __table_args__ = (
        Index(
            "ix_messages_tracking_link_created_at",
            "tracking_link_id",
            "created_at",
        ),
    )

    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id"), nullable=False, index=True
    )
    external_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    # text / image / video / audio / file / sticker / system
    message_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=MessageType.TEXT, server_default=MessageType.TEXT
    )
    # user / manager / system
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    sender_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    operator_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tracking_link_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tracking_links.id", ondelete="SET NULL"),
        nullable=True,
    )
    # NULL for media messages without a caption
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    translated_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    telegram_file_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, index=True)
    file_unique_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    media_group_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reply_to_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    edited_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    raw_payload_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    funnel_processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Relationships
    chat: Mapped[Chat] = relationship("Chat", back_populates="messages")
    sender: Mapped[Optional[User]] = relationship(
        "User", back_populates="sent_messages", foreign_keys=[sender_id]
    )
    operator: Mapped[Optional[User]] = relationship(
        "User", back_populates="operator_messages", foreign_keys=[operator_id]
    )

    # Partial unique index — declared via DDL in the Alembic migration.
    # UNIQUE(chat_id, external_message_id) WHERE external_message_id IS NOT NULL
    # Cannot be expressed purely through __table_args__ Index; must be in migration.

    @property
    def buttons(self) -> list[str]:
        payload = self.raw_payload_json if isinstance(self.raw_payload_json, dict) else {}
        reply_markup = payload.get("reply_markup")
        if not isinstance(reply_markup, dict):
            telegram_result = payload.get("telegram_result")
            reply_markup = (
                telegram_result.get("reply_markup")
                if isinstance(telegram_result, dict)
                else None
            )
        if not isinstance(reply_markup, dict):
            return []

        labels: list[str] = []
        rows = reply_markup.get("inline_keyboard") or reply_markup.get("keyboard") or []
        if not isinstance(rows, list):
            return labels
        for row in rows:
            if not isinstance(row, list):
                continue
            for button in row:
                if not isinstance(button, dict):
                    continue
                label = str(button.get("text") or "").strip()
                if label:
                    labels.append(label)
        return labels


class MessageUpload(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "message_uploads"
    __table_args__ = (
        Index("ix_message_uploads_project_id", "project_id"),
        Index("ix_message_uploads_chat_id", "chat_id"),
        Index("ix_message_uploads_created_by_user_id", "created_by_user_id"),
        Index("ix_message_uploads_status", "status"),
        Index("ix_message_uploads_expires_at", "expires_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id"), nullable=False
    )
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str] = mapped_column(String(30), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="uploaded",
        server_default="uploaded",
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id"), nullable=True
    )

    chat: Mapped[Chat] = relationship("Chat")
    created_by: Mapped[Optional[User]] = relationship("User")
    sent_message: Mapped[Optional[Message]] = relationship("Message")
