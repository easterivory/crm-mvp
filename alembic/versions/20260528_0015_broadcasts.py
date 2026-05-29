"""Add broadcasts foundation.

Revision ID: 20260528_0015
Revises: 20260528_0014
Create Date: 2026-05-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260528_0015"
down_revision = "20260528_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broadcasts",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "content_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "audience_filter_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("audience_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("schedule_type", sa.String(length=20), nullable=False, server_default="now"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone_mode", sa.String(length=30), nullable=False, server_default="project"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft','audience_ready','scheduled','sending','paused','sent','failed','cancelled')",
            name="ck_broadcasts_status",
        ),
        sa.CheckConstraint(
            "schedule_type IN ('now','scheduled')",
            name="ck_broadcasts_schedule_type",
        ),
        sa.CheckConstraint(
            "timezone_mode IN ('project','lead_local','fixed')",
            name="ck_broadcasts_timezone_mode",
        ),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_broadcasts_project_id", "broadcasts", ["project_id"])
    op.create_index("ix_broadcasts_bot_id", "broadcasts", ["bot_id"])
    op.create_index("ix_broadcasts_status", "broadcasts", ["status"])
    op.create_index("ix_broadcasts_scheduled_at", "broadcasts", ["scheduled_at"])
    op.create_index("ix_broadcasts_created_by_user_id", "broadcasts", ["created_by_user_id"])

    op.create_table(
        "broadcast_recipients",
        sa.Column("broadcast_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','sent','failed','skipped')",
            name="ck_broadcast_recipients_status",
        ),
        sa.ForeignKeyConstraint(["broadcast_id"], ["broadcasts.id"]),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("broadcast_id", "chat_id", name="uq_broadcast_recipients_broadcast_chat"),
    )
    op.create_index("ix_broadcast_recipients_broadcast_id", "broadcast_recipients", ["broadcast_id"])
    op.create_index("ix_broadcast_recipients_chat_id", "broadcast_recipients", ["chat_id"])
    op.create_index("ix_broadcast_recipients_lead_id", "broadcast_recipients", ["lead_id"])
    op.create_index("ix_broadcast_recipients_status", "broadcast_recipients", ["status"])
    op.create_index(
        "ix_broadcast_recipients_pending",
        "broadcast_recipients",
        ["broadcast_id", "status"],
    )

    op.create_table(
        "broadcast_templates",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "content_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_broadcast_templates_project_id", "broadcast_templates", ["project_id"])
    op.create_index(
        "ix_broadcast_templates_created_by_user_id",
        "broadcast_templates",
        ["created_by_user_id"],
    )

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
            "media_type IN ('photo','video','document')",
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


def downgrade() -> None:
    op.drop_index("ix_broadcast_uploads_expires_at", table_name="broadcast_uploads")
    op.drop_index("ix_broadcast_uploads_status", table_name="broadcast_uploads")
    op.drop_index("ix_broadcast_uploads_created_by_user_id", table_name="broadcast_uploads")
    op.drop_index("ix_broadcast_uploads_project_id", table_name="broadcast_uploads")
    op.drop_table("broadcast_uploads")

    op.drop_index("ix_broadcast_templates_created_by_user_id", table_name="broadcast_templates")
    op.drop_index("ix_broadcast_templates_project_id", table_name="broadcast_templates")
    op.drop_table("broadcast_templates")

    op.drop_index("ix_broadcast_recipients_pending", table_name="broadcast_recipients")
    op.drop_index("ix_broadcast_recipients_status", table_name="broadcast_recipients")
    op.drop_index("ix_broadcast_recipients_lead_id", table_name="broadcast_recipients")
    op.drop_index("ix_broadcast_recipients_chat_id", table_name="broadcast_recipients")
    op.drop_index("ix_broadcast_recipients_broadcast_id", table_name="broadcast_recipients")
    op.drop_table("broadcast_recipients")

    op.drop_index("ix_broadcasts_created_by_user_id", table_name="broadcasts")
    op.drop_index("ix_broadcasts_scheduled_at", table_name="broadcasts")
    op.drop_index("ix_broadcasts_status", table_name="broadcasts")
    op.drop_index("ix_broadcasts_bot_id", table_name="broadcasts")
    op.drop_index("ix_broadcasts_project_id", table_name="broadcasts")
    op.drop_table("broadcasts")
