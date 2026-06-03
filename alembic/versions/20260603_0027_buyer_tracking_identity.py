"""buyer_tracking_identity

Revision ID: 20260603_0027
Revises: 20260602_0026
Create Date: 2026-06-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260603_0027"
down_revision = "20260602_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("buyer_telegram_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("buyer_invite_token", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_users_buyer_telegram_id",
        "users",
        ["buyer_telegram_id"],
        unique=True,
    )
    op.create_index(
        "ix_users_buyer_invite_token",
        "users",
        ["buyer_invite_token"],
        unique=True,
    )

    op.add_column(
        "tracking_links",
        sa.Column("buyer_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tracking_links_buyer_id_users",
        "tracking_links",
        "users",
        ["buyer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_tracking_links_buyer_id",
        "tracking_links",
        ["buyer_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tracking_links_buyer_id", table_name="tracking_links")
    op.drop_constraint(
        "fk_tracking_links_buyer_id_users",
        "tracking_links",
        type_="foreignkey",
    )
    op.drop_column("tracking_links", "buyer_id")

    op.drop_index("ix_users_buyer_invite_token", table_name="users")
    op.drop_index("ix_users_buyer_telegram_id", table_name="users")
    op.drop_column("users", "buyer_invite_token")
    op.drop_column("users", "buyer_telegram_id")
