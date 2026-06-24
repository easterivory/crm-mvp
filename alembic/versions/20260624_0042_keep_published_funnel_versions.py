"""keep published funnel versions for explicit activation

Revision ID: 20260624_0042
Revises: 20260623_0041
Create Date: 2026-06-24 00:00:00.000000
"""
from __future__ import annotations

from alembic import op


revision = "20260624_0042"
down_revision = "20260623_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_funnel_versions_one_published_per_funnel")
    op.execute(
        """
        UPDATE funnel_versions AS version
        SET status = 'published', updated_at = now()
        FROM funnels AS funnel
        WHERE version.funnel_id = funnel.id
          AND funnel.status = 'active'
          AND version.status = 'archived'
          AND version.published_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY funnel_id
                    ORDER BY published_at DESC NULLS LAST, version_number DESC
                ) AS position
            FROM funnel_versions
            WHERE status = 'published'
        )
        UPDATE funnel_versions
        SET status = 'archived', updated_at = now()
        WHERE id IN (SELECT id FROM ranked WHERE position > 1)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_funnel_versions_one_published_per_funnel
        ON funnel_versions(funnel_id)
        WHERE status = 'published'
        """
    )
