"""restore UUID default for Telegram user connections

Revision ID: 20260824_0076
Revises: 20260822_0075
Create Date: 2026-08-24 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260824_0076"
down_revision = "20260822_0075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "telegram_user_connections",
        "id",
        existing_type=postgresql.UUID(as_uuid=True),
        existing_nullable=False,
        server_default=sa.text("gen_random_uuid()"),
    )


def downgrade() -> None:
    op.alter_column(
        "telegram_user_connections",
        "id",
        existing_type=postgresql.UUID(as_uuid=True),
        existing_nullable=False,
        server_default=None,
    )
