"""Advertising is opt-in and keeps its own durable delivery history."""
from datetime import datetime
from uuid import UUID as PyUUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKey


def default_scenario(context):
    return context.get_current_parameters()["project_id"]


class AdvertisingConfig(Base, UpdatedAtMixin):
    __tablename__ = "advertising_configs"
    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=default_scenario)
    project_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), default="Основной", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settings_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class AdvertisingSlot(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "advertising_slots"
    project_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    scenario_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("advertising_configs.id"), default=default_scenario, index=True)
    name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    delay_minutes: Mapped[int] = mapped_column(Integer, default=120)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    content_json: Mapped[dict] = mapped_column(JSONB, default=dict)


class AdvertisingEnrollment(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "advertising_enrollments"
    __table_args__ = (
        Index("ix_ad_enrollment_due", "status", "due_at"),
        Index("ix_ad_enrollment_project_created", "project_id", "created_at"),
        Index("uq_ad_enrollment_live_chat", "chat_id", unique=True,
              postgresql_where=text("status IN ('waiting','active','completed','protected','stopped')")),
    )
    project_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    scenario_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("advertising_configs.id"), default=default_scenario, index=True)
    chat_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chats.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="waiting")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="automatic")
    stop_main: Mapped[bool] = mapped_column(Boolean, default=True)
    marker_tag_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))


class AdvertisingDelivery(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "advertising_deliveries"
    __table_args__ = (UniqueConstraint("enrollment_id", "slot_id", name="uq_ad_delivery_slot"),)
    enrollment_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("advertising_enrollments.id"), index=True)
    slot_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("advertising_slots.id"))
    position: Mapped[int] = mapped_column(Integer)
    delay_minutes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    revision: Mapped[int | None] = mapped_column(Integer)
    content_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    progress_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))


class AdvertisingAudit(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "advertising_audit"
    project_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    scenario_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), default=default_scenario, index=True)
    actor_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    event: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
