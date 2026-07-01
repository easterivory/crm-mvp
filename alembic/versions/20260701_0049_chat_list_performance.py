"""chat list performance indexes

Revision ID: 20260701_0049
Revises: 20260701_0048
Create Date: 2026-07-01
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260701_0049"
down_revision: Union[str, None] = "20260701_0048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chats_project_active_last_message "
        "ON chats (project_id, last_message_at DESC, id DESC) "
        "WHERE is_deleted = false AND reset_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_messages_chat_created_desc "
        "ON messages (chat_id, created_at DESC, id DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_messages_chat_created_desc")
    op.execute("DROP INDEX IF EXISTS ix_chats_project_active_last_message")
