"""project google sheets configs

Revision ID: 20260613_0034
Revises: 20260613_0033
Create Date: 2026-06-13 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260613_0034"
down_revision = "20260613_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_google_sheets_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("spreadsheet_id", sa.String(length=255), nullable=True),
        sa.Column(
            "sheet_name",
            sa.String(length=255),
            server_default=sa.text("'Лиды'"),
            nullable=False,
        ),
        sa.Column(
            "trigger_statuses",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
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
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_google_sheets_configs_project_id",
        "project_google_sheets_configs",
        ["project_id"],
        unique=True,
    )
    op.create_index(
        "ix_project_google_sheets_configs_is_enabled",
        "project_google_sheets_configs",
        ["is_enabled"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_google_sheets_configs_is_enabled",
        table_name="project_google_sheets_configs",
    )
    op.drop_index(
        "ix_project_google_sheets_configs_project_id",
        table_name="project_google_sheets_configs",
    )
    op.drop_table("project_google_sheets_configs")
