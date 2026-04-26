from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class AuditLog(Base, UUIDPrimaryKey, TimestampMixin):
    """
    Immutable record of every state change on a Lead, Chat, or Message.

    entity_type + entity_id form a polymorphic reference (no FK constraint —
    entity lives in different tables). Integrity enforced at application level.

    Composite index on (entity_type, entity_id) is required for efficient
    history lookups per entity.
    """
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_project_id", "project_id"),
        Index("ix_audit_logs_actor_id", "actor_id"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    # NULL for system-initiated actions
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    action: Mapped[str] = mapped_column(String(100), nullable=False)
    # 'lead' | 'chat' | 'message'  — VARCHAR, not ENUM
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # {"old_value": ..., "new_value": ...}
    meta: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    project: Mapped[Project] = relationship("Project", back_populates="audit_logs")
    actor: Mapped[Optional[User]] = relationship("User", back_populates="audit_actions")
