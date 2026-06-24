"""add manager quality attribution and funnel pause

Revision ID: 20260623_0041
Revises: 20260623_0040
Create Date: 2026-06-23 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260623_0041"
down_revision = "20260623_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("handler_code", sa.String(length=4), nullable=True))
    op.create_check_constraint(
        "ck_users_handler_code_format",
        "users",
        "handler_code IS NULL OR handler_code ~ '^[0-9]{4}$'",
    )
    op.create_index(
        "uq_users_handler_code",
        "users",
        ["handler_code"],
        unique=True,
        postgresql_where=sa.text("handler_code IS NOT NULL"),
    )

    op.add_column(
        "chat_funnel_states",
        sa.Column("is_paused", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "chat_funnel_states",
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "chat_funnel_states",
        sa.Column("paused_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_chat_funnel_states_paused_by_user_id_users",
        "chat_funnel_states",
        "users",
        ["paused_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_chat_funnel_states_is_paused", "chat_funnel_states", ["is_paused"])

    op.add_column(
        "lead_submissions",
        sa.Column("submitted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("lead_submissions", sa.Column("is_valid", sa.Boolean(), nullable=True))
    op.add_column(
        "lead_submissions",
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_lead_submissions_submitted_by_user_id_users",
        "lead_submissions",
        "users",
        ["submitted_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_lead_submissions_submitted_by_user_id",
        "lead_submissions",
        ["submitted_by_user_id"],
    )
    op.create_index("ix_lead_submissions_is_valid", "lead_submissions", ["is_valid"])


def downgrade() -> None:
    op.drop_index("ix_lead_submissions_is_valid", table_name="lead_submissions")
    op.drop_index("ix_lead_submissions_submitted_by_user_id", table_name="lead_submissions")
    op.drop_constraint(
        "fk_lead_submissions_submitted_by_user_id_users",
        "lead_submissions",
        type_="foreignkey",
    )
    op.drop_column("lead_submissions", "validated_at")
    op.drop_column("lead_submissions", "is_valid")
    op.drop_column("lead_submissions", "submitted_by_user_id")

    op.drop_index("ix_chat_funnel_states_is_paused", table_name="chat_funnel_states")
    op.drop_constraint(
        "fk_chat_funnel_states_paused_by_user_id_users",
        "chat_funnel_states",
        type_="foreignkey",
    )
    op.drop_column("chat_funnel_states", "paused_by_user_id")
    op.drop_column("chat_funnel_states", "paused_at")
    op.drop_column("chat_funnel_states", "is_paused")

    op.drop_index("uq_users_handler_code", table_name="users")
    op.drop_constraint("ck_users_handler_code_format", "users", type_="check")
    op.drop_column("users", "handler_code")
