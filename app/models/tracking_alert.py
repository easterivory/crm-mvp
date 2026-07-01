from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UpdatedAtMixin


class TrackingConversionAlertState(Base, UpdatedAtMixin):
    """Last observed benchmark status for transition-based admin alerts."""

    __tablename__ = "tracking_conversion_alert_states"

    tracking_link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tracking_links.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_status: Mapped[str] = mapped_column(String(32), nullable=False)
    low_cr_alerted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    tracking_link: Mapped[TrackingLink] = relationship("TrackingLink")
