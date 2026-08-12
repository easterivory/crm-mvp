"""preserve Facebook attribution across Telegram channel joins

Revision ID: 20260812_0073
Revises: 20260811_0072
Create Date: 2026-08-12 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260812_0073"
down_revision = "20260811_0072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "telegram_channel_invite_links",
        sa.Column(
            "is_attribution_session",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "telegram_channel_invite_links",
        sa.Column("lander_start_key", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "telegram_channel_invite_links",
        sa.Column(
            "attribution_data_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "telegram_channel_invite_links",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "telegram_channel_invite_links",
        sa.Column("claimed_by_telegram_user_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "telegram_channel_invite_links",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_channel_invite_links_lander_start_key",
        "telegram_channel_invite_links",
        ["tracking_link_id", "lander_start_key"],
        unique=True,
    )
    op.create_index(
        "ix_channel_invite_links_attribution_expires",
        "telegram_channel_invite_links",
        ["expires_at"],
        unique=False,
    )

    for table_name in (
        "telegram_channel_subscriptions",
        "telegram_channel_subscription_events",
    ):
        op.add_column(
            table_name,
            sa.Column(
                "attribution_data_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    op.drop_column(
        "telegram_channel_subscription_events",
        "attribution_data_json",
    )
    op.drop_column("telegram_channel_subscriptions", "attribution_data_json")
    op.drop_index(
        "ix_channel_invite_links_attribution_expires",
        table_name="telegram_channel_invite_links",
    )
    op.drop_index(
        "uq_channel_invite_links_lander_start_key",
        table_name="telegram_channel_invite_links",
    )
    op.drop_column("telegram_channel_invite_links", "expires_at")
    op.drop_column("telegram_channel_invite_links", "claimed_at")
    op.drop_column(
        "telegram_channel_invite_links",
        "claimed_by_telegram_user_id",
    )
    op.drop_column("telegram_channel_invite_links", "attribution_data_json")
    op.drop_column("telegram_channel_invite_links", "lander_start_key")
    op.drop_column("telegram_channel_invite_links", "is_attribution_session")
