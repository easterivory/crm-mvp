from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UpdatedAtMixin,
    UUIDPrimaryKey,
)


class Chat(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin, SoftDeleteMixin):
    """
    Represents a Telegram dialog.
    Business data lives in Lead; this table stores the raw channel data.

    Computed fields (never stored):
      - unread     = last_message_at > last_read_at (OR last_read_at IS NULL)
      - unanswered = last_user_message_at > last_manager_reply_at (OR last_manager_reply_at IS NULL)
      - is_red     = unanswered AND now() - last_user_message_at > project.sla_threshold_minutes
    """
    __tablename__ = "chats"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "bot_id",
            "external_chat_id",
            name="uq_chats_project_bot_external",
        ),
        Index("ix_chats_project_id", "project_id"),
        Index("ix_chats_bot_id", "bot_id"),
        Index("ix_chats_tracking_link_id", "tracking_link_id"),
        Index("ix_chats_external_chat_id", "external_chat_id"),
        Index("ix_chats_external_user_id", "external_user_id"),
        Index("ix_chats_last_user_message_at", "last_user_message_at"),
        Index("ix_chats_last_manager_reply_at", "last_manager_reply_at"),
        Index("ix_chats_last_message_at", "last_message_at"),
        Index("ix_chats_last_read_at", "last_read_at"),
        Index("ix_chats_updated_at", "updated_at"),
        Index("ix_chats_project_last_user_msg", "project_id", "last_user_message_at"),
        Index("ix_chats_project_last_message", "project_id", "last_message_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    bot_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id"), nullable=True
    )
    tracking_link_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tracking_links.id"), nullable=True
    )
    external_chat_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Timestamp fields — updated by message_service on every message write
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_user_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_manager_reply_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Set explicitly when the manager opens the chat
    last_read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    project: Mapped[Project] = relationship("Project", back_populates="chats")
    bot: Mapped[Optional[Bot]] = relationship("Bot", back_populates="chats")
    tracking_link: Mapped[Optional[TrackingLink]] = relationship(
        "TrackingLink",
        back_populates="chats",
    )
    messages: Mapped[list[Message]] = relationship(
        "Message", back_populates="chat", order_by="Message.created_at"
    )
    lead: Mapped[Optional[Lead]] = relationship("Lead", back_populates="chat", uselist=False)
