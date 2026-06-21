"""user project accesses

Revision ID: 20260621_0038
Revises: 20260618_0037
Create Date: 2026-06-21 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260621_0038"
down_revision = "20260618_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_project_accesses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "project_id", name="uq_user_project_access_user_project"),
    )
    op.create_index(
        "ix_user_project_accesses_user_id",
        "user_project_accesses",
        ["user_id"],
    )
    op.create_index(
        "ix_user_project_accesses_project_id",
        "user_project_accesses",
        ["project_id"],
    )
    op.execute(
        """
        INSERT INTO user_project_accesses (user_id, project_id)
        SELECT id, project_id
        FROM users
        WHERE project_id IS NOT NULL
        ON CONFLICT (user_id, project_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_user_project_accesses_project_id", table_name="user_project_accesses")
    op.drop_index("ix_user_project_accesses_user_id", table_name="user_project_accesses")
    op.drop_table("user_project_accesses")
