"""funnel hold and dropoff analytics

Revision ID: 20260601_0021
Revises: 20260601_0020
Create Date: 2026-06-01 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260601_0021"
down_revision = "20260601_0020"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "funnel_versions",
        sa.Column("is_hold_active", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_table(
        "funnel_step_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("funnel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("funnel_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_name", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=50), server_default="entered", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.ForeignKeyConstraint(["funnel_id"], ["funnels.id"]),
        sa.ForeignKeyConstraint(["funnel_version_id"], ["funnel_versions.id"]),
        sa.ForeignKeyConstraint(["step_id"], ["funnel_steps.id"]),
    )
    op.create_index("ix_funnel_step_logs_lead_id", "funnel_step_logs", ["lead_id"])
    op.create_index(
        "ix_funnel_step_logs_funnel_version_id",
        "funnel_step_logs",
        ["funnel_version_id"],
    )
    op.create_index("ix_funnel_step_logs_step_id", "funnel_step_logs", ["step_id"])
    op.create_index("ix_funnel_step_logs_event_type", "funnel_step_logs", ["event_type"])
    op.create_index("ix_funnel_step_logs_created_at", "funnel_step_logs", ["created_at"])
    op.execute(
        """
        INSERT INTO lead_statuses (code, name, sort_order, is_final, created_at)
        SELECT
            'submitted',
            'Submitted',
            (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM lead_statuses),
            false,
            now()
        WHERE NOT EXISTS (
            SELECT 1 FROM lead_statuses existing WHERE existing.code = 'submitted'
        )
        """
    )


def downgrade():
    op.execute("DELETE FROM lead_statuses WHERE code = 'submitted'")
    op.drop_index("ix_funnel_step_logs_created_at", table_name="funnel_step_logs")
    op.drop_index("ix_funnel_step_logs_event_type", table_name="funnel_step_logs")
    op.drop_index("ix_funnel_step_logs_step_id", table_name="funnel_step_logs")
    op.drop_index(
        "ix_funnel_step_logs_funnel_version_id",
        table_name="funnel_step_logs",
    )
    op.drop_index("ix_funnel_step_logs_lead_id", table_name="funnel_step_logs")
    op.drop_table("funnel_step_logs")
    op.drop_column("funnel_versions", "is_hold_active")
