"""add tracking costs and traffic event impressions

Revision ID: 20260510_0003
Revises: 20260510_0002
Create Date: 2026-05-10
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260510_0003"
down_revision: Union[str, None] = "20260510_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tracking_links
            ADD COLUMN IF NOT EXISTS cost_model VARCHAR(20) NOT NULL DEFAULT 'fix_pdp',
            ADD COLUMN IF NOT EXISTS price_per_unit NUMERIC(12, 2) NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS spend NUMERIC(12, 2) NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_tracking_links_cost_model'
            ) THEN
                ALTER TABLE tracking_links
                    ADD CONSTRAINT ck_tracking_links_cost_model
                    CHECK (cost_model IN ('fix_pdp', 'cpm', 'cpa'));
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tracking_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES projects(id),
            tracking_link_id UUID NOT NULL REFERENCES tracking_links(id),
            clicks INTEGER NOT NULL DEFAULT 0,
            impressions INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_events_project_id "
        "ON tracking_events (project_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_events_tracking_link_id "
        "ON tracking_events (tracking_link_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tracking_events_tracking_link_id")
    op.execute("DROP INDEX IF EXISTS ix_tracking_events_project_id")
    op.execute("DROP TABLE IF EXISTS tracking_events")
    op.execute(
        "ALTER TABLE tracking_links DROP CONSTRAINT IF EXISTS ck_tracking_links_cost_model"
    )
    op.execute("ALTER TABLE tracking_links DROP COLUMN IF EXISTS spend")
    op.execute("ALTER TABLE tracking_links DROP COLUMN IF EXISTS price_per_unit")
    op.execute("ALTER TABLE tracking_links DROP COLUMN IF EXISTS cost_model")
