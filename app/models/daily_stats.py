from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from sqlalchemy import Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class DailyStats(Base, UUIDPrimaryKey, TimestampMixin):
    """
    Aggregated per-project statistics for a single calendar day.
    Written by stats_worker once per day. Never updated after creation.
    """
    __tablename__ = "daily_stats"
    __table_args__ = (
        UniqueConstraint("project_id", "date", name="uq_daily_stats_project_date"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)

    new_chats: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    processed_chats: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    qualified_chats: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    lost_chats: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # NULL when there is no response time data for the day
    avg_response_time_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    project: Mapped[Project] = relationship("Project", back_populates="daily_stats")
