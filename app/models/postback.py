from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, ForeignKey, Index, String, Text, UniqueConstraint, text
from datetime import datetime
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKey


class PostbackRelayDelivery(Base, UUIDPrimaryKey, TimestampMixin):
    """Durable transport deduplication; retained even if an endpoint is deleted."""
    __tablename__ = "postback_relay_deliveries"
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


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
    processing_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="lifecycle_event", server_default="lifecycle_event")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
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
    submission_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    endpoint_revision: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    attempt_log: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    occurred_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
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


class PostbackEndpointRevision(Base):
    __tablename__ = "postback_endpoint_revisions"
    endpoint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


class PostbackBusinessEffect(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "postback_business_effects"
    __table_args__ = (UniqueConstraint("namespace", "external_event_id", name="uq_postback_business_event"),)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    namespace: Mapped[str] = mapped_column(String(200), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class PostbackRelayHealth(Base):
    __tablename__ = "postback_relay_health"
    instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stats_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class PostbackBinding(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "postback_bindings"
    __table_args__ = (UniqueConstraint("project_id", "namespace", "identifier_type", "external_id", name="uq_postback_binding_identity"),)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    identifier_type: Mapped[str] = mapped_column(String(30), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    submission_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    attribution_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class PostbackFollowup(Base, UUIDPrimaryKey, TimestampMixin):
    """External integrations execute only after the callback transaction commits."""
    __tablename__ = "postback_followups"
    __table_args__ = (UniqueConstraint("receipt_id", "kind", name="uq_postback_followup"),
        Index("ix_postback_followups_status_created", "status", "created_at"))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    receipt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error: Mapped[Optional[str]] = mapped_column(String(255))
