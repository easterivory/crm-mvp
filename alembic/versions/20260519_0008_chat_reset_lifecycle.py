"""add chat reset lifecycle fields

Revision ID: 20260519_0008
Revises: 20260517_0007
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260519_0008"
down_revision: Union[str, None] = "20260517_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE chats ADD COLUMN IF NOT EXISTS reset_at TIMESTAMP WITH TIME ZONE")
    op.execute(
        "ALTER TABLE chats ADD COLUMN IF NOT EXISTS "
        "reset_count INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE chats ADD COLUMN IF NOT EXISTS "
        "current_cycle_started_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_chats_reset_at ON chats (reset_at)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chats_current_cycle_started_at "
        "ON chats (current_cycle_started_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chats_current_cycle_started_at")
    op.execute("DROP INDEX IF EXISTS ix_chats_reset_at")
    op.execute("ALTER TABLE chats DROP COLUMN IF EXISTS current_cycle_started_at")
    op.execute("ALTER TABLE chats DROP COLUMN IF EXISTS reset_count")
    op.execute("ALTER TABLE chats DROP COLUMN IF EXISTS reset_at")
