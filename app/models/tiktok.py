from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class TikTokIntegration(Base, TimestampMixin):
    __tablename__ = "tiktok_integrations"

    tracking_link_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tracking_links.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    pixel_id: Mapped[str] = mapped_column(String(120))
    encrypted_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_event_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mappings_json: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))


class TikTokDelivery(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "tiktok_deliveries"
    __table_args__ = (
        Index("ix_tiktok_deliveries_due", "status", "next_attempt_at"),
        Index("ix_tiktok_deliveries_link_created", "tracking_link_id", "created_at"),
        Index("ix_tiktok_deliveries_created", "created_at"),
    )

    tracking_link_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tracking_links.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(String(100), unique=True)
    source_event: Mapped[str] = mapped_column(String(50))
    payload_json: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
