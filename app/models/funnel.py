from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKey


class Funnel(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    """Project/bot scoped automation funnel."""

    __tablename__ = "funnels"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="ck_funnels_status"),
        Index("ix_funnels_project_id", "project_id"),
        Index("ix_funnels_bot_id", "bot_id"),
        Index("ix_funnels_status", "status"),
        Index("ix_funnels_project_bot_status", "project_id", "bot_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    versions: Mapped[list[FunnelVersion]] = relationship(
        "FunnelVersion",
        back_populates="funnel",
        cascade="all, delete-orphan",
    )


class FunnelVersion(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    """Draft/published/archived immutable-ish funnel graph version."""

    __tablename__ = "funnel_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_funnel_versions_status",
        ),
        UniqueConstraint(
            "funnel_id",
            "version_number",
            name="uq_funnel_versions_funnel_version_number",
        ),
        Index("ix_funnel_versions_funnel_id", "funnel_id"),
        Index("ix_funnel_versions_status", "status"),
        Index("ix_funnel_versions_published_at", "published_at"),
        Index(
            "uq_funnel_versions_one_published_per_funnel",
            "funnel_id",
            unique=True,
            postgresql_where=text("status = 'published'"),
        ),
    )

    funnel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funnels.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    funnel: Mapped[Funnel] = relationship("Funnel", back_populates="versions")
    steps: Mapped[list[FunnelStep]] = relationship(
        "FunnelStep",
        back_populates="version",
        cascade="all, delete-orphan",
    )
    edges: Mapped[list[FunnelEdge]] = relationship(
        "FunnelEdge",
        back_populates="version",
        cascade="all, delete-orphan",
    )
    push_rules: Mapped[list[FunnelPushRule]] = relationship(
        "FunnelPushRule",
        back_populates="version",
        cascade="all, delete-orphan",
    )
    field_mappings: Mapped[list[FunnelFieldMapping]] = relationship(
        "FunnelFieldMapping",
        back_populates="version",
        cascade="all, delete-orphan",
    )


class FunnelStep(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "funnel_steps"
    __table_args__ = (
        UniqueConstraint(
            "funnel_version_id",
            "key",
            name="uq_funnel_steps_version_key",
        ),
        Index("ix_funnel_steps_funnel_version_id", "funnel_version_id"),
        Index("ix_funnel_steps_step_type", "step_type"),
        Index("ix_funnel_steps_block_type", "block_type"),
    )

    funnel_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funnel_versions.id"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    step_type: Mapped[str] = mapped_column(String(50), nullable=False)
    block_type: Mapped[str] = mapped_column(String(100), nullable=False)
    position_x: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    position_y: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    config_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    validation_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    ui_schema_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)

    version: Mapped[FunnelVersion] = relationship("FunnelVersion", back_populates="steps")


class FunnelEdge(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "funnel_edges"
    __table_args__ = (
        Index("ix_funnel_edges_funnel_version_id", "funnel_version_id"),
        Index("ix_funnel_edges_from_step_id", "from_step_id"),
        Index("ix_funnel_edges_to_step_id", "to_step_id"),
    )

    funnel_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funnel_versions.id"), nullable=False
    )
    from_step_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funnel_steps.id"), nullable=False
    )
    to_step_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funnel_steps.id"), nullable=False
    )
    condition_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    version: Mapped[FunnelVersion] = relationship("FunnelVersion", back_populates="edges")
    from_step: Mapped[FunnelStep] = relationship(
        "FunnelStep",
        foreign_keys=[from_step_id],
    )
    to_step: Mapped[FunnelStep] = relationship(
        "FunnelStep",
        foreign_keys=[to_step_id],
    )


class FunnelPushRule(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "funnel_push_rules"
    __table_args__ = (
        CheckConstraint(
            "action_after_send IN ('stay', 'move_to_step', 'finish', 'assign_operator')",
            name="ck_funnel_push_rules_action_after_send",
        ),
        Index("ix_funnel_push_rules_funnel_version_id", "funnel_version_id"),
        Index("ix_funnel_push_rules_step_id", "step_id"),
        Index("ix_funnel_push_rules_is_active", "is_active"),
    )

    funnel_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funnel_versions.id"), nullable=False
    )
    step_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funnel_steps.id"), nullable=False
    )
    delay_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    action_after_send: Mapped[str] = mapped_column(
        String(50), nullable=False, default="stay", server_default="stay"
    )
    target_step_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funnel_steps.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    version: Mapped[FunnelVersion] = relationship("FunnelVersion", back_populates="push_rules")
    step: Mapped[FunnelStep] = relationship("FunnelStep", foreign_keys=[step_id])
    target_step: Mapped[Optional[FunnelStep]] = relationship(
        "FunnelStep",
        foreign_keys=[target_step_id],
    )


class FunnelFieldMapping(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "funnel_field_mappings"
    __table_args__ = (
        CheckConstraint(
            "source IN ('user_answer', 'button_value', 'computed_value')",
            name="ck_funnel_field_mappings_source",
        ),
        Index("ix_funnel_field_mappings_funnel_version_id", "funnel_version_id"),
        Index("ix_funnel_field_mappings_step_id", "step_id"),
        Index("ix_funnel_field_mappings_lead_field_key", "lead_field_key"),
    )

    funnel_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funnel_versions.id"), nullable=False
    )
    step_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funnel_steps.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    lead_field_key: Mapped[str] = mapped_column(String(100), nullable=False)
    transform_rule_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    is_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    version: Mapped[FunnelVersion] = relationship(
        "FunnelVersion",
        back_populates="field_mappings",
    )
    step: Mapped[FunnelStep] = relationship("FunnelStep")


class ChatFunnelState(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    """Independent funnel runtime state that leaves legacy ChatBotState untouched."""

    __tablename__ = "chat_funnel_states"
    __table_args__ = (
        UniqueConstraint("chat_id", name="uq_chat_funnel_states_chat_id"),
        Index("ix_chat_funnel_states_chat_id", "chat_id"),
        Index("ix_chat_funnel_states_funnel_id", "funnel_id"),
        Index("ix_chat_funnel_states_funnel_version_id", "funnel_version_id"),
        Index("ix_chat_funnel_states_current_step_id", "current_step_id"),
        Index("ix_chat_funnel_states_completed_at", "completed_at"),
        Index("ix_chat_funnel_states_entered_step_at", "entered_step_at"),
    )

    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id"), nullable=False
    )
    funnel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funnels.id"), nullable=False
    )
    funnel_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funnel_versions.id"), nullable=False
    )
    current_step_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funnel_steps.id"), nullable=False
    )
    entered_step_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    chat: Mapped[Chat] = relationship("Chat")
    funnel: Mapped[Funnel] = relationship("Funnel")
    version: Mapped[FunnelVersion] = relationship("FunnelVersion")
    current_step: Mapped[FunnelStep] = relationship("FunnelStep")
