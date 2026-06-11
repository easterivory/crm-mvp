"""broadcast archive, bot settings, bot audit logs and telegram login

Revision ID: 20260609_0030
Revises: 20260609_0029
Create Date: 2026-06-09 01:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260609_0030"
down_revision = "20260609_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "broadcasts",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_broadcasts_is_deleted", "broadcasts", ["is_deleted"])
    op.create_index(
        "ix_broadcasts_project_is_deleted",
        "broadcasts",
        ["project_id", "is_deleted"],
    )

    op.add_column("bots", sa.Column("crm_description", sa.Text(), nullable=True))
    op.add_column("bots", sa.Column("telegram_description", sa.Text(), nullable=True))
    op.add_column("bots", sa.Column("telegram_about", sa.Text(), nullable=True))

    op.create_table(
        "bot_config_audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("bot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bot_config_audit_logs_bot_id",
        "bot_config_audit_logs",
        ["bot_id"],
    )
    op.create_index(
        "ix_bot_config_audit_logs_user_id",
        "bot_config_audit_logs",
        ["user_id"],
    )
    op.create_index(
        "ix_bot_config_audit_logs_action_type",
        "bot_config_audit_logs",
        ["action_type"],
    )
    op.create_index(
        "ix_bot_config_audit_logs_created_at",
        "bot_config_audit_logs",
        ["created_at"],
    )

    op.add_column("users", sa.Column("telegram_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_column("users", "telegram_id")

    op.drop_index("ix_bot_config_audit_logs_created_at", table_name="bot_config_audit_logs")
    op.drop_index("ix_bot_config_audit_logs_action_type", table_name="bot_config_audit_logs")
    op.drop_index("ix_bot_config_audit_logs_user_id", table_name="bot_config_audit_logs")
    op.drop_index("ix_bot_config_audit_logs_bot_id", table_name="bot_config_audit_logs")
    op.drop_table("bot_config_audit_logs")

    op.drop_column("bots", "telegram_about")
    op.drop_column("bots", "telegram_description")
    op.drop_column("bots", "crm_description")

    op.drop_index("ix_broadcasts_project_is_deleted", table_name="broadcasts")
    op.drop_index("ix_broadcasts_is_deleted", table_name="broadcasts")
    op.drop_column("broadcasts", "is_deleted")
