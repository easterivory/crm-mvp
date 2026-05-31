from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKey


class PartnerIntegration(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    """Partner CRM integration for lead postbacks."""
    __tablename__ = "partner_integrations"
    __table_args__ = (Index("ix_partner_integrations_project_id", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    postback_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    auth_token: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

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
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    lead: Mapped[Lead] = relationship("Lead")
    partner_integration: Mapped[PartnerIntegration] = relationship(
        "PartnerIntegration", back_populates="submissions"
    )
