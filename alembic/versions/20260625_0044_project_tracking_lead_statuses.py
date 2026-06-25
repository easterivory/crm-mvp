"""project configurable tracking lead statuses

Revision ID: 20260625_0044
Revises: 20260624_0043
Create Date: 2026-06-25 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260625_0044"
down_revision = "20260624_0043"
branch_labels = None
depends_on = None


DEFAULT_TRACKING_LEAD_STATUSES = "'[\"submitted\",\"qualified\"]'::jsonb"


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "tracking_lead_status_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(DEFAULT_TRACKING_LEAD_STATUSES),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "tracking_lead_status_codes")
