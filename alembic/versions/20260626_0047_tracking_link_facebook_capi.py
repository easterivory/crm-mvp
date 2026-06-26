"""tracking link facebook capi settings

Revision ID: 20260626_0047
Revises: 20260626_0046
Create Date: 2026-06-26 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260626_0047"
down_revision = "20260626_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tracking_links",
        sa.Column("fb_pixel_id", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "tracking_links",
        sa.Column("fb_capi_token", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tracking_links", "fb_capi_token")
    op.drop_column("tracking_links", "fb_pixel_id")
