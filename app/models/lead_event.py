from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class LeadEvent(Base, UUIDPrimaryKey, TimestampMixin):
    """Canonical lead lifecycle event, independent of the event source."""

    __tablename__ = "lead_events"
    __table_args__ = (
        UniqueConstraint(
            "postback_endpoint_id",
            "external_event_id",
            name="uq_lead_events_endpoint_external",
        ),
        Index("ix_lead_events_project_type_occurred", "project_id", "event_type", "occurred_at"),
        Index("ix_lead_events_lead_occurred", "lead_id", "occurred_at"),
        Index("ix_lead_events_partner_integration_id", "partner_integration_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    partner_integration_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("partner_integrations.id", ondelete="SET NULL"),
        nullable=True,
    )
    postback_endpoint_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("postback_endpoints.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    attributed_manager_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    external_event_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    payload_json: Mapped[dict] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    lead: Mapped[Lead] = relationship("Lead")
    partner_integration: Mapped[Optional[PartnerIntegration]] = relationship("PartnerIntegration")
    postback_endpoint: Mapped[Optional[PostbackEndpoint]] = relationship("PostbackEndpoint")
    created_by_user: Mapped[Optional[User]] = relationship(
        "User",
        foreign_keys=[created_by_user_id],
    )
    attributed_manager: Mapped[Optional[User]] = relationship(
        "User",
        foreign_keys=[attributed_manager_id],
    )
