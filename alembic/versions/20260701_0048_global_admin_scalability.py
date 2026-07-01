"""global admin, Telegram settings, and conversion alert state

Revision ID: 20260701_0048
Revises: 20260626_0047
Create Date: 2026-07-01 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260701_0048"
down_revision = "20260626_0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO system_settings (key, value)
        VALUES
            ('tg_backup_bot_token', NULL),
            ('tg_backup_channel_id', NULL),
            ('is_tg_backup_enabled', 'false'),
            ('admin_bot_token', NULL)
        ON CONFLICT (key) DO NOTHING
        """
    )

    op.execute(
        """
        UPDATE users
        SET role_id = roles.id,
            project_id = NULL,
            is_deleted = FALSE
        FROM roles
        WHERE lower(users.email) = 'superadmin@testcrm.dev'
          AND roles.name = 'super_admin'
        """
    )
    op.execute(
        """
        DELETE FROM user_project_accesses
        USING users
        WHERE user_project_accesses.user_id = users.id
          AND lower(users.email) = 'superadmin@testcrm.dev'
        """
    )

    op.create_table(
        "tracking_conversion_alert_states",
        sa.Column("tracking_link_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_status", sa.String(length=32), nullable=False),
        sa.Column("low_cr_alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tracking_link_id"],
            ["tracking_links.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tracking_link_id"),
    )


def downgrade() -> None:
    op.drop_table("tracking_conversion_alert_states")
    op.execute(
        """
        DELETE FROM system_settings
        WHERE key IN (
            'tg_backup_bot_token',
            'tg_backup_channel_id',
            'is_tg_backup_enabled',
            'admin_bot_token'
        )
        """
    )
