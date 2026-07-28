from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UpdatedAtMixin,
    UUIDPrimaryKey,
)


class AIProviderConnection(
    Base,
    UUIDPrimaryKey,
    TimestampMixin,
    UpdatedAtMixin,
    SoftDeleteMixin,
):
    """Encrypted provider credential and protocol-level defaults."""

    __tablename__ = "ai_provider_connections"
    __table_args__ = (
        CheckConstraint(
            "api_style IN ('openai_compatible', 'gemini')",
            name="ck_ai_provider_connections_api_style",
        ),
        CheckConstraint(
            "request_timeout_seconds BETWEEN 1 AND 120",
            name="ck_ai_provider_connections_timeout",
        ),
        Index("ix_ai_provider_connections_provider", "provider"),
        Index("ix_ai_provider_connections_active", "is_active", "is_deleted"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    api_style: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="openai_compatible",
        server_default="openai_compatible",
    )
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    api_key_last_four: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    credential_fingerprint: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    default_model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    request_timeout_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=20,
        server_default="20",
    )
    supports_json_mode: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    pricing_json: Mapped[dict] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_by: Mapped[Optional[User]] = relationship("User")


class AIProjectSettings(Base, TimestampMixin, UpdatedAtMixin):
    """Opt-in AI runtime policy for one project."""

    __tablename__ = "ai_project_settings"
    __table_args__ = (
        CheckConstraint(
            "history_message_limit BETWEEN 1 AND 100",
            name="ck_ai_project_settings_history_limit",
        ),
        CheckConstraint(
            "max_context_chars BETWEEN 1000 AND 100000",
            name="ck_ai_project_settings_context_chars",
        ),
        CheckConstraint(
            "default_temperature BETWEEN 0 AND 2",
            name="ck_ai_project_settings_temperature",
        ),
        CheckConstraint(
            "default_max_output_tokens BETWEEN 1 AND 32000",
            name="ck_ai_project_settings_output_tokens",
        ),
        CheckConstraint(
            "typing_delay_per_char_ms BETWEEN 0 AND 250",
            name="ck_ai_project_settings_typing_delay",
        ),
        CheckConstraint(
            "min_delay_ms BETWEEN 0 AND 30000",
            name="ck_ai_project_settings_min_delay",
        ),
        CheckConstraint(
            "max_delay_ms BETWEEN 0 AND 30000",
            name="ck_ai_project_settings_max_delay",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    primary_connection_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_provider_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    primary_model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    fallback_connection_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_provider_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    fallback_model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    master_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    history_message_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=20,
        server_default="20",
    )
    max_context_chars: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=16000,
        server_default="16000",
    )
    default_temperature: Mapped[Decimal] = mapped_column(
        Numeric(3, 2),
        nullable=False,
        default=Decimal("0.40"),
        server_default="0.40",
    )
    default_max_output_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=400,
        server_default="400",
    )
    typing_delay_per_char_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
        server_default="30",
    )
    min_delay_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=500,
        server_default="500",
    )
    max_delay_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3500,
        server_default="3500",
    )
    daily_budget_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 4),
        nullable=True,
    )
    monthly_budget_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 4),
        nullable=True,
    )

    project: Mapped[Project] = relationship("Project")
    primary_connection: Mapped[Optional[AIProviderConnection]] = relationship(
        "AIProviderConnection",
        foreign_keys=[primary_connection_id],
    )
    fallback_connection: Mapped[Optional[AIProviderConnection]] = relationship(
        "AIProviderConnection",
        foreign_keys=[fallback_connection_id],
    )


class AIUsageLog(Base, UUIDPrimaryKey, TimestampMixin):
    """Append-only, prompt-free billing and reliability trace."""

    __tablename__ = "ai_usage_logs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('success', 'failed')",
            name="ck_ai_usage_logs_status",
        ),
        Index("ix_ai_usage_logs_project_created", "project_id", "created_at"),
        Index("ix_ai_usage_logs_connection_created", "connection_id", "created_at"),
        Index("ix_ai_usage_logs_chat_id", "chat_id"),
        Index("ix_ai_usage_logs_step_id", "step_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    connection_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_provider_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    chat_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="SET NULL"),
        nullable=True,
    )
    lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="SET NULL"),
        nullable=True,
    )
    funnel_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("funnels.id", ondelete="SET NULL"),
        nullable=True,
    )
    funnel_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("funnel_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    step_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("funnel_steps.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    credential_fingerprint: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    api_key_last_four: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    used_fallback: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 8),
        nullable=True,
    )
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    provider_request_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    project: Mapped[Project] = relationship("Project")
    connection: Mapped[Optional[AIProviderConnection]] = relationship(
        "AIProviderConnection"
    )
