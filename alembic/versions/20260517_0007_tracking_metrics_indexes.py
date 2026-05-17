"""add tracking metrics aggregation indexes

Revision ID: 20260517_0007
Revises: 20260517_0006
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260517_0007"
down_revision: Union[str, None] = "20260517_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_spends_link_date "
        "ON tracking_spends (tracking_link_id, spend_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_links_project_bot "
        "ON tracking_links (project_id, bot_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chats_tracking_created_at "
        "ON chats (tracking_link_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chats_project_bot_created_at "
        "ON chats (project_id, bot_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_leads_project_created_at "
        "ON leads (project_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_events_link_created_at "
        "ON tracking_events (tracking_link_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tracking_events_link_created_at")
    op.execute("DROP INDEX IF EXISTS ix_leads_project_created_at")
    op.execute("DROP INDEX IF EXISTS ix_chats_project_bot_created_at")
    op.execute("DROP INDEX IF EXISTS ix_chats_tracking_created_at")
    op.execute("DROP INDEX IF EXISTS ix_tracking_links_project_bot")
    op.execute("DROP INDEX IF EXISTS ix_tracking_spends_link_date")
