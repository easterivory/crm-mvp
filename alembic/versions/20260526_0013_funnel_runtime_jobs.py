"""Add funnel runtime jobs and state payload.

Revision ID: 20260526_0013
Revises: 20260523_0012
Create Date: 2026-05-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260526_0013"
down_revision = "20260523_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_funnel_states",
        sa.Column(
            "runtime_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "funnel_scheduled_jobs",
        sa.Column("job_type", sa.String(length=80), nullable=False),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("funnel_state_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("funnel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("funnel_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'done', 'failed', 'cancelled')",
            name="ck_funnel_scheduled_jobs_status",
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"]),
        sa.ForeignKeyConstraint(["funnel_id"], ["funnels.id"]),
        sa.ForeignKeyConstraint(["funnel_state_id"], ["chat_funnel_states.id"]),
        sa.ForeignKeyConstraint(["funnel_version_id"], ["funnel_versions.id"]),
        sa.ForeignKeyConstraint(["step_id"], ["funnel_steps.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_funnel_scheduled_jobs_chat_id", "funnel_scheduled_jobs", ["chat_id"])
    op.create_index("ix_funnel_scheduled_jobs_job_type", "funnel_scheduled_jobs", ["job_type"])
    op.create_index("ix_funnel_scheduled_jobs_status_run_at", "funnel_scheduled_jobs", ["status", "run_at"])
    op.create_index("ix_funnel_scheduled_jobs_step_id", "funnel_scheduled_jobs", ["step_id"])


def downgrade() -> None:
    op.drop_index("ix_funnel_scheduled_jobs_step_id", table_name="funnel_scheduled_jobs")
    op.drop_index("ix_funnel_scheduled_jobs_status_run_at", table_name="funnel_scheduled_jobs")
    op.drop_index("ix_funnel_scheduled_jobs_job_type", table_name="funnel_scheduled_jobs")
    op.drop_index("ix_funnel_scheduled_jobs_chat_id", table_name="funnel_scheduled_jobs")
    op.drop_table("funnel_scheduled_jobs")
    op.drop_column("chat_funnel_states", "runtime_json")
