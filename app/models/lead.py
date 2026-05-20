from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UpdatedAtMixin,
    UUIDPrimaryKey,
)


class Lead(Base, UUIDPrimaryKey, TimestampMixin, UpdatedAtMixin, SoftDeleteMixin):
    """
    Business entity tied 1-to-1 to a Chat.
    Stores: status, current manager, contact info, tags.

    manager_id is the simplified assignment — history is in audit_logs.
    status_id references lead_statuses (mutable reference table, not ENUM).
    """
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("chat_id", name="uq_leads_chat_id"),
        Index("ix_leads_project_id", "project_id"),
        Index("ix_leads_manager_id", "manager_id"),
        Index("ix_leads_status_id", "status_id"),
        Index("ix_leads_updated_at", "updated_at"),
        Index("ix_leads_project_status", "project_id", "status_id"),
        Index("ix_leads_project_manager", "project_id", "manager_id"),
        Index("ix_leads_project_created_at", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id"), nullable=False
    )
    manager_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    status_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead_statuses.id"), nullable=False
    )

    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    call_time_text: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    has_card: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    custom_fields: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    # Relationships
    project: Mapped[Project] = relationship("Project", back_populates="leads")
    chat: Mapped[Chat] = relationship("Chat", back_populates="lead")
    manager: Mapped[Optional[User]] = relationship(
        "User", back_populates="managed_leads", foreign_keys=[manager_id]
    )
    status: Mapped[LeadStatus] = relationship("LeadStatus", back_populates="leads")
    lead_tags: Mapped[list[LeadTag]] = relationship(
        "LeadTag", back_populates="lead", cascade="all, delete-orphan"
    )


class LeadTag(Base, TimestampMixin):
    """Junction table: Lead ↔ Tag (many-to-many with created_at)."""
    __tablename__ = "lead_tags"

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tags.id"), primary_key=True, index=True
    )

    lead: Mapped[Lead] = relationship("Lead", back_populates="lead_tags")
    tag: Mapped[Tag] = relationship("Tag", back_populates="lead_tags")
