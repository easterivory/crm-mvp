"""add chat blocking state

Revision ID: 20260623_0040
Revises: 20260622_0039
Create Date: 2026-06-23 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260623_0040"
down_revision = "20260622_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chats",
        sa.Column(
            "is_blocked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index("ix_chats_is_blocked", "chats", ["is_blocked"])


def downgrade() -> None:
    op.drop_index("ix_chats_is_blocked", table_name="chats")
    op.drop_column("chats", "is_blocked")
