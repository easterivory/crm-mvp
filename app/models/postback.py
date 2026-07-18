from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKey


class PostbackEndpoint(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    """Project-scoped authenticated endpoint exposed to a partner."""

    __tablename__ = "postback_endpoints"
    __table_args__ = (
        UniqueConstraint("secret_token", name="uq_postback_endpoints_secret_token"),
        Index("ix_postback_endpoints_project_id", "project_id"),
        Index("ix_postback_endpoints_partner_integration_id", "partner_integration_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    partner_integration_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("partner_integrations.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    secret_token: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    parameter_mapping: Mapped[dict] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    project: Mapped[Project] = relationship("Project")
    partner_integration: Mapped[Optional[PartnerIntegration]] = relationship("PartnerIntegration")
    receipts: Mapped[list[PostbackReceipt]] = relationship(
        "PostbackReceipt", back_populates="endpoint", cascade="all, delete-orphan"
    )


class PostbackReceipt(Base, UUIDPrimaryKey, TimestampMixin):
    """Immutable intake log. Unmatched callbacks are retained for diagnostics."""

    __tablename__ = "postback_receipts"
    __table_args__ = (
        Index("ix_postback_receipts_endpoint_created_at", "endpoint_id", "created_at"),
        Index("ix_postback_receipts_project_status", "project_id", "status"),
        Index("ix_postback_receipts_lead_id", "lead_id"),
    )

    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("postback_endpoints.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
    )
    lead_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead_events.id", ondelete="SET NULL"), nullable=True
    )
    request_method: Mapped[str] = mapped_column(String(10), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    query_payload: Mapped[dict] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    body_payload: Mapped[dict] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    endpoint: Mapped[PostbackEndpoint] = relationship("PostbackEndpoint", back_populates="receipts")
    lead: Mapped[Optional[Lead]] = relationship("Lead")
    lead_event: Mapped[Optional[LeadEvent]] = relationship("LeadEvent")
