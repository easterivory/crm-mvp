from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKey


class Project(Base, UUIDPrimaryKey, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sla_threshold_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30"
    )

    # Relationships
    users: Mapped[list[User]] = relationship("User", back_populates="project")
    chats: Mapped[list[Chat]] = relationship("Chat", back_populates="project")
    leads: Mapped[list[Lead]] = relationship("Lead", back_populates="project")
    tags: Mapped[list[Tag]] = relationship("Tag", back_populates="project")
    audit_logs: Mapped[list[AuditLog]] = relationship("AuditLog", back_populates="project")
    alerts: Mapped[list[Alert]] = relationship("Alert", back_populates="project")
    daily_stats: Mapped[list[DailyStats]] = relationship("DailyStats", back_populates="project")
