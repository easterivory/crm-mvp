"""message operator author

Revision ID: 20260601_0023
Revises: 20260601_0022
Create Date: 2026-06-01 13:05:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260601_0023"
down_revision = "20260601_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_messages_operator_id_users",
        "messages",
        "users",
        ["operator_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_messages_operator_id", "messages", ["operator_id"])
    op.execute(
        """
        UPDATE messages
        SET operator_id = sender_id
        WHERE sender_type = 'manager'
          AND sender_id IS NOT NULL
          AND operator_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_messages_operator_id", table_name="messages")
    op.drop_constraint("fk_messages_operator_id_users", "messages", type_="foreignkey")
    op.drop_column("messages", "operator_id")
