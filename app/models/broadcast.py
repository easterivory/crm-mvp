from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKey


class Broadcast(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "broadcasts"
    __table_args__ = (
        Index("ix_broadcasts_project_id", "project_id"),
        Index("ix_broadcasts_bot_id", "bot_id"),
        Index("ix_broadcasts_status", "status"),
        Index("ix_broadcasts_scheduled_at", "scheduled_at"),
        Index("ix_broadcasts_created_by_user_id", "created_by_user_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    bot_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    audience_filter_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    audience_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    schedule_type: Mapped[str] = mapped_column(String(20), nullable=False, default="now", server_default="now")
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone_mode: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="project",
        server_default="project",
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship("Project")
    bot: Mapped[Optional[Bot]] = relationship("Bot")
    created_by: Mapped[Optional[User]] = relationship("User")
    recipients: Mapped[list[BroadcastRecipient]] = relationship(
        "BroadcastRecipient",
        back_populates="broadcast",
        cascade="all, delete-orphan",
    )

    @property
    def created_by_name(self) -> str | None:
        if "created_by" not in self.__dict__:
            return None
        return self.created_by.name if self.created_by is not None else None


class BroadcastRecipient(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "broadcast_recipients"
    __table_args__ = (
        UniqueConstraint("broadcast_id", "chat_id", name="uq_broadcast_recipients_broadcast_chat"),
        Index("ix_broadcast_recipients_broadcast_id", "broadcast_id"),
        Index("ix_broadcast_recipients_chat_id", "chat_id"),
        Index("ix_broadcast_recipients_lead_id", "lead_id"),
        Index("ix_broadcast_recipients_status", "status"),
        Index("ix_broadcast_recipients_pending", "broadcast_id", "status"),
    )

    broadcast_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("broadcasts.id"), nullable=False
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id"), nullable=False
    )
    lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    broadcast: Mapped[Broadcast] = relationship("Broadcast", back_populates="recipients")
    chat: Mapped[Chat] = relationship("Chat")
    lead: Mapped[Optional[Lead]] = relationship("Lead")


class BroadcastTemplate(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "broadcast_templates"
    __table_args__ = (
        Index("ix_broadcast_templates_project_id", "project_id"),
        Index("ix_broadcast_templates_created_by_user_id", "created_by_user_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    project: Mapped[Project] = relationship("Project")
    created_by: Mapped[Optional[User]] = relationship("User")

    @property
    def created_by_name(self) -> str | None:
        if "created_by" not in self.__dict__:
            return None
        return self.created_by.name if self.created_by is not None else None


class BroadcastUpload(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "broadcast_uploads"
    __table_args__ = (
        Index("ix_broadcast_uploads_project_id", "project_id"),
        Index("ix_broadcast_uploads_created_by_user_id", "created_by_user_id"),
        Index("ix_broadcast_uploads_status", "status"),
        Index("ix_broadcast_uploads_expires_at", "expires_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
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

    project: Mapped[Project] = relationship("Project")
    created_by: Mapped[Optional[User]] = relationship("User")
