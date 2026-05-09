"""add bot engine tables

Revision ID: 20260509_0001
Revises:
Create Date: 2026-05-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260509_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bots",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("telegram_token", sa.String(length=255), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bots_project_id", "bots", ["project_id"])
    op.create_index("ix_bots_is_deleted", "bots", ["is_deleted"])

    op.create_table(
        "bot_versions",
        sa.Column("bot_id", sa.UUID(), nullable=False),
        sa.Column("version_name", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("start_step_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bot_versions_bot_id", "bot_versions", ["bot_id"])
    op.create_index("ix_bot_versions_is_active", "bot_versions", ["is_active"])
    op.create_index("ix_bot_versions_start_step_id", "bot_versions", ["start_step_id"])
    op.create_index(
        "uq_bot_versions_one_active_per_bot",
        "bot_versions",
        ["bot_id"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
    )

    op.create_table(
        "bot_steps",
        sa.Column("bot_version_id", sa.UUID(), nullable=False),
        sa.Column("step_type", sa.String(length=50), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("next_step_id", sa.UUID(), nullable=True),
        sa.Column("fallback_step_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["bot_version_id"], ["bot_versions.id"]),
        sa.ForeignKeyConstraint(["fallback_step_id"], ["bot_steps.id"]),
        sa.ForeignKeyConstraint(["next_step_id"], ["bot_steps.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bot_steps_bot_version_id", "bot_steps", ["bot_version_id"])
    op.create_index("ix_bot_steps_next_step_id", "bot_steps", ["next_step_id"])
    op.create_index("ix_bot_steps_fallback_step_id", "bot_steps", ["fallback_step_id"])

    op.create_foreign_key(
        "fk_bot_versions_start_step_id_bot_steps",
        "bot_versions",
        "bot_steps",
        ["start_step_id"],
        ["id"],
    )

    op.create_table(
        "chat_bot_states",
        sa.Column("chat_id", sa.UUID(), nullable=False),
        sa.Column("bot_version_id", sa.UUID(), nullable=False),
        sa.Column("current_step_id", sa.UUID(), nullable=True),
        sa.Column("variables", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_interaction_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["bot_version_id"], ["bot_versions.id"]),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"]),
        sa.ForeignKeyConstraint(["current_step_id"], ["bot_steps.id"]),
        sa.PrimaryKeyConstraint("chat_id"),
    )
    op.create_index("ix_chat_bot_states_chat_id", "chat_bot_states", ["chat_id"])
    op.create_index("ix_chat_bot_states_bot_version_id", "chat_bot_states", ["bot_version_id"])
    op.create_index("ix_chat_bot_states_current_step_id", "chat_bot_states", ["current_step_id"])
    op.create_index("ix_chat_bot_states_is_active", "chat_bot_states", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_chat_bot_states_is_active", table_name="chat_bot_states")
    op.drop_index("ix_chat_bot_states_current_step_id", table_name="chat_bot_states")
    op.drop_index("ix_chat_bot_states_bot_version_id", table_name="chat_bot_states")
    op.drop_index("ix_chat_bot_states_chat_id", table_name="chat_bot_states")
    op.drop_table("chat_bot_states")

    op.drop_constraint(
        "fk_bot_versions_start_step_id_bot_steps",
        "bot_versions",
        type_="foreignkey",
    )
    op.drop_index("ix_bot_steps_fallback_step_id", table_name="bot_steps")
    op.drop_index("ix_bot_steps_next_step_id", table_name="bot_steps")
    op.drop_index("ix_bot_steps_bot_version_id", table_name="bot_steps")
    op.drop_table("bot_steps")

    op.drop_index("uq_bot_versions_one_active_per_bot", table_name="bot_versions")
    op.drop_index("ix_bot_versions_start_step_id", table_name="bot_versions")
    op.drop_index("ix_bot_versions_is_active", table_name="bot_versions")
    op.drop_index("ix_bot_versions_bot_id", table_name="bot_versions")
    op.drop_table("bot_versions")

    op.drop_index("ix_bots_is_deleted", table_name="bots")
    op.drop_index("ix_bots_project_id", table_name="bots")
    op.drop_table("bots")
