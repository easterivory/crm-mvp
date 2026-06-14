"""project domains and landers

Revision ID: 20260614_0035
Revises: 20260613_0034
Create Date: 2026-06-14 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260614_0035"
down_revision = "20260613_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_domains",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain_name", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
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
        "ix_project_domains_domain_name",
        "project_domains",
        ["domain_name"],
        unique=True,
    )
    op.create_index(
        "ix_project_domains_project_id",
        "project_domains",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_domains_project_active",
        "project_domains",
        ["project_id", "is_active"],
        unique=False,
    )

    op.create_table(
        "project_landers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("tracking_link_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("custom_html_path", sa.String(length=1024), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
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
        sa.CheckConstraint(
            "type IN ('default_tg_redirect', 'custom_upload')",
            name="ck_project_landers_type",
        ),
        sa.ForeignKeyConstraint(
            ["domain_id"],
            ["project_domains.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tracking_link_id"],
            ["tracking_links.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_landers_slug",
        "project_landers",
        ["slug"],
        unique=True,
    )
    op.create_index(
        "ix_project_landers_domain_id",
        "project_landers",
        ["domain_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_landers_project_id",
        "project_landers",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_landers_tracking_link_id",
        "project_landers",
        ["tracking_link_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_landers_domain_active",
        "project_landers",
        ["domain_id", "is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_project_landers_domain_active", table_name="project_landers")
    op.drop_index("ix_project_landers_tracking_link_id", table_name="project_landers")
    op.drop_index("ix_project_landers_project_id", table_name="project_landers")
    op.drop_index("ix_project_landers_domain_id", table_name="project_landers")
    op.drop_index("ix_project_landers_slug", table_name="project_landers")
    op.drop_table("project_landers")

    op.drop_index("ix_project_domains_project_active", table_name="project_domains")
    op.drop_index("ix_project_domains_project_id", table_name="project_domains")
    op.drop_index("ix_project_domains_domain_name", table_name="project_domains")
    op.drop_table("project_domains")
