from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKey


class TelegramChannel(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "telegram_channels"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "telegram_chat_id",
            name="uq_telegram_channels_project_chat",
        ),
        Index("ix_telegram_channels_project_id", "project_id"),
        Index("ix_telegram_channels_tracker_bot_id", "tracker_bot_id"),
        Index("ix_telegram_channels_telegram_chat_id", "telegram_chat_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    tracker_bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="RESTRICT"), nullable=False
    )
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    bot_is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    can_invite_users: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    project: Mapped[Project] = relationship("Project")
    tracker_bot: Mapped[Bot] = relationship("Bot")
    tracking_links: Mapped[list[TrackingLink]] = relationship(
        "TrackingLink", back_populates="channel"
    )
    invite_links: Mapped[list[TelegramChannelInviteLink]] = relationship(
        "TelegramChannelInviteLink",
        back_populates="channel",
        cascade="all, delete-orphan",
    )
    subscriptions: Mapped[list[TelegramChannelSubscription]] = relationship(
        "TelegramChannelSubscription",
        back_populates="channel",
        cascade="all, delete-orphan",
    )


class TelegramChannelInviteLink(
    Base,
    UUIDPrimaryKey,
    TimestampMixin,
    UpdatedAtMixin,
):
    __tablename__ = "telegram_channel_invite_links"
    __table_args__ = (
        UniqueConstraint("invite_link", name="uq_channel_invite_links_invite_link"),
        Index("ix_channel_invite_links_channel_id", "channel_id"),
        Index("ix_channel_invite_links_tracking_link_id", "tracking_link_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("telegram_channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    tracking_link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tracking_links.id", ondelete="CASCADE"),
        nullable=False,
    )
    invite_link: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    creates_join_request: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    channel: Mapped[TelegramChannel] = relationship(
        "TelegramChannel", back_populates="invite_links"
    )
    tracking_link: Mapped[TrackingLink] = relationship(
        "TrackingLink", back_populates="channel_invite_links"
    )


class TelegramChannelSubscription(
    Base,
    UUIDPrimaryKey,
    TimestampMixin,
    UpdatedAtMixin,
):
    __tablename__ = "telegram_channel_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "channel_id",
            "telegram_user_id",
            name="uq_channel_subscriptions_channel_user",
        ),
        CheckConstraint(
            "status IN ('pending', 'member', 'left', 'kicked')",
            name="ck_channel_subscriptions_status",
        ),
        Index("ix_channel_subscriptions_project_status", "project_id", "status"),
        Index(
            "ix_channel_subscriptions_tracking_status",
            "tracking_link_id",
            "status",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("telegram_channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    tracking_link_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tracking_links.id", ondelete="SET NULL"),
        nullable=True,
    )
    tracker_bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="RESTRICT"), nullable=False
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    first_joined_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    joined_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    left_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_event_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_update_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    channel: Mapped[TelegramChannel] = relationship(
        "TelegramChannel", back_populates="subscriptions"
    )
    tracking_link: Mapped[Optional[TrackingLink]] = relationship("TrackingLink")


class TelegramChannelSubscriptionEvent(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "telegram_channel_subscription_events"
    __table_args__ = (
        UniqueConstraint(
            "tracker_bot_id",
            "telegram_update_id",
            name="uq_channel_subscription_events_bot_update",
        ),
        CheckConstraint(
            "event_type IN ('join_request', 'join', 'leave', 'kick')",
            name="ck_channel_subscription_events_type",
        ),
        Index(
            "ix_channel_subscription_events_link_type_time",
            "tracking_link_id",
            "event_type",
            "occurred_at",
        ),
        Index(
            "ix_channel_subscription_events_channel_user",
            "channel_id",
            "telegram_user_id",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("telegram_channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    tracking_link_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tracking_links.id", ondelete="SET NULL"),
        nullable=True,
    )
    tracker_bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="RESTRICT"), nullable=False
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_update_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    previous_status: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    new_status: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    invite_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    request_message_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auto_approve_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    auto_start_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    request_message_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    request_approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    funnel_start_processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    funnel_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    funnel_start_chat_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="SET NULL"),
        nullable=True,
    )
    funnel_start_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_action_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    channel: Mapped[TelegramChannel] = relationship("TelegramChannel")
    tracking_link: Mapped[Optional[TrackingLink]] = relationship("TrackingLink")
