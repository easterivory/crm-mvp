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


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _check_constraint_exists(table_name: str, constraint_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return constraint_name in {
        constraint["name"] for constraint in inspector.get_check_constraints(table_name)
    }


def _create_broadcast_uploads_table() -> None:
    op.create_table(
        "broadcast_uploads",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("file_name", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=30), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="uploaded"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "media_type IN ('photo','video','document','voice','video_note')",
            name="ck_broadcast_uploads_media_type",
        ),
        sa.CheckConstraint(
            "status IN ('uploaded','used','expired','deleted')",
            name="ck_broadcast_uploads_status",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_broadcast_uploads_project_id", "broadcast_uploads", ["project_id"])
    op.create_index(
        "ix_broadcast_uploads_created_by_user_id",
        "broadcast_uploads",
        ["created_by_user_id"],
    )
    op.create_index("ix_broadcast_uploads_status", "broadcast_uploads", ["status"])
    op.create_index("ix_broadcast_uploads_expires_at", "broadcast_uploads", ["expires_at"])


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

    if _table_exists("broadcast_uploads"):
        if _check_constraint_exists("broadcast_uploads", "ck_broadcast_uploads_media_type"):
            op.drop_constraint("ck_broadcast_uploads_media_type", "broadcast_uploads", type_="check")
        op.create_check_constraint(
            "ck_broadcast_uploads_media_type",
            "broadcast_uploads",
            "media_type IN ('photo','video','document','voice','video_note')",
        )
    else:
        _create_broadcast_uploads_table()


def downgrade() -> None:
    if _table_exists("broadcast_uploads"):
        if _check_constraint_exists("broadcast_uploads", "ck_broadcast_uploads_media_type"):
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
