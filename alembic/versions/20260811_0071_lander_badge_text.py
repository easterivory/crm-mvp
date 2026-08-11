"""add editable lander badge text

Revision ID: 20260811_0071
Revises: 20260811_0070
Create Date: 2026-08-11 11:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260811_0071"
down_revision = "20260811_0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_landers",
        sa.Column("badge_text", sa.String(length=80), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("project_landers", "badge_text")
