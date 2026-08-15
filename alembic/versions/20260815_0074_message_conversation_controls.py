"""add reply, edit, and soft-delete metadata to messages

Revision ID: 20260815_0074
Revises: 20260812_0073
Create Date: 2026-08-15 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260815_0074"
down_revision = "20260812_0073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "reply_to_message_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "messages",
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_messages_reply_to_message_id_messages",
        "messages",
        "messages",
        ["reply_to_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_messages_reply_to_message_id",
        "messages",
        ["reply_to_message_id"],
        unique=False,
    )
    op.create_index(
        "ix_messages_chat_deleted_created",
        "messages",
        ["chat_id", "deleted_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_messages_chat_deleted_created", table_name="messages")
    op.drop_index("ix_messages_reply_to_message_id", table_name="messages")
    op.drop_constraint(
        "fk_messages_reply_to_message_id_messages",
        "messages",
        type_="foreignkey",
    )
    op.drop_column("messages", "deleted_at")
    op.drop_column("messages", "edited_at")
    op.drop_column("messages", "reply_to_message_id")
