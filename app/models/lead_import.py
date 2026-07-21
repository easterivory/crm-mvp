from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKey


class BotLeadImport(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    """Auditable Google Sheets import batch for one Telegram bot."""

    __tablename__ = "bot_lead_imports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('created','validated','completed','failed')",
            name="ck_bot_lead_imports_status",
        ),
        CheckConstraint(
            "total_rows >= 0 AND imported_count >= 0 AND updated_count >= 0 "
            "AND skipped_count >= 0 AND error_count >= 0",
            name="ck_bot_lead_imports_counts_nonnegative",
        ),
        Index("ix_bot_lead_imports_project_id", "project_id"),
        Index("ix_bot_lead_imports_bot_id", "bot_id"),
        Index("ix_bot_lead_imports_status", "status"),
        Index("ix_bot_lead_imports_created_at", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    imported_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_system: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="chatterfy",
        server_default="chatterfy",
    )
    spreadsheet_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    spreadsheet_url: Mapped[str] = mapped_column(Text, nullable=False)
    worksheet_title: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="Перенос лидов",
        server_default="Перенос лидов",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="created",
        server_default="created",
    )
    preview_checksum: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    preview_summary: Mapped[dict] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    total_rows: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    imported_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    updated_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    skipped_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    error_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
