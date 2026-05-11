"""isolate chats by bot

Revision ID: 20260511_0004
Revises: 20260510_0003
Create Date: 2026-05-11
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260511_0004"
down_revision: Union[str, None] = "20260510_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE chats ADD COLUMN IF NOT EXISTS bot_id UUID NULL")
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
                    AND ft.relname = 'bots'
                    AND a.attname = 'bot_id'
            ) THEN
                ALTER TABLE chats
                    ADD CONSTRAINT fk_chats_bot_id_bots
                    FOREIGN KEY (bot_id) REFERENCES bots(id);
            END IF;
        END $$;
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_chats_bot_id ON chats (bot_id)")
    op.execute("ALTER TABLE chats DROP CONSTRAINT IF EXISTS uq_chats_project_external")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_chats_project_bot_external'
            ) THEN
                ALTER TABLE chats
                    ADD CONSTRAINT uq_chats_project_bot_external
                    UNIQUE (project_id, bot_id, external_chat_id);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE chats DROP CONSTRAINT IF EXISTS uq_chats_project_bot_external")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_chats_project_external'
            ) THEN
                ALTER TABLE chats
                    ADD CONSTRAINT uq_chats_project_external
                    UNIQUE (project_id, external_chat_id);
            END IF;
        END $$;
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_chats_bot_id")
    op.execute("ALTER TABLE chats DROP CONSTRAINT IF EXISTS fk_chats_bot_id_bots")
    op.execute("ALTER TABLE chats DROP COLUMN IF EXISTS bot_id")
