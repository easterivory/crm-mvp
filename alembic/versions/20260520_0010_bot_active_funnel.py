"""add active funnel pointers to bots

Revision ID: 20260520_0010
Revises: 20260520_0009
Create Date: 2026-05-20
"""

from alembic import op


revision = "20260520_0010"
down_revision = "20260520_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE bots ADD COLUMN IF NOT EXISTS active_funnel_id UUID")
    op.execute(
        "ALTER TABLE bots ADD COLUMN IF NOT EXISTS active_funnel_version_id UUID"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bots_active_funnel_id "
        "ON bots(active_funnel_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bots_active_funnel_version_id "
        "ON bots(active_funnel_version_id)"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_bots_active_funnel_id_funnels'
            ) THEN
                ALTER TABLE bots
                    ADD CONSTRAINT fk_bots_active_funnel_id_funnels
                    FOREIGN KEY (active_funnel_id)
                    REFERENCES funnels(id)
                    ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_bots_active_funnel_version_id_funnel_versions'
            ) THEN
                ALTER TABLE bots
                    ADD CONSTRAINT fk_bots_active_funnel_version_id_funnel_versions
                    FOREIGN KEY (active_funnel_version_id)
                    REFERENCES funnel_versions(id)
                    ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE bots "
        "DROP CONSTRAINT IF EXISTS fk_bots_active_funnel_version_id_funnel_versions"
    )
    op.execute(
        "ALTER TABLE bots DROP CONSTRAINT IF EXISTS fk_bots_active_funnel_id_funnels"
    )
    op.execute("DROP INDEX IF EXISTS ix_bots_active_funnel_version_id")
    op.execute("DROP INDEX IF EXISTS ix_bots_active_funnel_id")
    op.execute("ALTER TABLE bots DROP COLUMN IF EXISTS active_funnel_version_id")
    op.execute("ALTER TABLE bots DROP COLUMN IF EXISTS active_funnel_id")
