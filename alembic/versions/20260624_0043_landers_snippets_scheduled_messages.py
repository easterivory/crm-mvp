"""editable landing events, media snippets, and scheduled chat messages

Revision ID: 20260624_0043
Revises: 20260624_0042
Create Date: 2026-06-24 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260624_0043"
down_revision = "20260624_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_landers",
        sa.Column(
            "meta_events_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "project_landers",
        sa.Column("auto_redirect_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )

    op.add_column("project_snippets", sa.Column("storage_path", sa.Text(), nullable=True))
    op.add_column("project_snippets", sa.Column("file_name", sa.String(length=512), nullable=True))
    op.add_column("project_snippets", sa.Column("mime_type", sa.String(length=255), nullable=True))
    op.add_column("project_snippets", sa.Column("file_size", sa.Integer(), nullable=True))
    op.drop_constraint("ck_project_snippets_media_file_required", "project_snippets", type_="check")
    op.create_check_constraint(
        "ck_project_snippets_media_file_required",
        "project_snippets",
        "(type = 'text') OR ((file_id IS NOT NULL AND length(btrim(file_id)) > 0) OR storage_path IS NOT NULL)",
    )

    op.create_table(
        "scheduled_messages",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("original_text", sa.Text(), nullable=True),
        sa.Column("media_type", sa.String(length=30), server_default="text", nullable=False),
        sa.Column("file_id", sa.String(length=512), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("file_name", sa.String(length=512), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("auto_translate", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','running','sent','failed','cancelled')",
            name="ck_scheduled_messages_status",
        ),
        sa.CheckConstraint(
            "media_type IN ('text','photo','video','voice','video_note','document')",
            name="ck_scheduled_messages_media_type",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["sent_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scheduled_messages_status_scheduled_at", "scheduled_messages", ["status", "scheduled_at"])
    op.create_index("ix_scheduled_messages_chat_id", "scheduled_messages", ["chat_id"])
    op.create_index("ix_scheduled_messages_project_id", "scheduled_messages", ["project_id"])
    op.create_index("ix_scheduled_messages_created_by_user_id", "scheduled_messages", ["created_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_scheduled_messages_created_by_user_id", table_name="scheduled_messages")
    op.drop_index("ix_scheduled_messages_project_id", table_name="scheduled_messages")
    op.drop_index("ix_scheduled_messages_chat_id", table_name="scheduled_messages")
    op.drop_index("ix_scheduled_messages_status_scheduled_at", table_name="scheduled_messages")
    op.drop_table("scheduled_messages")

    op.drop_constraint("ck_project_snippets_media_file_required", "project_snippets", type_="check")
    op.create_check_constraint(
        "ck_project_snippets_media_file_required",
        "project_snippets",
        "(type = 'text') OR (file_id IS NOT NULL AND length(btrim(file_id)) > 0)",
    )
    op.drop_column("project_snippets", "file_size")
    op.drop_column("project_snippets", "mime_type")
    op.drop_column("project_snippets", "file_name")
    op.drop_column("project_snippets", "storage_path")

    op.drop_column("project_landers", "auto_redirect_enabled")
    op.drop_column("project_landers", "meta_events_json")
