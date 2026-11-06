"""Opt-in offers. Issued URLs and payout versions are immutable historical facts."""
from datetime import datetime
from uuid import UUID as PyUUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKey


class OfferPayoutPolicy(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "offer_payout_policies"
    project_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    partner_name: Mapped[str] = mapped_column(String(255))
    count_scope: Mapped[str] = mapped_column(String(30), default="offer")
    current_version: Mapped[int] = mapped_column(Integer, default=1)


class OfferPayoutVersion(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "offer_payout_versions"
    __table_args__ = (UniqueConstraint("policy_id", "version", name="uq_offer_payout_version"),)
    policy_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("offer_payout_policies.id"))
    version: Mapped[int] = mapped_column(Integer)
    terms_json: Mapped[dict] = mapped_column(JSONB)
    created_by_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class OfferPayoutAssignment(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "offer_payout_assignments"
    __table_args__ = (Index("ix_offer_payout_assignment_at", "offer_id", "created_at"),)
    offer_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("gambling_offers.id"))
    policy_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("offer_payout_policies.id"))
    created_by_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class GamblingOffer(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "gambling_offers"
    project_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    partner_name: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str] = mapped_column(Text)
    postbacks_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    identifier_parameter: Mapped[str | None] = mapped_column(String(100))
    endpoint_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("postback_endpoints.id"))
    payout_policy_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("offer_payout_policies.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class OfferLink(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "offer_links"
    __table_args__ = (UniqueConstraint("lead_id", "offer_id", "run_key", name="uq_offer_link_run"),)
    project_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    offer_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("gambling_offers.id"), index=True)
    lead_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), index=True)
    run_key: Mapped[str] = mapped_column(String(100))
    token: Mapped[str] = mapped_column(String(64), unique=True)
    issued_url: Mapped[str] = mapped_column(Text)
    endpoint_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("postback_endpoints.id"))
    attribution_json: Mapped[dict] = mapped_column(JSONB)


class OfferConversion(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "offer_conversions"
    __table_args__ = (
        Index("uq_offer_first_conversion", "offer_id", "lead_id", "event_type", unique=True,
              postgresql_where=text("event_type IN ('registration','deposit')")),
        Index("ix_offer_conversion_finance", "project_id", "occurred_at", "payout_version_id"),
    )
    project_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    offer_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("gambling_offers.id"))
    lead_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"))
    offer_link_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("offer_links.id"))
    event_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lead_events.id"), unique=True)
    event_type: Mapped[str] = mapped_column(String(30))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payout_version_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("offer_payout_versions.id"))
    qualified: Mapped[bool | None] = mapped_column(Boolean)
    qualification_reason: Mapped[str | None] = mapped_column(String(255))
    event_time_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    review_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    reviewed_by_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
