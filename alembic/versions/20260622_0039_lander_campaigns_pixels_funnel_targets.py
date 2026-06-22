"""lander campaigns, pixels and funnel target steps

Revision ID: 20260622_0039
Revises: 20260621_0038
Create Date: 2026-06-22 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260622_0039"
down_revision = "20260621_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_landers",
        sa.Column(
            "pixels_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "project_landers",
        sa.Column(
            "utm_defaults_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "tracking_links",
        sa.Column("target_funnel_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tracking_links",
        sa.Column("target_funnel_step_key", sa.String(length=100), nullable=True),
    )
    op.create_foreign_key(
        "fk_tracking_links_target_funnel_id",
        "tracking_links",
        "funnels",
        ["target_funnel_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_tracking_links_target_funnel_id",
        "tracking_links",
        ["target_funnel_id"],
    )
    op.create_index(
        "ix_tracking_links_target_funnel_step_key",
        "tracking_links",
        ["target_funnel_step_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_tracking_links_target_funnel_step_key", table_name="tracking_links")
    op.drop_index("ix_tracking_links_target_funnel_id", table_name="tracking_links")
    op.drop_constraint("fk_tracking_links_target_funnel_id", "tracking_links", type_="foreignkey")
    op.drop_column("tracking_links", "target_funnel_step_key")
    op.drop_column("tracking_links", "target_funnel_id")
    op.drop_column("project_landers", "utm_defaults_json")
    op.drop_column("project_landers", "pixels_json")
