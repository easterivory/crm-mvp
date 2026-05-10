"""add tracking links and bot usernames

Revision ID: 20260510_0002
Revises: 20260509_0001
Create Date: 2026-05-10
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260510_0002"
down_revision: Union[str, None] = "20260509_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Baseline migration imports current metadata via Base.metadata.create_all().
    # Keep this migration idempotent so fresh databases and upgraded databases
    # both reach the same schema.
    op.execute("ALTER TABLE bots ADD COLUMN IF NOT EXISTS bot_username VARCHAR(255)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bots_bot_username ON bots (bot_username)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tracking_links (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES projects(id),
            bot_id UUID NOT NULL REFERENCES bots(id),
            name VARCHAR(255) NOT NULL,
            ref_code VARCHAR(100) NOT NULL,
            target_step_id UUID NULL REFERENCES bot_steps(id),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT uq_tracking_links_ref_code UNIQUE (ref_code)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_links_project_id "
        "ON tracking_links (project_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_links_bot_id "
        "ON tracking_links (bot_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_links_target_step_id "
        "ON tracking_links (target_step_id)"
    )

    op.execute(
        "ALTER TABLE chats ADD COLUMN IF NOT EXISTS tracking_link_id UUID NULL"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_class ft ON ft.oid = c.confrelid
                JOIN pg_attribute a
                    ON a.attrelid = c.conrelid
                    AND a.attnum = ANY(c.conkey)
                WHERE c.contype = 'f'
                    AND t.relname = 'chats'
                    AND ft.relname = 'tracking_links'
                    AND a.attname = 'tracking_link_id'
            ) THEN
                ALTER TABLE chats
                    ADD CONSTRAINT fk_chats_tracking_link_id_tracking_links
                    FOREIGN KEY (tracking_link_id) REFERENCES tracking_links(id);
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chats_tracking_link_id "
        "ON chats (tracking_link_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chats_tracking_link_id")
    op.execute(
        """
        ALTER TABLE chats
        DROP CONSTRAINT IF EXISTS fk_chats_tracking_link_id_tracking_links
        """
    )
    op.execute("ALTER TABLE chats DROP COLUMN IF EXISTS tracking_link_id")

    op.execute("DROP TABLE IF EXISTS tracking_links")

    op.execute("DROP INDEX IF EXISTS ix_bots_bot_username")
    op.execute("ALTER TABLE bots DROP COLUMN IF EXISTS bot_username")
