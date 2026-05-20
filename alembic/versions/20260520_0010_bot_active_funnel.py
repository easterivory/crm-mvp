"""add active funnel pointers to bots

Revision ID: 20260520_0010
Revises: 20260520_0009
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260520_0010"
down_revision = "20260520_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bots",
        sa.Column("active_funnel_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "bots",
        sa.Column(
            "active_funnel_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_bots_active_funnel_id",
        "bots",
        ["active_funnel_id"],
    )
    op.create_index(
        "ix_bots_active_funnel_version_id",
        "bots",
        ["active_funnel_version_id"],
    )
    op.create_foreign_key(
        "fk_bots_active_funnel_id_funnels",
        "bots",
        "funnels",
        ["active_funnel_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_bots_active_funnel_version_id_funnel_versions",
        "bots",
        "funnel_versions",
        ["active_funnel_version_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_bots_active_funnel_version_id_funnel_versions",
        "bots",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_bots_active_funnel_id_funnels",
        "bots",
        type_="foreignkey",
    )
    op.drop_index("ix_bots_active_funnel_version_id", table_name="bots")
    op.drop_index("ix_bots_active_funnel_id", table_name="bots")
    op.drop_column("bots", "active_funnel_version_id")
    op.drop_column("bots", "active_funnel_id")
