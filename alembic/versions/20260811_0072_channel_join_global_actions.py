"""add durable global channel join actions

Revision ID: 20260811_0072
Revises: 20260811_0071
Create Date: 2026-08-11 22:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260811_0072"
down_revision = "20260811_0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "telegram_channel_subscription_events",
        sa.Column(
            "auto_start_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "telegram_channel_subscription_events",
        sa.Column(
            "funnel_start_processed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "telegram_channel_subscription_events",
        sa.Column("funnel_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "telegram_channel_subscription_events",
        sa.Column("funnel_start_chat_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "telegram_channel_subscription_events",
        sa.Column("funnel_start_error", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_channel_subscription_events_funnel_start_chat",
        "telegram_channel_subscription_events",
        "chats",
        ["funnel_start_chat_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_channel_subscription_events_funnel_start_chat",
        "telegram_channel_subscription_events",
        type_="foreignkey",
    )
    op.drop_column("telegram_channel_subscription_events", "funnel_start_error")
    op.drop_column("telegram_channel_subscription_events", "funnel_start_chat_id")
    op.drop_column("telegram_channel_subscription_events", "funnel_started_at")
    op.drop_column(
        "telegram_channel_subscription_events",
        "funnel_start_processed_at",
    )
    op.drop_column("telegram_channel_subscription_events", "auto_start_requested")
