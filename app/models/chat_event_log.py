from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class ChatEventLog(Base, UUIDPrimaryKey, TimestampMixin):
    """Append-only audit trail for operator actions inside a chat."""

    __tablename__ = "chat_event_logs"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('status_change','tag_added','manager_assigned','SLA_breached','note_added')",
            name="ck_chat_event_logs_event_type",
        ),
        Index("ix_chat_event_logs_chat_id", "chat_id"),
        Index("ix_chat_event_logs_user_id", "user_id"),
        Index("ix_chat_event_logs_event_type", "event_type"),
        Index("ix_chat_event_logs_created_at", "created_at"),
        Index("ix_chat_event_logs_chat_created_at", "chat_id", "created_at"),
    )

    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    chat: Mapped[Chat] = relationship("Chat", back_populates="event_logs")
    user: Mapped[Optional[User]] = relationship("User", back_populates="chat_event_logs")
