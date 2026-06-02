"""funnel_runtime_trace_and_version_history

Revision ID: 20260602_0026
Revises: 20260602_0025
Create Date: 2026-06-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260602_0026"
down_revision = "20260602_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "funnel_versions",
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "funnel_versions",
        sa.Column("change_log", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_funnel_versions_created_by_id_users",
        "funnel_versions",
        "users",
        ["created_by_id"],
        ["id"],
    )
    op.execute(
        """
        UPDATE funnel_versions
        SET created_by_id = created_by_user_id
        WHERE created_by_id IS NULL
          AND created_by_user_id IS NOT NULL
        """
    )
    op.create_index(
        "ix_funnel_versions_created_by_id",
        "funnel_versions",
        ["created_by_id"],
    )

    op.create_table(
        "funnel_runtime_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("funnel_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('success', 'failed')",
            name="ck_funnel_runtime_logs_status",
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"]),
        sa.ForeignKeyConstraint(["funnel_version_id"], ["funnel_versions.id"]),
        sa.ForeignKeyConstraint(["step_id"], ["funnel_steps.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_funnel_runtime_logs_chat_id",
        "funnel_runtime_logs",
        ["chat_id"],
    )
    op.create_index(
        "ix_funnel_runtime_logs_funnel_version_id",
        "funnel_runtime_logs",
        ["funnel_version_id"],
    )
    op.create_index(
        "ix_funnel_runtime_logs_step_id",
        "funnel_runtime_logs",
        ["step_id"],
    )
    op.create_index(
        "ix_funnel_runtime_logs_status",
        "funnel_runtime_logs",
        ["status"],
    )
    op.create_index(
        "ix_funnel_runtime_logs_created_at",
        "funnel_runtime_logs",
        ["created_at"],
    )
    op.create_index(
        "ix_funnel_runtime_logs_chat_created_at",
        "funnel_runtime_logs",
        ["chat_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_funnel_runtime_logs_chat_created_at",
        table_name="funnel_runtime_logs",
    )
    op.drop_index("ix_funnel_runtime_logs_created_at", table_name="funnel_runtime_logs")
    op.drop_index("ix_funnel_runtime_logs_status", table_name="funnel_runtime_logs")
    op.drop_index("ix_funnel_runtime_logs_step_id", table_name="funnel_runtime_logs")
    op.drop_index(
        "ix_funnel_runtime_logs_funnel_version_id",
        table_name="funnel_runtime_logs",
    )
    op.drop_index("ix_funnel_runtime_logs_chat_id", table_name="funnel_runtime_logs")
    op.drop_table("funnel_runtime_logs")

    op.drop_index("ix_funnel_versions_created_by_id", table_name="funnel_versions")
    op.drop_constraint(
        "fk_funnel_versions_created_by_id_users",
        "funnel_versions",
        type_="foreignkey",
    )
    op.drop_column("funnel_versions", "change_log")
    op.drop_column("funnel_versions", "created_by_id")
