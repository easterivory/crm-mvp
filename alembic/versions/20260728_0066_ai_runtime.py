"""add opt-in AI runtime configuration and usage accounting

Revision ID: 20260728_0066
Revises: 20260722_0065
Create Date: 2026-07-28 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260728_0066"
down_revision = "20260722_0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_provider_connections",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column(
            "api_style",
            sa.String(length=30),
            server_default="openai_compatible",
            nullable=False,
        ),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column("api_key_last_four", sa.String(length=4), nullable=True),
        sa.Column("credential_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("default_model", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "request_timeout_seconds",
            sa.Integer(),
            server_default="20",
            nullable=False,
        ),
        sa.Column(
            "supports_json_mode",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
        sa.Column(
            "pricing_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.CheckConstraint(
            "api_style IN ('openai_compatible', 'gemini')",
            name="ck_ai_provider_connections_api_style",
        ),
        sa.CheckConstraint(
            "request_timeout_seconds BETWEEN 1 AND 120",
            name="ck_ai_provider_connections_timeout",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_provider_connections_provider",
        "ai_provider_connections",
        ["provider"],
    )
    op.create_index(
        "ix_ai_provider_connections_active",
        "ai_provider_connections",
        ["is_active", "is_deleted"],
    )

    op.create_table(
        "ai_project_settings",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "primary_connection_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("primary_model", sa.String(length=255), nullable=True),
        sa.Column(
            "fallback_connection_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("fallback_model", sa.String(length=255), nullable=True),
        sa.Column("master_prompt", sa.Text(), nullable=True),
        sa.Column(
            "history_message_limit",
            sa.Integer(),
            server_default="20",
            nullable=False,
        ),
        sa.Column(
            "max_context_chars",
            sa.Integer(),
            server_default="16000",
            nullable=False,
        ),
        sa.Column(
            "default_temperature",
            sa.Numeric(precision=3, scale=2),
            server_default="0.40",
            nullable=False,
        ),
        sa.Column(
            "default_max_output_tokens",
            sa.Integer(),
            server_default="400",
            nullable=False,
        ),
        sa.Column(
            "typing_delay_per_char_ms",
            sa.Integer(),
            server_default="30",
            nullable=False,
        ),
        sa.Column(
            "min_delay_ms",
            sa.Integer(),
            server_default="500",
            nullable=False,
        ),
        sa.Column(
            "max_delay_ms",
            sa.Integer(),
            server_default="3500",
            nullable=False,
        ),
        sa.Column("daily_budget_usd", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column(
            "monthly_budget_usd",
            sa.Numeric(precision=14, scale=4),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "history_message_limit BETWEEN 1 AND 100",
            name="ck_ai_project_settings_history_limit",
        ),
        sa.CheckConstraint(
            "max_context_chars BETWEEN 1000 AND 100000",
            name="ck_ai_project_settings_context_chars",
        ),
        sa.CheckConstraint(
            "default_temperature BETWEEN 0 AND 2",
            name="ck_ai_project_settings_temperature",
        ),
        sa.CheckConstraint(
            "default_max_output_tokens BETWEEN 1 AND 32000",
            name="ck_ai_project_settings_output_tokens",
        ),
        sa.CheckConstraint(
            "typing_delay_per_char_ms BETWEEN 0 AND 250",
            name="ck_ai_project_settings_typing_delay",
        ),
        sa.CheckConstraint(
            "min_delay_ms BETWEEN 0 AND 30000",
            name="ck_ai_project_settings_min_delay",
        ),
        sa.CheckConstraint(
            "max_delay_ms BETWEEN 0 AND 30000",
            name="ck_ai_project_settings_max_delay",
        ),
        sa.ForeignKeyConstraint(
            ["fallback_connection_id"],
            ["ai_provider_connections.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["primary_connection_id"],
            ["ai_provider_connections.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
    )

    op.create_table(
        "ai_usage_logs",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("funnel_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("funnel_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("credential_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("api_key_last_four", sa.String(length=4), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("used_fallback", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "estimated_cost_usd",
            sa.Numeric(precision=18, scale=8),
            nullable=True,
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('success', 'failed')",
            name="ck_ai_usage_logs_status",
        ),
        sa.ForeignKeyConstraint(
            ["chat_id"],
            ["chats.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["ai_provider_connections.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["funnel_id"],
            ["funnels.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["funnel_version_id"],
            ["funnel_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["funnel_steps.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_usage_logs_project_created",
        "ai_usage_logs",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_ai_usage_logs_connection_created",
        "ai_usage_logs",
        ["connection_id", "created_at"],
    )
    op.create_index("ix_ai_usage_logs_chat_id", "ai_usage_logs", ["chat_id"])
    op.create_index("ix_ai_usage_logs_step_id", "ai_usage_logs", ["step_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_logs_step_id", table_name="ai_usage_logs")
    op.drop_index("ix_ai_usage_logs_chat_id", table_name="ai_usage_logs")
    op.drop_index(
        "ix_ai_usage_logs_connection_created",
        table_name="ai_usage_logs",
    )
    op.drop_index("ix_ai_usage_logs_project_created", table_name="ai_usage_logs")
    op.drop_table("ai_usage_logs")
    op.drop_table("ai_project_settings")
    op.drop_index(
        "ix_ai_provider_connections_active",
        table_name="ai_provider_connections",
    )
    op.drop_index(
        "ix_ai_provider_connections_provider",
        table_name="ai_provider_connections",
    )
    op.drop_table("ai_provider_connections")
