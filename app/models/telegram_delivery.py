"""Durable Telegram intake and post-commit runtime dispatch, not chat history."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class TelegramInbox(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "telegram_inbox"
    __table_args__ = (
        UniqueConstraint("bot_id", "update_id", name="uq_telegram_inbox_update"),
        Index("ix_telegram_inbox_due", "status", "available_at"),
        Index("ix_telegram_inbox_peer", "bot_id", "peer_key", "created_at", "update_id",
              postgresql_where=text("status IN ('pending', 'processing')")),
        Index("ix_telegram_inbox_completed", "completed_at", postgresql_where=text("status = 'done'")),
    )
    bot_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    update_id: Mapped[int] = mapped_column(BigInteger)
    peer_key: Mapped[str] = mapped_column(String(100))
    payload_json: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class RuntimeDispatch(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "runtime_dispatches"
    __table_args__ = (
        Index("ix_runtime_dispatches_due", "status", "available_at"),
        Index("ix_runtime_dispatches_completed", "completed_at", postgresql_where=text("status = 'done'")),
    )
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(30))
    payload_json: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    diagnostics_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
