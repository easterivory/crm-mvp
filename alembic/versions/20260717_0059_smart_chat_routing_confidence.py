"""smart chat routing and lead confidence

Revision ID: 20260717_0059
Revises: 20260712_0058
Create Date: 2026-07-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260717_0059"
down_revision = "20260712_0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "use_confidence_score",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "hide_assigned_chats_from_all",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "chat_lease_minutes",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )
    op.create_check_constraint(
        "ck_projects_chat_lease_minutes_nonnegative",
        "projects",
        "chat_lease_minutes >= 0",
    )

    op.add_column(
        "chats",
        sa.Column("assignment_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "chats",
        sa.Column(
            "is_favorite",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "chats",
        sa.Column(
            "has_restarted_bot",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_chats_assignment_expires_at",
        "chats",
        ["assignment_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_chats_project_is_favorite",
        "chats",
        ["project_id", "is_favorite"],
        unique=False,
    )

    op.execute(
        """
        UPDATE leads
        SET score_percent = LEAST(100, GREATEST(0, COALESCE(score_percent, 100)))
        """
    )
    op.alter_column(
        "leads",
        "score_percent",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="100",
    )
    op.add_column(
        "leads",
        sa.Column(
            "confidence_level",
            sa.String(length=10),
            nullable=False,
            server_default="high",
        ),
    )
    op.add_column(
        "leads",
        sa.Column(
            "confidence_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "leads",
        sa.Column(
            "confidence_meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.execute(
        """
        UPDATE leads
        SET confidence_level = CASE
            WHEN score_percent >= 80 THEN 'high'
            WHEN score_percent >= 50 THEN 'medium'
            ELSE 'low'
        END
        """
    )
    op.add_column(
        "leads",
        sa.Column("score_calculated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column(
            "score_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "ck_leads_score_percent_range",
        "leads",
        "score_percent BETWEEN 0 AND 100",
    )
    op.create_check_constraint(
        "ck_leads_confidence_level",
        "leads",
        "confidence_level IN ('high', 'medium', 'low')",
    )
    op.create_check_constraint(
        "ck_leads_score_version_positive",
        "leads",
        "score_version >= 1",
    )

    op.add_column(
        "partner_integrations",
        sa.Column(
            "is_auto_submit_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "partner_integrations",
        sa.Column(
            "auto_submit_rules",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_partner_integrations_project_auto_submit",
        "partner_integrations",
        ["project_id", "is_auto_submit_enabled"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_partner_integrations_project_auto_submit",
        table_name="partner_integrations",
    )
    op.drop_column("partner_integrations", "auto_submit_rules")
    op.drop_column("partner_integrations", "is_auto_submit_enabled")

    op.drop_constraint("ck_leads_score_version_positive", "leads", type_="check")
    op.drop_constraint("ck_leads_confidence_level", "leads", type_="check")
    op.drop_constraint("ck_leads_score_percent_range", "leads", type_="check")
    op.drop_column("leads", "score_version")
    op.drop_column("leads", "score_calculated_at")
    op.drop_column("leads", "confidence_meta")
    op.drop_column("leads", "confidence_reasons")
    op.drop_column("leads", "confidence_level")
    op.alter_column(
        "leads",
        "score_percent",
        existing_type=sa.Integer(),
        nullable=True,
        server_default=None,
    )

    op.drop_index("ix_chats_project_is_favorite", table_name="chats")
    op.drop_index("ix_chats_assignment_expires_at", table_name="chats")
    op.drop_column("chats", "has_restarted_bot")
    op.drop_column("chats", "is_favorite")
    op.drop_column("chats", "assignment_expires_at")

    op.drop_constraint(
        "ck_projects_chat_lease_minutes_nonnegative",
        "projects",
        type_="check",
    )
    op.drop_column("projects", "chat_lease_minutes")
    op.drop_column("projects", "hide_assigned_chats_from_all")
    op.drop_column("projects", "use_confidence_score")
