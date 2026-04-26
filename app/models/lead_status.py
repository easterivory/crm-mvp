from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class LeadStatus(Base, UUIDPrimaryKey, TimestampMixin):
    """
    Mutable reference table for lead statuses.
    New statuses can be added via INSERT without schema migration.
    No PostgreSQL ENUM — avoids blocking ALTER TYPE operations.

    Initial seed rows: new, in_progress, qualified, lost.
    """
    __tablename__ = "lead_statuses"

    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_final: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    leads: Mapped[list[Lead]] = relationship("Lead", back_populates="status")
