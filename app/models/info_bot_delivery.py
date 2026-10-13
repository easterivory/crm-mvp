"""Private durable checkpoints for the standalone statistics bot."""
from sqlalchemy import BigInteger, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin, UpdatedAtMixin


class InfoBotDelivery(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "info_bot_deliveries"
    __table_args__ = (Index("ix_info_bot_deliveries_bot_created", "bot_id", "created_at"),)
    bot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    plan_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class InfoBotCursor(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "info_bot_cursors"
    bot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    next_update_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
