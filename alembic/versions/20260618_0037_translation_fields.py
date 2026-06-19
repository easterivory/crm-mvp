"""translation fields

Revision ID: 20260618_0037
Revises: 20260614_0036
Create Date: 2026-06-18 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260618_0037"
down_revision = "20260614_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("operator_lang", sa.String(length=10), nullable=False, server_default="ru"),
    )
    op.add_column(
        "projects",
        sa.Column("default_client_lang", sa.String(length=10), nullable=False, server_default="en"),
    )
    op.add_column(
        "projects",
        sa.Column(
            "is_translation_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column("chats", sa.Column("client_lang", sa.String(length=10), nullable=True))
    op.add_column("messages", sa.Column("translated_text", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("original_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "original_text")
    op.drop_column("messages", "translated_text")
    op.drop_column("chats", "client_lang")
    op.drop_column("projects", "is_translation_enabled")
    op.drop_column("projects", "default_client_lang")
    op.drop_column("projects", "operator_lang")
