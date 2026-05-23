"""add Telegram identity and lazy media metadata

Revision ID: 20260521_0011
Revises: 20260520_0010
Create Date: 2026-05-21
"""

from alembic import op


revision = "20260521_0011"
down_revision = "20260520_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE bots ADD COLUMN IF NOT EXISTS telegram_bot_id BIGINT")
    op.execute("ALTER TABLE bots ADD COLUMN IF NOT EXISTS telegram_first_name VARCHAR(255)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bots_telegram_bot_id "
        "ON bots(telegram_bot_id)"
    )

    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS caption TEXT")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS telegram_file_id VARCHAR(512)")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS file_unique_id VARCHAR(255)")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS file_name VARCHAR(512)")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS mime_type VARCHAR(255)")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS file_size INTEGER")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS media_group_id VARCHAR(255)")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS raw_payload_json JSONB")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_messages_telegram_file_id "
        "ON messages(telegram_file_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_messages_telegram_file_id")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS raw_payload_json")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS media_group_id")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS file_size")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS mime_type")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS file_name")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS file_unique_id")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS telegram_file_id")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS caption")

    op.execute("DROP INDEX IF EXISTS ix_bots_telegram_bot_id")
    op.execute("ALTER TABLE bots DROP COLUMN IF EXISTS telegram_first_name")
    op.execute("ALTER TABLE bots DROP COLUMN IF EXISTS telegram_bot_id")
