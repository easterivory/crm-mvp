from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class ProjectSnippet(Base, UUIDPrimaryKey, TimestampMixin):
    """Project-scoped quick reply or reusable Telegram media template."""

    __tablename__ = "project_snippets"
    __table_args__ = (
        CheckConstraint("channel IN ('telegram')", name="ck_project_snippets_channel"),
        CheckConstraint(
            "type IN ('text','photo','video','voice','video_note','document')",
            name="ck_project_snippets_type",
        ),
        CheckConstraint("length(btrim(name)) > 0", name="ck_project_snippets_name_not_blank"),
        CheckConstraint(
            "(type <> 'text') OR (content IS NOT NULL AND length(btrim(content)) > 0)",
            name="ck_project_snippets_text_content_required",
        ),
        CheckConstraint(
            "(type = 'text') OR ((file_id IS NOT NULL AND length(btrim(file_id)) > 0) OR storage_path IS NOT NULL)",
            name="ck_project_snippets_media_file_required",
        ),
        Index("ix_project_snippets_project_id", "project_id"),
        Index("ix_project_snippets_project_type", "project_id", "type"),
        Index("ix_project_snippets_project_channel", "project_id", "channel"),
        Index("ix_project_snippets_created_at", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(30), nullable=False, default="telegram", server_default="telegram")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    storage_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    project: Mapped[Project] = relationship("Project", back_populates="snippets")

    @property
    def preview_available(self) -> bool:
        return bool(self.storage_path)
