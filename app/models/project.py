from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import LeadStatusCode
from app.models.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UpdatedAtMixin,
    UUIDPrimaryKey,
)


class Project(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_projects_status",
        ),
        CheckConstraint(
            "chat_lease_minutes >= 0",
            name="ck_projects_chat_lease_minutes_nonnegative",
        ),
        CheckConstraint(
            "project_format IN ('submission', 'gambling')",
            name="ck_projects_project_format",
        ),
        CheckConstraint(
            "push_unread_threshold >= 1",
            name="ck_projects_push_unread_threshold_positive",
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
        index=True,
    )
    sla_threshold_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30"
    )
    operator_lang: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="ru",
        server_default="ru",
    )
    default_client_lang: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="en",
        server_default="en",
    )
    is_translation_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    tracking_lead_status_codes: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSONB),
        nullable=False,
        default=lambda: list(LeadStatusCode.TRACKING_LEAD_DEFAULT),
        server_default=text("'[\"submitted\",\"qualified\"]'::jsonb"),
    )
    use_confidence_score: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    hide_assigned_chats_from_all: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    chat_lease_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
        server_default="30",
    )
    project_format: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="submission",
        server_default="submission",
    )
    vip_tags: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSONB),
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    push_unread_threshold: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    confidence_weights: Mapped[Optional[dict[str, int]]] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=True,
    )
    confidence_thresholds: Mapped[Optional[dict[str, int]]] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=True,
    )
    facebook_tag_event_rules: Mapped[list[dict[str, str]]] = mapped_column(
        MutableList.as_mutable(JSONB),
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )

    # Relationships
    bots: Mapped[list[Bot]] = relationship("Bot", back_populates="project")
    users: Mapped[list[User]] = relationship("User", back_populates="project")
    chats: Mapped[list[Chat]] = relationship("Chat", back_populates="project")
    leads: Mapped[list[Lead]] = relationship("Lead", back_populates="project")
    tags: Mapped[list[Tag]] = relationship("Tag", back_populates="project")
    audit_logs: Mapped[list[AuditLog]] = relationship("AuditLog", back_populates="project")
    alerts: Mapped[list[Alert]] = relationship("Alert", back_populates="project")
    daily_stats: Mapped[list[DailyStats]] = relationship("DailyStats", back_populates="project")
    snippets: Mapped[list[ProjectSnippet]] = relationship(
        "ProjectSnippet", back_populates="project", cascade="all, delete-orphan"
    )
    partner_integrations: Mapped[list[PartnerIntegration]] = relationship(
        "PartnerIntegration", back_populates="project"
    )
    domains: Mapped[list[ProjectDomain]] = relationship(
        "ProjectDomain", back_populates="project", cascade="all, delete-orphan"
    )
    landers: Mapped[list[ProjectLander]] = relationship(
        "ProjectLander", back_populates="project", cascade="all, delete-orphan"
    )
    google_sheets_config: Mapped[Optional[ProjectGoogleSheetsConfig]] = relationship(
        "ProjectGoogleSheetsConfig",
        back_populates="project",
        cascade="all, delete-orphan",
        single_parent=True,
        uselist=False,
    )
