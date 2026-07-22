"""track Telegram commands managed by funnel configuration

Revision ID: 20260722_0065
Revises: 20260722_0064
Create Date: 2026-07-22 15:10:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260722_0065"
down_revision = "20260722_0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bots",
        sa.Column(
            "telegram_managed_commands",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("bots", "telegram_managed_commands")
