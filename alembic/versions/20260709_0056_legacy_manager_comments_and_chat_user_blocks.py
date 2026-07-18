"""manager comments and Telegram user block status (legacy revision id)

Revision ID: 20260709_0056
Revises: 20260705_0055
Create Date: 2026-07-09 00:00:00.000000

This revision id was already applied by an earlier production build.  It is
kept in the graph so those databases can continue upgrading without a manual
Alembic stamp.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260709_0056"
down_revision = "20260705_0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("manager_comment", sa.Text(), nullable=True))
    op.add_column(
        "chats",
        sa.Column(
            "is_blocked_by_user",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_chats_is_blocked_by_user",
        "chats",
        ["is_blocked_by_user"],
    )


def downgrade() -> None:
    op.drop_index("ix_chats_is_blocked_by_user", table_name="chats")
    op.drop_column("chats", "is_blocked_by_user")
    op.drop_column("leads", "manager_comment")
