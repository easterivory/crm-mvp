"""add opt-in Telegram user account transport

Revision ID: 20260822_0075
Revises: 20260815_0074
Create Date: 2026-08-22 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260822_0075"
down_revision = "20260815_0074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chats",
        sa.Column("external_access_hash", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "bots",
        sa.Column(
            "transport_type",
            sa.String(length=32),
            nullable=False,
            server_default="bot_api",
        ),
    )
    op.create_check_constraint(
        "ck_bots_transport_type",
        "bots",
        "transport_type IN ('bot_api', 'user_mtproto')",
    )
    op.create_index(
        "ix_bots_transport_type",
        "bots",
        ["transport_type"],
        unique=False,
    )

    op.create_table(
        "telegram_user_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("api_id", sa.BigInteger(), nullable=False),
        sa.Column("api_hash_encrypted", sa.Text(), nullable=False),
        sa.Column("api_hash_last_four", sa.String(length=4), nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=False),
        sa.Column("session_encrypted", sa.Text(), nullable=True),
        sa.Column("phone_code_hash_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "auth_status",
            sa.String(length=32),
            nullable=False,
            server_default="disconnected",
        ),
        sa.Column(
            "connection_status",
            sa.String(length=32),
            nullable=False,
            server_default="disconnected",
        ),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_first_name", sa.String(length=255), nullable=True),
        sa.Column("telegram_last_name", sa.String(length=255), nullable=True),
        sa.Column("telegram_username", sa.String(length=255), nullable=True),
        sa.Column("auth_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "auth_status IN ('disconnected', 'awaiting_code', "
            "'awaiting_password', 'authorized', 'error')",
            name="ck_telegram_user_connections_auth_status",
        ),
        sa.CheckConstraint(
            "connection_status IN ('disconnected', 'connecting', "
            "'connected', 'error')",
            name="ck_telegram_user_connections_connection_status",
        ),
        sa.ForeignKeyConstraint(
            ["bot_id"],
            ["bots.id"],
            name="fk_telegram_user_connections_bot_id_bots",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bot_id", name="uq_telegram_user_connections_bot_id"),
    )
    op.create_index(
        "ix_telegram_user_connections_auth_status",
        "telegram_user_connections",
        ["auth_status"],
        unique=False,
    )
    op.create_index(
        "ix_telegram_user_connections_connection_status",
        "telegram_user_connections",
        ["connection_status"],
        unique=False,
    )
    op.create_index(
        "ix_telegram_user_connections_telegram_user_id",
        "telegram_user_connections",
        ["telegram_user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telegram_user_connections_telegram_user_id",
        table_name="telegram_user_connections",
    )
    op.drop_index(
        "ix_telegram_user_connections_connection_status",
        table_name="telegram_user_connections",
    )
    op.drop_index(
        "ix_telegram_user_connections_auth_status",
        table_name="telegram_user_connections",
    )
    op.drop_table("telegram_user_connections")
    op.drop_index("ix_bots_transport_type", table_name="bots")
    op.drop_constraint("ck_bots_transport_type", "bots", type_="check")
    op.drop_column("bots", "transport_type")
    op.drop_column("chats", "external_access_hash")
