from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, Text, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import TrackingCostModel
from app.core.constants import TrackingSpendSource
from app.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKey


class TrackingLink(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    """Telegram deep-link attribution source scoped to a project and bot."""

    __tablename__ = "tracking_links"
    __table_args__ = (
        UniqueConstraint("ref_code", name="uq_tracking_links_ref_code"),
        UniqueConstraint("code", name="uq_tracking_links_code"),
        Index("ix_tracking_links_project_id", "project_id"),
        Index("ix_tracking_links_bot_id", "bot_id"),
        Index("ix_tracking_links_project_bot", "project_id", "bot_id"),
        Index("ix_tracking_links_code", "code"),
        Index("ix_tracking_links_is_active", "is_active"),
        Index("ix_tracking_links_target_step_id", "target_step_id"),
        Index("ix_tracking_links_target_funnel_id", "target_funnel_id"),
        Index("ix_tracking_links_target_funnel_step_key", "target_funnel_step_key"),
        Index("ix_tracking_links_buyer_id", "buyer_id"),
        Index("ix_tracking_links_fb_campaign_enabled", "fb_campaign_enabled"),
        Index("ix_tracking_links_channel_id", "channel_id"),
        Index("ix_tracking_links_destination_type", "destination_type"),
        CheckConstraint(
            "destination_type IN ('bot', 'channel')",
            name="ck_tracking_links_destination_type",
        ),
        CheckConstraint(
            "(destination_type = 'bot' AND channel_id IS NULL) OR "
            "(destination_type = 'channel' AND channel_id IS NOT NULL)",
            name="ck_tracking_links_channel_destination",
        ),
        CheckConstraint(
            "base_conversion_rate >= 0 AND base_conversion_rate <= 100",
            name="ck_tracking_links_base_conversion_rate_percent",
        ),
        CheckConstraint(
            "min_sample_size >= 1",
            name="ck_tracking_links_min_sample_size_positive",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id"), nullable=False
    )
    destination_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="bot", server_default="bot"
    )
    channel_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("telegram_channels.id", ondelete="RESTRICT"),
        nullable=True,
    )
    channel_join_request: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    channel_request_message_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    channel_request_message: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    channel_auto_approve: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # name/ref_code are the legacy API fields used by current Telegram /start
    # attribution. code/title are the v1 canonical names and stay synchronized
    # in TrackingService.
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ref_code: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    buyer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ad_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    payment_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    invite_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fb_pixel_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    fb_capi_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fb_campaign_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    fb_event_mappings_json: Mapped[list[dict]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    fb_proxy_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fb_test_event_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    buyer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cost_model: Mapped[TrackingCostModel] = mapped_column(
        SAEnum(
            TrackingCostModel,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            native_enum=False,
            length=20,
        ),
        nullable=False,
        default=TrackingCostModel.CPM,
        server_default=TrackingCostModel.CPM.value,
    )
    price_per_unit: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    spend: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    base_conversion_rate: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=10.0,
        server_default="10.0",
    )
    min_sample_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=500,
        server_default="500",
    )
    target_step_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_steps.id"), nullable=True
    )
    target_funnel_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funnels.id", ondelete="SET NULL"), nullable=True
    )
    target_funnel_step_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    project: Mapped[Project] = relationship("Project")
    bot: Mapped[Bot] = relationship("Bot", back_populates="tracking_links")
    channel: Mapped[Optional[TelegramChannel]] = relationship(
        "TelegramChannel", back_populates="tracking_links"
    )
    channel_invite_links: Mapped[list[TelegramChannelInviteLink]] = relationship(
        "TelegramChannelInviteLink",
        back_populates="tracking_link",
        cascade="all, delete-orphan",
    )
    target_step: Mapped[Optional[BotStep]] = relationship(
        "BotStep",
        foreign_keys=[target_step_id],
    )
    target_funnel: Mapped[Optional[Funnel]] = relationship(
        "Funnel",
        foreign_keys=[target_funnel_id],
    )
    created_by_user: Mapped[Optional[User]] = relationship(
        "User",
        foreign_keys=[created_by_user_id],
    )
    buyer: Mapped[Optional[User]] = relationship(
        "User",
        back_populates="buyer_tracking_links",
        foreign_keys=[buyer_id],
    )
    chats: Mapped[list[Chat]] = relationship("Chat", back_populates="tracking_link")
    events: Mapped[list[TrackingEvent]] = relationship(
        "TrackingEvent",
        back_populates="tracking_link",
        cascade="all, delete-orphan",
    )
    spends: Mapped[list[TrackingSpend]] = relationship(
        "TrackingSpend",
        back_populates="tracking_link",
        cascade="all, delete-orphan",
    )
    landers: Mapped[list[ProjectLander]] = relationship(
        "ProjectLander",
        back_populates="tracking_link",
    )


class TrackingSpend(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    """Manual or imported traffic spend for a tracking link."""

    __tablename__ = "tracking_spends"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_tracking_spends_amount_nonnegative"),
        CheckConstraint(
            "source IN ('crm_manual', 'buyer_bot')",
            name="ck_tracking_spends_source",
        ),
        Index("ix_tracking_spends_tracking_link_id", "tracking_link_id"),
        Index("ix_tracking_spends_spend_date", "spend_date"),
        Index("ix_tracking_spends_link_date", "tracking_link_id", "spend_date"),
        Index("ix_tracking_spends_source", "source"),
    )

    tracking_link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tracking_links.id"), nullable=False
    )
    spend_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="USD",
        server_default="USD",
    )
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[TrackingSpendSource] = mapped_column(
        SAEnum(
            TrackingSpendSource,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            native_enum=False,
            length=32,
        ),
        nullable=False,
        default=TrackingSpendSource.CRM_MANUAL,
        server_default=TrackingSpendSource.CRM_MANUAL.value,
    )
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    tracking_link: Mapped[TrackingLink] = relationship(
        "TrackingLink",
        back_populates="spends",
    )
    created_by_user: Mapped[Optional[User]] = relationship("User")


class TrackingEvent(Base, UUIDPrimaryKey, TimestampMixin):
    """Aggregated traffic counters imported from ad platforms."""

    __tablename__ = "tracking_events"
    __table_args__ = (
        UniqueConstraint(
            "tracking_link_id",
            "bucket_start",
            name="uq_tracking_events_link_bucket",
        ),
        Index("ix_tracking_events_project_id", "project_id"),
        Index("ix_tracking_events_tracking_link_id", "tracking_link_id"),
        Index("ix_tracking_events_link_created_at", "tracking_link_id", "created_at"),
        Index("ix_tracking_events_bucket_start", "bucket_start"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    tracking_link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tracking_links.id"), nullable=False
    )
    bucket_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    impressions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    project: Mapped[Project] = relationship("Project")
    tracking_link: Mapped[TrackingLink] = relationship(
        "TrackingLink",
        back_populates="events",
    )
