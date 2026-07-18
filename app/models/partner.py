from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKey


class PartnerIntegration(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    """Partner CRM integration for lead postbacks."""
    __tablename__ = "partner_integrations"
    __table_args__ = (
        CheckConstraint(
            "auth_type IN ('header', 'query_param', 'bearer')",
            name="ck_partner_integrations_auth_type",
        ),
        Index("ix_partner_integrations_project_id", "project_id"),
        Index("ix_partner_integrations_project_active", "project_id", "is_active"),
        Index(
            "ix_partner_integrations_project_auto_submit",
            "project_id",
            "is_auto_submit_enabled",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    postback_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    auth_token: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    auth_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="header", server_default="header"
    )
    auth_config: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    field_mapping: Mapped[dict[str, str]] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    required_fields: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSONB),
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    response_mapping: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    retry_config: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    request_config: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_auto_submit_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    auto_submit_rules: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    project: Mapped[Project] = relationship("Project", back_populates="partner_integrations")
    submissions: Mapped[list[LeadSubmission]] = relationship(
        "LeadSubmission", back_populates="partner_integration", cascade="all, delete-orphan"
    )


class LeadSubmission(Base, UUIDPrimaryKey):
    """Tracks lead submissions to partner CRMs."""
    __tablename__ = "lead_submissions"
    __table_args__ = (
        Index("ix_lead_submissions_lead_id", "lead_id"),
        Index("ix_lead_submissions_partner_integration_id", "partner_integration_id"),
        Index("ix_lead_submissions_status", "status"),
        Index("ix_lead_submissions_partner_status", "partner_status"),
        Index(
            "ix_lead_submissions_manual_source",
            "submitted_manually",
            "submission_source",
        ),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    partner_integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("partner_integrations.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    request_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    response_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    partner_feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    partner_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    partner_status_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_valid: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_manually: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    routing_decision_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submission_source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="legacy",
        server_default="legacy",
    )

    lead: Mapped[Lead] = relationship("Lead")
    submitted_by_user: Mapped[Optional[User]] = relationship("User", foreign_keys=[submitted_by_user_id])
    partner_integration: Mapped[PartnerIntegration] = relationship(
        "PartnerIntegration", back_populates="submissions"
    )
