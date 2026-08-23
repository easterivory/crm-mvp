from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, func, text
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
        Index("ix_bots_telegram_bot_id", "telegram_bot_id"),
        Index("ix_bots_is_deleted", "is_deleted"),
        Index("ix_bots_active_funnel_id", "active_funnel_id"),
        Index("ix_bots_active_funnel_version_id", "active_funnel_version_id"),
        Index("ix_bots_transport_type", "transport_type"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    transport_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="bot_api", server_default="bot_api"
    )
    telegram_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    telegram_bot_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    telegram_first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bot_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    crm_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    telegram_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    telegram_about: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    telegram_managed_commands: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    active_funnel_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funnels.id"), nullable=True
    )
    active_funnel_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funnel_versions.id"), nullable=True
    )

    project: Mapped[Project] = relationship("Project", back_populates="bots")
    versions: Mapped[list[BotVersion]] = relationship(
        "BotVersion",
        back_populates="bot",
        cascade="all, delete-orphan",
    )
    tracking_links: Mapped[list[TrackingLink]] = relationship(
        "TrackingLink",
        back_populates="bot",
    )
    chats: Mapped[list[Chat]] = relationship("Chat", back_populates="bot")
    config_audit_logs: Mapped[list[BotConfigAuditLog]] = relationship(
        "BotConfigAuditLog",
        back_populates="bot",
        cascade="all, delete-orphan",
    )
    telegram_user_connection: Mapped[Optional[TelegramUserConnection]] = relationship(
        "TelegramUserConnection",
        back_populates="bot",
        cascade="all, delete-orphan",
        uselist=False,
    )

    @property
    def has_telegram_token(self) -> bool:
        return bool(self.telegram_token)

    @property
    def is_telegram_user_account(self) -> bool:
        return self.transport_type == "user_mtproto"


class TelegramUserConnection(
    Base,
    UUIDPrimaryKey,
    TimestampMixin,
    UpdatedAtMixin,
):
    """Encrypted MTProto authorization state for one dedicated work account."""

    __tablename__ = "telegram_user_connections"
    __table_args__ = (
        Index("ix_telegram_user_connections_auth_status", "auth_status"),
        Index("ix_telegram_user_connections_connection_status", "connection_status"),
        Index(
            "ix_telegram_user_connections_telegram_user_id",
            "telegram_user_id",
            unique=True,
        ),
    )

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    api_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    api_hash_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    api_hash_last_four: Mapped[str] = mapped_column(String(4), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    session_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone_code_hash_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auth_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="disconnected", server_default="disconnected"
    )
    connection_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="disconnected", server_default="disconnected"
    )
    telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    telegram_first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    telegram_last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    auth_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_connected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    bot: Mapped[Bot] = relationship("Bot", back_populates="telegram_user_connection")


class BotConfigAuditLog(Base, UUIDPrimaryKey, TimestampMixin):
    """Admin-visible history of bot profile and runtime configuration changes."""

    __tablename__ = "bot_config_audit_logs"
    __table_args__ = (
        Index("ix_bot_config_audit_logs_bot_id", "bot_id"),
        Index("ix_bot_config_audit_logs_user_id", "user_id"),
        Index("ix_bot_config_audit_logs_action_type", "action_type"),
        Index("ix_bot_config_audit_logs_created_at", "created_at"),
    )

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    bot: Mapped[Bot] = relationship("Bot", back_populates="config_audit_logs")
    user: Mapped[Optional[User]] = relationship("User", back_populates="bot_config_audit_logs")


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
