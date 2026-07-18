from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKey


class ProjectDomain(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    """Custom domain parked for project landing pages."""

    __tablename__ = "project_domains"
    __table_args__ = (
        Index("ix_project_domains_domain_name", "domain_name", unique=True),
        Index("ix_project_domains_project_id", "project_id"),
        Index("ix_project_domains_project_active", "project_id", "is_active"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    domain_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    project: Mapped[Project] = relationship("Project", back_populates="domains")
    landers: Mapped[list[ProjectLander]] = relationship(
        "ProjectLander",
        back_populates="domain",
        passive_deletes=True,
    )


class ProjectLander(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin):
    """Landing page entry point served by slug and attached to a parked domain."""

    __tablename__ = "project_landers"
    __table_args__ = (
        CheckConstraint(
            "type IN ('default_tg_redirect', 'custom_upload')",
            name="ck_project_landers_type",
        ),
        Index("ix_project_landers_slug", "slug", unique=True),
        Index("ix_project_landers_domain_id", "domain_id"),
        Index("ix_project_landers_project_id", "project_id"),
        Index("ix_project_landers_tracking_link_id", "tracking_link_id"),
        Index("ix_project_landers_domain_active", "domain_id", "is_active"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    domain_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("project_domains.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    tracking_link_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tracking_links.id", ondelete="SET NULL"),
        nullable=True,
    )
    pixels_json: Mapped[list[dict]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    utm_defaults_json: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    meta_events_json: Mapped[list[dict]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    auto_redirect_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    custom_html_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    project: Mapped[Project] = relationship("Project", back_populates="landers")
    domain: Mapped[Optional[ProjectDomain]] = relationship(
        "ProjectDomain",
        back_populates="landers",
    )
    tracking_link: Mapped[Optional[TrackingLink]] = relationship(
        "TrackingLink",
        back_populates="landers",
    )
