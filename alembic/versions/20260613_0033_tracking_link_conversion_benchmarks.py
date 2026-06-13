"""tracking link conversion benchmarks

Revision ID: 20260613_0033
Revises: 20260612_0032
Create Date: 2026-06-13 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260613_0033"
down_revision = "20260612_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tracking_links",
        sa.Column(
            "base_conversion_rate",
            sa.Float(),
            nullable=False,
            server_default=sa.text("10.0"),
        ),
    )
    op.add_column(
        "tracking_links",
        sa.Column(
            "min_sample_size",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("500"),
        ),
    )
    op.create_check_constraint(
        "ck_tracking_links_base_conversion_rate_percent",
        "tracking_links",
        "base_conversion_rate >= 0 AND base_conversion_rate <= 100",
    )
    op.create_check_constraint(
        "ck_tracking_links_min_sample_size_positive",
        "tracking_links",
        "min_sample_size >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_tracking_links_min_sample_size_positive",
        "tracking_links",
        type_="check",
    )
    op.drop_constraint(
        "ck_tracking_links_base_conversion_rate_percent",
        "tracking_links",
        type_="check",
    )
    op.drop_column("tracking_links", "min_sample_size")
    op.drop_column("tracking_links", "base_conversion_rate")
