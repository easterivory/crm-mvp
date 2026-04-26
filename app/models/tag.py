from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class Tag(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_tags_project_name"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    project: Mapped[Project] = relationship("Project", back_populates="tags")
    lead_tags: Mapped[list[LeadTag]] = relationship("LeadTag", back_populates="tag")
