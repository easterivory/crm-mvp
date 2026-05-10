from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import TrackingCostModel
from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class TrackingLink(Base, UUIDPrimaryKey, TimestampMixin):
    """Telegram deep-link attribution source scoped to a project and bot."""

    __tablename__ = "tracking_links"
    __table_args__ = (
        UniqueConstraint("ref_code", name="uq_tracking_links_ref_code"),
        Index("ix_tracking_links_project_id", "project_id"),
        Index("ix_tracking_links_bot_id", "bot_id"),
        Index("ix_tracking_links_target_step_id", "target_step_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ref_code: Mapped[str] = mapped_column(String(100), nullable=False)
    cost_model: Mapped[TrackingCostModel] = mapped_column(
        SAEnum(
            TrackingCostModel,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            native_enum=False,
            length=20,
        ),
        nullable=False,
        default=TrackingCostModel.FIX_PDP,
        server_default=TrackingCostModel.FIX_PDP.value,
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
    target_step_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_steps.id"), nullable=True
    )

    project: Mapped[Project] = relationship("Project")
    bot: Mapped[Bot] = relationship("Bot", back_populates="tracking_links")
    target_step: Mapped[Optional[BotStep]] = relationship(
        "BotStep",
        foreign_keys=[target_step_id],
    )
    chats: Mapped[list[Chat]] = relationship("Chat", back_populates="tracking_link")
    events: Mapped[list[TrackingEvent]] = relationship(
        "TrackingEvent",
        back_populates="tracking_link",
        cascade="all, delete-orphan",
    )


class TrackingEvent(Base, UUIDPrimaryKey, TimestampMixin):
    """Aggregated traffic counters imported from ad platforms."""

    __tablename__ = "tracking_events"
    __table_args__ = (
        Index("ix_tracking_events_project_id", "project_id"),
        Index("ix_tracking_events_tracking_link_id", "tracking_link_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    tracking_link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tracking_links.id"), nullable=False
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
