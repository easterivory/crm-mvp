from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKey


class ChatFilterPreset(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    """Saved chat filter template scoped to one project and owner."""

    __tablename__ = "chat_filter_presets"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "user_id",
            "name",
            name="uq_chat_filter_presets_project_user_name",
        ),
        Index("ix_chat_filter_presets_project_id", "project_id"),
        Index("ix_chat_filter_presets_user_id", "user_id"),
        Index("ix_chat_filter_presets_project_shared", "project_id", "is_shared"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    filters_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    is_shared: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    project: Mapped[Project] = relationship("Project")
    user: Mapped[User] = relationship("User")
