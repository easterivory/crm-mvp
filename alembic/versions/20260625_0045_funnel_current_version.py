"""funnel current published version

Revision ID: 20260625_0045
Revises: 20260625_0044
Create Date: 2026-06-25 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260625_0045"
down_revision = "20260625_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "funnels",
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_funnels_current_version_id",
        "funnels",
        ["current_version_id"],
    )
    op.create_foreign_key(
        "fk_funnels_current_version_id_funnel_versions",
        "funnels",
        "funnel_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        """
        WITH latest AS (
            SELECT DISTINCT ON (funnel_id)
                id,
                funnel_id
            FROM funnel_versions
            WHERE status = 'published'
            ORDER BY funnel_id, published_at DESC NULLS LAST, version_number DESC
        )
        UPDATE funnels
        SET current_version_id = latest.id
        FROM latest
        WHERE latest.funnel_id = funnels.id
          AND funnels.current_version_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_funnels_current_version_id_funnel_versions",
        "funnels",
        type_="foreignkey",
    )
    op.drop_index("ix_funnels_current_version_id", table_name="funnels")
    op.drop_column("funnels", "current_version_id")
