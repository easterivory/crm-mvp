"""operator workspace foundation

Revision ID: 20260601_0022
Revises: 20260601_0021
Create Date: 2026-06-01 12:40:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260601_0022"
down_revision = "20260601_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chats",
        sa.Column("last_client_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "chats",
        sa.Column("last_operator_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "chats",
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "chats",
        sa.Column("unanswered_minutes", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_chats_unanswered_minutes_nonnegative",
        "chats",
        "unanswered_minutes >= 0",
    )
    op.create_index("ix_chats_last_client_message_at", "chats", ["last_client_message_at"])
    op.create_index("ix_chats_last_operator_message_at", "chats", ["last_operator_message_at"])
    op.create_index("ix_chats_is_read", "chats", ["is_read"])
    op.create_index("ix_chats_project_is_read", "chats", ["project_id", "is_read"])

    op.create_table(
        "project_snippets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(length=30), server_default="telegram", nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("file_id", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("channel IN ('telegram')", name="ck_project_snippets_channel"),
        sa.CheckConstraint(
            "type IN ('text','photo','video','voice','video_note','document')",
            name="ck_project_snippets_type",
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_project_snippets_name_not_blank"),
        sa.CheckConstraint(
            "(type <> 'text') OR (content IS NOT NULL AND length(btrim(content)) > 0)",
            name="ck_project_snippets_text_content_required",
        ),
        sa.CheckConstraint(
            "(type = 'text') OR (file_id IS NOT NULL AND length(btrim(file_id)) > 0)",
            name="ck_project_snippets_media_file_required",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_snippets_project_id", "project_snippets", ["project_id"])
    op.create_index("ix_project_snippets_project_type", "project_snippets", ["project_id", "type"])
    op.create_index("ix_project_snippets_project_channel", "project_snippets", ["project_id", "channel"])
    op.create_index("ix_project_snippets_created_at", "project_snippets", ["created_at"])

    op.create_table(
        "chat_event_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('status_change','tag_added','manager_assigned','SLA_breached','note_added')",
            name="ck_chat_event_logs_event_type",
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_event_logs_chat_id", "chat_event_logs", ["chat_id"])
    op.create_index("ix_chat_event_logs_user_id", "chat_event_logs", ["user_id"])
    op.create_index("ix_chat_event_logs_event_type", "chat_event_logs", ["event_type"])
    op.create_index("ix_chat_event_logs_created_at", "chat_event_logs", ["created_at"])
    op.create_index("ix_chat_event_logs_chat_created_at", "chat_event_logs", ["chat_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_event_logs_chat_created_at", table_name="chat_event_logs")
    op.drop_index("ix_chat_event_logs_created_at", table_name="chat_event_logs")
    op.drop_index("ix_chat_event_logs_event_type", table_name="chat_event_logs")
    op.drop_index("ix_chat_event_logs_user_id", table_name="chat_event_logs")
    op.drop_index("ix_chat_event_logs_chat_id", table_name="chat_event_logs")
    op.drop_table("chat_event_logs")

    op.drop_index("ix_project_snippets_created_at", table_name="project_snippets")
    op.drop_index("ix_project_snippets_project_channel", table_name="project_snippets")
    op.drop_index("ix_project_snippets_project_type", table_name="project_snippets")
    op.drop_index("ix_project_snippets_project_id", table_name="project_snippets")
    op.drop_table("project_snippets")

    op.drop_index("ix_chats_project_is_read", table_name="chats")
    op.drop_index("ix_chats_is_read", table_name="chats")
    op.drop_index("ix_chats_last_operator_message_at", table_name="chats")
    op.drop_index("ix_chats_last_client_message_at", table_name="chats")
    op.drop_constraint("ck_chats_unanswered_minutes_nonnegative", "chats", type_="check")
    op.drop_column("chats", "unanswered_minutes")
    op.drop_column("chats", "is_read")
    op.drop_column("chats", "last_operator_message_at")
    op.drop_column("chats", "last_client_message_at")
