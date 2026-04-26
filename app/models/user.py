from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKey


class User(Base, UUIDPrimaryKey, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    # project_id is NULL for super_admin
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False, index=True
    )

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationships
    project: Mapped[Optional[Project]] = relationship("Project", back_populates="users")
    role: Mapped[Role] = relationship("Role", back_populates="users")

    managed_leads: Mapped[list[Lead]] = relationship(
        "Lead", back_populates="manager", foreign_keys="Lead.manager_id"
    )
    sent_messages: Mapped[list[Message]] = relationship(
        "Message", back_populates="sender", foreign_keys="Message.sender_id"
    )
    audit_actions: Mapped[list[AuditLog]] = relationship("AuditLog", back_populates="actor")
