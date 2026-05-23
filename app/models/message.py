from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Index, Integer, String, Text
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
    # NULL for media messages without a caption
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    telegram_file_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, index=True)
    file_unique_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    media_group_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    raw_payload_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Relationships
    chat: Mapped[Chat] = relationship("Chat", back_populates="messages")
    sender: Mapped[Optional[User]] = relationship(
        "User", back_populates="sent_messages", foreign_keys=[sender_id]
    )

    # Partial unique index — declared via DDL in the Alembic migration.
    # UNIQUE(chat_id, external_message_id) WHERE external_message_id IS NOT NULL
    # Cannot be expressed purely through __table_args__ Index; must be in migration.
