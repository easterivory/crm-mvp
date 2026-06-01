"""Add production broadcast fields.

Revision ID: 20260601_0024
Revises: 20260601_0023
Create Date: 2026-06-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260601_0024"
down_revision = "20260601_0023"
branch_labels = None
depends_on = None


NEW_BROADCAST_STATUSES = "'draft','scheduled','processing','paused','completed','cancelled'"
OLD_BROADCAST_STATUSES = (
    "'draft','audience_ready','scheduled','sending','paused','sent','failed','cancelled'"
)


def upgrade() -> None:
    op.drop_constraint("ck_broadcasts_status", "broadcasts", type_="check")
    op.execute(
        """
        UPDATE broadcasts
        SET status = CASE status
            WHEN 'audience_ready' THEN 'draft'
            WHEN 'sending' THEN 'processing'
            WHEN 'sent' THEN 'completed'
            WHEN 'failed' THEN 'completed'
            ELSE status
        END
        """
    )

    op.add_column(
        "broadcasts",
        sa.Column("total_recipients", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "broadcasts",
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "broadcasts",
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "broadcasts",
        sa.Column("snippet_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("broadcasts", sa.Column("media_type", sa.String(length=30), nullable=True))
    op.add_column("broadcasts", sa.Column("file_id", sa.String(length=512), nullable=True))
    op.add_column(
        "broadcasts",
        sa.Column("trigger_funnel_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "broadcasts",
        sa.Column("stop_on_reply", sa.Boolean(), nullable=False, server_default="false"),
    )

    op.execute("UPDATE broadcasts SET total_recipients = audience_count")
    op.execute(
        """
        WITH recipient_counts AS (
            SELECT
                broadcast_id,
                COUNT(*)::integer AS total,
                COUNT(*) FILTER (WHERE status = 'sent')::integer AS sent,
                COUNT(*) FILTER (WHERE status = 'failed')::integer AS failed
            FROM broadcast_recipients
            GROUP BY broadcast_id
        )
        UPDATE broadcasts AS b
        SET
            total_recipients = GREATEST(b.total_recipients, recipient_counts.total),
            sent_count = recipient_counts.sent,
            failed_count = recipient_counts.failed
        FROM recipient_counts
        WHERE b.id = recipient_counts.broadcast_id
        """
    )

    op.create_foreign_key(
        "fk_broadcasts_snippet_id_project_snippets",
        "broadcasts",
        "project_snippets",
        ["snippet_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_broadcasts_trigger_funnel_id_funnels",
        "broadcasts",
        "funnels",
        ["trigger_funnel_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_broadcasts_snippet_id", "broadcasts", ["snippet_id"])
    op.create_index("ix_broadcasts_trigger_funnel_id", "broadcasts", ["trigger_funnel_id"])
    op.create_index("ix_broadcasts_project_status", "broadcasts", ["project_id", "status"])

    op.create_check_constraint(
        "ck_broadcasts_status",
        "broadcasts",
        f"status IN ({NEW_BROADCAST_STATUSES})",
    )
    op.create_check_constraint(
        "ck_broadcasts_media_type",
        "broadcasts",
        "media_type IS NULL OR media_type IN ('text','photo','video','voice','video_note','document')",
    )
    op.create_check_constraint(
        "ck_broadcasts_total_recipients_nonnegative",
        "broadcasts",
        "total_recipients >= 0",
    )
    op.create_check_constraint(
        "ck_broadcasts_sent_count_nonnegative",
        "broadcasts",
        "sent_count >= 0",
    )
    op.create_check_constraint(
        "ck_broadcasts_failed_count_nonnegative",
        "broadcasts",
        "failed_count >= 0",
    )

    op.drop_constraint("ck_broadcast_uploads_media_type", "broadcast_uploads", type_="check")
    op.create_check_constraint(
        "ck_broadcast_uploads_media_type",
        "broadcast_uploads",
        "media_type IN ('photo','video','document','voice','video_note')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_broadcast_uploads_media_type", "broadcast_uploads", type_="check")
    op.execute(
        """
        UPDATE broadcast_uploads
        SET media_type = 'document'
        WHERE media_type IN ('voice','video_note')
        """
    )
    op.create_check_constraint(
        "ck_broadcast_uploads_media_type",
        "broadcast_uploads",
        "media_type IN ('photo','video','document')",
    )

    op.drop_constraint("ck_broadcasts_failed_count_nonnegative", "broadcasts", type_="check")
    op.drop_constraint("ck_broadcasts_sent_count_nonnegative", "broadcasts", type_="check")
    op.drop_constraint("ck_broadcasts_total_recipients_nonnegative", "broadcasts", type_="check")
    op.drop_constraint("ck_broadcasts_media_type", "broadcasts", type_="check")
    op.drop_constraint("ck_broadcasts_status", "broadcasts", type_="check")
    op.execute(
        """
        UPDATE broadcasts
        SET status = CASE status
            WHEN 'processing' THEN 'sending'
            WHEN 'completed' THEN 'sent'
            ELSE status
        END
        """
    )
    op.create_check_constraint(
        "ck_broadcasts_status",
        "broadcasts",
        f"status IN ({OLD_BROADCAST_STATUSES})",
    )

    op.drop_index("ix_broadcasts_project_status", table_name="broadcasts")
    op.drop_index("ix_broadcasts_trigger_funnel_id", table_name="broadcasts")
    op.drop_index("ix_broadcasts_snippet_id", table_name="broadcasts")
    op.drop_constraint("fk_broadcasts_trigger_funnel_id_funnels", "broadcasts", type_="foreignkey")
    op.drop_constraint(
        "fk_broadcasts_snippet_id_project_snippets",
        "broadcasts",
        type_="foreignkey",
    )
    op.drop_column("broadcasts", "stop_on_reply")
    op.drop_column("broadcasts", "trigger_funnel_id")
    op.drop_column("broadcasts", "file_id")
    op.drop_column("broadcasts", "media_type")
    op.drop_column("broadcasts", "snippet_id")
    op.drop_column("broadcasts", "failed_count")
    op.drop_column("broadcasts", "sent_count")
    op.drop_column("broadcasts", "total_recipients")
