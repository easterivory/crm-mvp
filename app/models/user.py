from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKey
from app.core.constants import ROOT_ADMIN_EMAIL


class User(Base, UUIDPrimaryKey, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "handler_code IS NULL OR handler_code ~ '^[0-9]{4}$'",
            name="ck_users_handler_code_format",
        ),
        Index(
            "uq_users_handler_code",
            "handler_code",
            unique=True,
            postgresql_where=text("handler_code IS NOT NULL"),
        ),
    )

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
    telegram_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        unique=True,
        index=True,
    )
    buyer_telegram_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        unique=True,
        index=True,
    )
    buyer_invite_token: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        unique=True,
        index=True,
    )
    handler_code: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    buyer_fb_pixel_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    buyer_fb_capi_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    project: Mapped[Optional[Project]] = relationship("Project", back_populates="users")
    role: Mapped[Role] = relationship("Role", back_populates="users")
    project_accesses: Mapped[list[UserProjectAccess]] = relationship(
        "UserProjectAccess",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    managed_leads: Mapped[list[Lead]] = relationship(
        "Lead", back_populates="manager", foreign_keys="Lead.manager_id"
    )
    sent_messages: Mapped[list[Message]] = relationship(
        "Message", back_populates="sender", foreign_keys="Message.sender_id"
    )
    operator_messages: Mapped[list[Message]] = relationship(
        "Message", back_populates="operator", foreign_keys="Message.operator_id"
    )
    chat_event_logs: Mapped[list[ChatEventLog]] = relationship(
        "ChatEventLog", back_populates="user", foreign_keys="ChatEventLog.user_id"
    )
    bot_config_audit_logs: Mapped[list[BotConfigAuditLog]] = relationship(
        "BotConfigAuditLog",
        back_populates="user",
        foreign_keys="BotConfigAuditLog.user_id",
    )
    audit_actions: Mapped[list[AuditLog]] = relationship("AuditLog", back_populates="actor")
    buyer_tracking_links: Mapped[list[TrackingLink]] = relationship(
        "TrackingLink",
        back_populates="buyer",
        foreign_keys="TrackingLink.buyer_id",
    )

    @property
    def role_name(self) -> str | None:
        return self.role.name if self.role is not None else None

    @property
    def is_root(self) -> bool:
        return self.email.strip().lower() == ROOT_ADMIN_EMAIL

    @property
    def project_ids(self) -> list[uuid.UUID]:
        accesses = self.__dict__.get("project_accesses")
        if accesses is None:
            return [self.project_id] if self.project_id is not None else []
        ids = [access.project_id for access in accesses]
        if self.project_id is not None and self.project_id not in ids:
            ids.insert(0, self.project_id)
        return ids


class UserProjectAccess(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "user_project_accesses"
    __table_args__ = (
        UniqueConstraint("user_id", "project_id", name="uq_user_project_access_user_project"),
        Index("ix_user_project_accesses_user_id", "user_id"),
        Index("ix_user_project_accesses_project_id", "project_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="project_accesses")
    project: Mapped[Project] = relationship("Project")
