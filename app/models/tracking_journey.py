from datetime import datetime
from uuid import UUID as UUIDType

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKey


class TrackingJourneyConfig(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "tracking_journey_configs"

    funnel_id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), ForeignKey("funnels.id", ondelete="CASCADE"), primary_key=True)
    project_id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class LeadTagHistory(Base, UUIDPrimaryKey):
    """Assignment facts survive removal/renaming of a tag and funnel resets."""
    __tablename__ = "lead_tag_history"
    __table_args__ = (Index("ix_lead_tag_history_lead_tag_time", "lead_id", "tag_id", "occurred_at"),)

    lead_id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    tag_id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), nullable=False)
    tag_name: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
