from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UpdatedAtMixin,
    UUIDPrimaryKey,
)


class Bot(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin, SoftDeleteMixin):
    """Telegram bot definition scoped to a CRM project."""

    __tablename__ = "bots"
    __table_args__ = (
        Index("ix_bots_project_id", "project_id"),
        Index("ix_bots_bot_username", "bot_username"),
        Index("ix_bots_is_deleted", "is_deleted"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    telegram_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bot_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    project: Mapped[Project] = relationship("Project")
    versions: Mapped[list[BotVersion]] = relationship(
        "BotVersion",
        back_populates="bot",
        cascade="all, delete-orphan",
    )
    tracking_links: Mapped[list[TrackingLink]] = relationship(
        "TrackingLink",
        back_populates="bot",
    )

    @property
    def has_telegram_token(self) -> bool:
        return bool(self.telegram_token)


class BotVersion(Base, UUIDPrimaryKey, TimestampMixin):
    """Versioned bot scenario graph."""

    __tablename__ = "bot_versions"
    __table_args__ = (
        Index("ix_bot_versions_bot_id", "bot_id"),
        Index("ix_bot_versions_is_active", "is_active"),
        Index(
            "uq_bot_versions_one_active_per_bot",
            "bot_id",
            unique=True,
            postgresql_where=text("is_active IS TRUE"),
        ),
    )

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id"), nullable=False
    )
    version_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    start_step_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_steps.id"), nullable=True, index=True
    )

    bot: Mapped[Bot] = relationship("Bot", back_populates="versions")
    steps: Mapped[list[BotStep]] = relationship(
        "BotStep",
        back_populates="bot_version",
        cascade="all, delete-orphan",
        foreign_keys="BotStep.bot_version_id",
    )
    start_step: Mapped[Optional[BotStep]] = relationship(
        "BotStep",
        foreign_keys=[start_step_id],
        post_update=True,
    )
    chat_states: Mapped[list[ChatBotState]] = relationship(
        "ChatBotState",
        back_populates="bot_version",
    )


class BotStep(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    """Single executable step in a bot version graph."""

    __tablename__ = "bot_steps"
    __table_args__ = (
        Index("ix_bot_steps_bot_version_id", "bot_version_id"),
        Index("ix_bot_steps_next_step_id", "next_step_id"),
        Index("ix_bot_steps_fallback_step_id", "fallback_step_id"),
    )

    bot_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_versions.id"), nullable=False
    )
    step_type: Mapped[str] = mapped_column(String(50), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    next_step_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_steps.id"), nullable=True
    )
    fallback_step_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_steps.id"), nullable=True
    )

    bot_version: Mapped[BotVersion] = relationship(
        "BotVersion",
        back_populates="steps",
        foreign_keys=[bot_version_id],
    )
    next_step: Mapped[Optional[BotStep]] = relationship(
        "BotStep",
        remote_side="BotStep.id",
        foreign_keys=[next_step_id],
    )
    fallback_step: Mapped[Optional[BotStep]] = relationship(
        "BotStep",
        remote_side="BotStep.id",
        foreign_keys=[fallback_step_id],
    )


class ChatBotState(Base, TimestampMixin, UpdatedAtMixin):
    """Per-chat bot execution state pinned to the bot version that started it."""

    __tablename__ = "chat_bot_states"
    __table_args__ = (
        Index("ix_chat_bot_states_chat_id", "chat_id"),
        Index("ix_chat_bot_states_bot_version_id", "bot_version_id"),
        Index("ix_chat_bot_states_current_step_id", "current_step_id"),
        Index("ix_chat_bot_states_is_active", "is_active"),
    )

    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id"), primary_key=True
    )
    bot_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_versions.id"), nullable=False
    )
    current_step_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_steps.id"), nullable=True
    )
    variables: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    last_interaction_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    chat: Mapped[Chat] = relationship("Chat")
    bot_version: Mapped[BotVersion] = relationship(
        "BotVersion",
        back_populates="chat_states",
    )
    current_step: Mapped[Optional[BotStep]] = relationship(
        "BotStep",
        foreign_keys=[current_step_id],
    )
