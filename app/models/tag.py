from __future__ import annotations

import uuid
from secrets import choice

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


TAG_COLOR_PALETTE = (
    "#BFDBFE",
    "#C7D2FE",
    "#DDD6FE",
    "#FBCFE8",
    "#FECACA",
    "#FED7AA",
    "#FDE68A",
    "#D9F99D",
    "#BBF7D0",
    "#A7F3D0",
    "#BAE6FD",
    "#E9D5FF",
)


def random_tag_color() -> str:
    return choice(TAG_COLOR_PALETTE)


class Tag(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_tags_project_name"),
        CheckConstraint("color ~ '^#[0-9A-Fa-f]{6}$'", name="ck_tags_color_hex"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(
        String(7),
        nullable=False,
        default=random_tag_color,
        server_default="#BFDBFE",
    )

    project: Mapped[Project] = relationship("Project", back_populates="tags")
    lead_tags: Mapped[list[LeadTag]] = relationship("LeadTag", back_populates="tag")
