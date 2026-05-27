"""Add chat filter presets and search indexes.

Revision ID: 20260528_0014
Revises: 20260526_0013
Create Date: 2026-05-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260528_0014"
down_revision = "20260526_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_filter_presets",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "filters_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "user_id",
            "name",
            name="uq_chat_filter_presets_project_user_name",
        ),
    )
    op.create_index("ix_chat_filter_presets_project_id", "chat_filter_presets", ["project_id"])
    op.create_index("ix_chat_filter_presets_user_id", "chat_filter_presets", ["user_id"])
    op.create_index(
        "ix_chat_filter_presets_project_shared",
        "chat_filter_presets",
        ["project_id", "is_shared"],
    )

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_messages_body_trgm "
        "ON messages USING gin (lower(coalesce(body, '')) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_messages_caption_trgm "
        "ON messages USING gin (lower(coalesce(caption, '')) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_leads_name_trgm "
        "ON leads USING gin (lower(coalesce(name, '')) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_leads_phone_trgm "
        "ON leads USING gin (lower(coalesce(phone, '')) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_leads_username_trgm "
        "ON leads USING gin (lower(coalesce(username, '')) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chats_external_chat_id_trgm "
        "ON chats USING gin (lower(coalesce(external_chat_id, '')) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chats_external_user_id_trgm "
        "ON chats USING gin (lower(coalesce(external_user_id, '')) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_links_title_trgm "
        "ON tracking_links USING gin (lower(coalesce(title, '')) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_links_code_trgm "
        "ON tracking_links USING gin (lower(coalesce(code, '')) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_links_buyer_name_trgm "
        "ON tracking_links USING gin (lower(coalesce(buyer_name, '')) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tracking_links_buyer_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_tracking_links_code_trgm")
    op.execute("DROP INDEX IF EXISTS ix_tracking_links_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_chats_external_user_id_trgm")
    op.execute("DROP INDEX IF EXISTS ix_chats_external_chat_id_trgm")
    op.execute("DROP INDEX IF EXISTS ix_leads_username_trgm")
    op.execute("DROP INDEX IF EXISTS ix_leads_phone_trgm")
    op.execute("DROP INDEX IF EXISTS ix_leads_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_messages_caption_trgm")
    op.execute("DROP INDEX IF EXISTS ix_messages_body_trgm")
    op.drop_index("ix_chat_filter_presets_project_shared", table_name="chat_filter_presets")
    op.drop_index("ix_chat_filter_presets_user_id", table_name="chat_filter_presets")
    op.drop_index("ix_chat_filter_presets_project_id", table_name="chat_filter_presets")
    op.drop_table("chat_filter_presets")
