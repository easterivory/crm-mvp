"""Add chat message uploads.

Revision ID: 20260529_0016
Revises: 20260528_0015
Create Date: 2026-05-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260529_0016"
down_revision = "20260528_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_uploads",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("file_name", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=30), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="uploaded"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "media_type IN ('photo','video','document')",
            name="ck_message_uploads_media_type",
        ),
        sa.CheckConstraint(
            "status IN ('uploaded','sent','failed','expired','deleted')",
            name="ck_message_uploads_status",
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["sent_message_id"], ["messages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_message_uploads_project_id", "message_uploads", ["project_id"])
    op.create_index("ix_message_uploads_chat_id", "message_uploads", ["chat_id"])
    op.create_index(
        "ix_message_uploads_created_by_user_id",
        "message_uploads",
        ["created_by_user_id"],
    )
    op.create_index("ix_message_uploads_status", "message_uploads", ["status"])
    op.create_index("ix_message_uploads_expires_at", "message_uploads", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_message_uploads_expires_at", table_name="message_uploads")
    op.drop_index("ix_message_uploads_status", table_name="message_uploads")
    op.drop_index("ix_message_uploads_created_by_user_id", table_name="message_uploads")
    op.drop_index("ix_message_uploads_chat_id", table_name="message_uploads")
    op.drop_index("ix_message_uploads_project_id", table_name="message_uploads")
    op.drop_table("message_uploads")
