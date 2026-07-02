from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKey

if TYPE_CHECKING:
    from app.models.project import Project


class ProjectGoogleSheetsConfig(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    """Per-project Google Sheets lead export settings."""

    __tablename__ = "project_google_sheets_configs"
    __table_args__ = (
        Index(
            "ix_project_google_sheets_configs_project_id",
            "project_id",
            unique=True,
        ),
        Index("ix_project_google_sheets_configs_is_enabled", "is_enabled"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    spreadsheet_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sheet_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="Лиды",
        server_default="Лиды",
    )
    trigger_statuses: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSONB),
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    bot_ids: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSONB),
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    export_fields: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSONB),
        nullable=False,
        default=lambda: [
            "created_at",
            "name",
            "phone",
            "telegram",
            "country",
            "age",
            "tracking_link",
            "buyer",
            "status",
            "cpl",
            "score",
        ],
        server_default=text(
            "'[\"created_at\", \"name\", \"phone\", \"telegram\", "
            "\"country\", \"age\", \"tracking_link\", \"buyer\", "
            "\"status\", \"cpl\", \"score\"]'::jsonb"
        ),
    )
    custom_field_keys: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSONB),
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )

    project: Mapped[Project] = relationship(
        "Project",
        back_populates="google_sheets_config",
    )
