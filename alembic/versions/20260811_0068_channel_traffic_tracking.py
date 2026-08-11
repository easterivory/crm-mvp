"""add channel traffic tracking

Revision ID: 20260811_0068
Revises: 20260728_0067
Create Date: 2026-08-11 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260811_0068"
down_revision = "20260728_0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_channels",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tracker_bot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "bot_is_admin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "can_invite_users",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_telegram_channels_project_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tracker_bot_id"],
            ["bots.id"],
            name="fk_telegram_channels_tracker_bot_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "telegram_chat_id",
            name="uq_telegram_channels_project_chat",
        ),
    )
    op.create_index(
        "ix_telegram_channels_project_id",
        "telegram_channels",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_telegram_channels_tracker_bot_id",
        "telegram_channels",
        ["tracker_bot_id"],
        unique=False,
    )
    op.create_index(
        "ix_telegram_channels_telegram_chat_id",
        "telegram_channels",
        ["telegram_chat_id"],
        unique=False,
    )

    op.add_column(
        "tracking_links",
        sa.Column(
            "destination_type",
            sa.String(length=16),
            server_default="bot",
            nullable=False,
        ),
    )
    op.add_column(
        "tracking_links",
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tracking_links",
        sa.Column(
            "channel_join_request",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_tracking_links_channel_id",
        "tracking_links",
        "telegram_channels",
        ["channel_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_tracking_links_channel_id",
        "tracking_links",
        ["channel_id"],
        unique=False,
    )
    op.create_index(
        "ix_tracking_links_destination_type",
        "tracking_links",
        ["destination_type"],
        unique=False,
    )
    op.create_check_constraint(
        "ck_tracking_links_destination_type",
        "tracking_links",
        "destination_type IN ('bot', 'channel')",
    )
    op.create_check_constraint(
        "ck_tracking_links_channel_destination",
        "tracking_links",
        "(destination_type = 'bot' AND channel_id IS NULL) OR "
        "(destination_type = 'channel' AND channel_id IS NOT NULL)",
    )

    op.create_table(
        "telegram_channel_invite_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tracking_link_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invite_link", sa.Text(), nullable=False),
        sa.Column("telegram_name", sa.String(length=64), nullable=True),
        sa.Column(
            "creates_join_request",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_current",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_channel_invite_links_project_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["telegram_channels.id"],
            name="fk_channel_invite_links_channel_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tracking_link_id"],
            ["tracking_links.id"],
            name="fk_channel_invite_links_tracking_link_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invite_link", name="uq_channel_invite_links_invite_link"),
    )
    op.create_index(
        "ix_channel_invite_links_channel_id",
        "telegram_channel_invite_links",
        ["channel_id"],
        unique=False,
    )
    op.create_index(
        "ix_channel_invite_links_tracking_link_id",
        "telegram_channel_invite_links",
        ["tracking_link_id"],
        unique=False,
    )

    op.create_table(
        "telegram_channel_subscriptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tracking_link_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tracker_bot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("first_joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_update_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'member', 'left', 'kicked')",
            name="ck_channel_subscriptions_status",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_channel_subscriptions_project_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["telegram_channels.id"],
            name="fk_channel_subscriptions_channel_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tracking_link_id"],
            ["tracking_links.id"],
            name="fk_channel_subscriptions_tracking_link_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tracker_bot_id"],
            ["bots.id"],
            name="fk_channel_subscriptions_tracker_bot_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "channel_id",
            "telegram_user_id",
            name="uq_channel_subscriptions_channel_user",
        ),
    )
    op.create_index(
        "ix_channel_subscriptions_project_status",
        "telegram_channel_subscriptions",
        ["project_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_channel_subscriptions_tracking_status",
        "telegram_channel_subscriptions",
        ["tracking_link_id", "status"],
        unique=False,
    )

    op.create_table(
        "telegram_channel_subscription_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tracking_link_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tracker_bot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_update_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("previous_status", sa.String(length=24), nullable=True),
        sa.Column("new_status", sa.String(length=24), nullable=True),
        sa.Column("invite_link", sa.Text(), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('join_request', 'join', 'leave', 'kick')",
            name="ck_channel_subscription_events_type",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_channel_subscription_events_project_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["telegram_channels.id"],
            name="fk_channel_subscription_events_channel_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tracking_link_id"],
            ["tracking_links.id"],
            name="fk_channel_subscription_events_tracking_link_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tracker_bot_id"],
            ["bots.id"],
            name="fk_channel_subscription_events_tracker_bot_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tracker_bot_id",
            "telegram_update_id",
            name="uq_channel_subscription_events_bot_update",
        ),
    )
    op.create_index(
        "ix_channel_subscription_events_link_type_time",
        "telegram_channel_subscription_events",
        ["tracking_link_id", "event_type", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_channel_subscription_events_channel_user",
        "telegram_channel_subscription_events",
        ["channel_id", "telegram_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_channel_subscription_events_channel_user",
        table_name="telegram_channel_subscription_events",
    )
    op.drop_index(
        "ix_channel_subscription_events_link_type_time",
        table_name="telegram_channel_subscription_events",
    )
    op.drop_table("telegram_channel_subscription_events")
    op.drop_index(
        "ix_channel_subscriptions_tracking_status",
        table_name="telegram_channel_subscriptions",
    )
    op.drop_index(
        "ix_channel_subscriptions_project_status",
        table_name="telegram_channel_subscriptions",
    )
    op.drop_table("telegram_channel_subscriptions")
    op.drop_index(
        "ix_channel_invite_links_tracking_link_id",
        table_name="telegram_channel_invite_links",
    )
    op.drop_index(
        "ix_channel_invite_links_channel_id",
        table_name="telegram_channel_invite_links",
    )
    op.drop_table("telegram_channel_invite_links")
    op.drop_constraint(
        "ck_tracking_links_channel_destination",
        "tracking_links",
        type_="check",
    )
    op.drop_constraint(
        "ck_tracking_links_destination_type",
        "tracking_links",
        type_="check",
    )
    op.drop_index("ix_tracking_links_destination_type", table_name="tracking_links")
    op.drop_index("ix_tracking_links_channel_id", table_name="tracking_links")
    op.drop_constraint(
        "fk_tracking_links_channel_id",
        "tracking_links",
        type_="foreignkey",
    )
    op.drop_column("tracking_links", "channel_join_request")
    op.drop_column("tracking_links", "channel_id")
    op.drop_column("tracking_links", "destination_type")
    op.drop_index("ix_telegram_channels_telegram_chat_id", table_name="telegram_channels")
    op.drop_index("ix_telegram_channels_tracker_bot_id", table_name="telegram_channels")
    op.drop_index("ix_telegram_channels_project_id", table_name="telegram_channels")
    op.drop_table("telegram_channels")
