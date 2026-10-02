"""Opt-in traffic rules, evaluation state and durable notification outbox."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey, UpdatedAtMixin


class TrafficQualitySettings(Base, UpdatedAtMixin):
    __tablename__ = "traffic_quality_settings"
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class TrafficQualityOverride(Base, UpdatedAtMixin):
    __tablename__ = "traffic_quality_overrides"
    link_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tracking_links.id", ondelete="CASCADE"), primary_key=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class TrafficQualityState(Base, UpdatedAtMixin):
    __tablename__ = "traffic_quality_states"
    link_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tracking_links.id", ondelete="CASCADE"), primary_key=True)
    rule_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="insufficient_data")
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class TrafficQualityDelivery(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "traffic_quality_deliveries"
    __table_args__ = (UniqueConstraint("dedup_key", name="uq_quality_delivery_key"),)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    link_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tracking_links.id", ondelete="CASCADE"), nullable=False)
    recipient_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    bot_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(500))


class TrafficQualityAcknowledgement(Base, UpdatedAtMixin):
    __tablename__ = "traffic_quality_acknowledgements"
    link_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tracking_links.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generations: Mapped[dict] = mapped_column(JSONB, nullable=False)
