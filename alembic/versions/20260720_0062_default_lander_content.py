"""configurable default Telegram lander content

Revision ID: 20260720_0062
Revises: 20260720_0061
Create Date: 2026-07-20 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260720_0062"
down_revision = "20260720_0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_landers",
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.add_column(
        "project_landers",
        sa.Column("button_text", sa.String(length=80), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("project_landers", "button_text")
    op.drop_column("project_landers", "description")
