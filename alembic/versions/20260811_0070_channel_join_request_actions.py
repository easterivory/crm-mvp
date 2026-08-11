"""add optional channel join-request actions

Revision ID: 20260811_0070
Revises: 20260811_0069
Create Date: 2026-08-11 21:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260811_0070"
down_revision = "20260811_0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tracking_links",
        sa.Column(
            "channel_request_message_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tracking_links",
        sa.Column("channel_request_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "tracking_links",
        sa.Column(
            "channel_auto_approve",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.add_column(
        "telegram_channel_subscription_events",
        sa.Column("request_message_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "telegram_channel_subscription_events",
        sa.Column(
            "auto_approve_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "telegram_channel_subscription_events",
        sa.Column("request_message_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "telegram_channel_subscription_events",
        sa.Column("request_approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "telegram_channel_subscription_events",
        sa.Column("request_action_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(
        "telegram_channel_subscription_events",
        "request_action_error",
    )
    op.drop_column(
        "telegram_channel_subscription_events",
        "request_approved_at",
    )
    op.drop_column(
        "telegram_channel_subscription_events",
        "request_message_sent_at",
    )
    op.drop_column(
        "telegram_channel_subscription_events",
        "auto_approve_requested",
    )
    op.drop_column(
        "telegram_channel_subscription_events",
        "request_message_text",
    )

    op.drop_column("tracking_links", "channel_auto_approve")
    op.drop_column("tracking_links", "channel_request_message")
    op.drop_column("tracking_links", "channel_request_message_enabled")
