"""lander click buckets

Revision ID: 20260712_0058
Revises: 20260712_0057
Create Date: 2026-07-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260712_0058"
down_revision = "20260712_0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tracking_events",
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_tracking_events_link_bucket",
        "tracking_events",
        ["tracking_link_id", "bucket_start"],
    )
    op.create_index(
        "ix_tracking_events_bucket_start",
        "tracking_events",
        ["bucket_start"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tracking_events_bucket_start", table_name="tracking_events")
    op.drop_constraint(
        "uq_tracking_events_link_bucket",
        "tracking_events",
        type_="unique",
    )
    op.drop_column("tracking_events", "bucket_start")
