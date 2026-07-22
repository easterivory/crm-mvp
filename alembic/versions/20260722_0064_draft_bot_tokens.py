"""allow Telegram tokenless bot drafts

Revision ID: 20260722_0064
Revises: 20260721_0063
Create Date: 2026-07-22 14:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260722_0064"
down_revision = "20260721_0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "bots",
        "telegram_token",
        existing_type=sa.String(length=255),
        nullable=True,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE bots "
            "SET telegram_token = 'draft-disabled-' || id::text "
            "WHERE telegram_token IS NULL"
        )
    )
    op.alter_column(
        "bots",
        "telegram_token",
        existing_type=sa.String(length=255),
        nullable=False,
    )
