"""snapshot tracking attribution on Telegram start messages

Revision ID: 20260811_0069
Revises: 20260811_0068
Create Date: 2026-08-11 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260811_0069"
down_revision = "20260811_0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "tracking_link_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_messages_tracking_link_id",
        "messages",
        "tracking_links",
        ["tracking_link_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_messages_tracking_link_created_at",
        "messages",
        ["tracking_link_id", "created_at"],
        unique=False,
    )

    # Preserve the attribution visible before this migration. New /start
    # messages snapshot their own source and no longer move between links when
    # a chat receives a newer campaign attribution.
    op.execute(
        """
        UPDATE messages AS message
        SET tracking_link_id = chat.tracking_link_id
        FROM chats AS chat
        WHERE message.chat_id = chat.id
          AND message.tracking_link_id IS NULL
          AND message.sender_type = 'user'
          AND message.message_type = 'text'
          AND (
              split_part(lower(trim(message.body)), ' ', 1) = '/start'
              OR split_part(lower(trim(message.body)), ' ', 1) LIKE '/start@%'
          )
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_messages_tracking_link_created_at",
        table_name="messages",
    )
    op.drop_constraint(
        "fk_messages_tracking_link_id",
        "messages",
        type_="foreignkey",
    )
    op.drop_column("messages", "tracking_link_id")
