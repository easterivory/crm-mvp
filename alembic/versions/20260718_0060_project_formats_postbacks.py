"""project formats, confidence routing and partner postbacks

Revision ID: 20260718_0060
Revises: 20260717_0059
Create Date: 2026-07-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260718_0060"
down_revision = "20260717_0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "project_format",
            sa.String(length=20),
            nullable=False,
            server_default="submission",
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "vip_tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "push_unread_threshold",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "confidence_weights",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "confidence_thresholds",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_projects_project_format",
        "projects",
        "project_format IN ('submission', 'gambling')",
    )
    op.create_check_constraint(
        "ck_projects_push_unread_threshold_positive",
        "projects",
        "push_unread_threshold >= 1",
    )

    op.add_column(
        "chats",
        sa.Column(
            "unanswered_push_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "chats",
        sa.Column(
            "has_out_of_scenario_message",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_check_constraint(
        "ck_chats_unanswered_push_count_nonnegative",
        "chats",
        "unanswered_push_count >= 0",
    )

    op.add_column(
        "lead_submissions",
        sa.Column(
            "submitted_manually",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "lead_submissions",
        sa.Column("routing_decision_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "lead_submissions",
        sa.Column(
            "submission_source",
            sa.String(length=20),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.create_index(
        "ix_lead_submissions_manual_source",
        "lead_submissions",
        ["submitted_manually", "submission_source"],
        unique=False,
    )

    op.create_table(
        "postback_endpoints",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("partner_integration_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("secret_token", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column(
            "parameter_mapping",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["partner_integration_id"], ["partner_integrations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("secret_token", name="uq_postback_endpoints_secret_token"),
    )
    op.create_index("ix_postback_endpoints_project_id", "postback_endpoints", ["project_id"])
    op.create_index(
        "ix_postback_endpoints_partner_integration_id",
        "postback_endpoints",
        ["partner_integration_id"],
    )

    op.create_table(
        "lead_events",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("partner_integration_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("postback_endpoint_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attributed_manager_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("external_event_id", sa.String(length=255), nullable=True),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["attributed_manager_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["partner_integration_id"], ["partner_integrations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["postback_endpoint_id"], ["postback_endpoints.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "postback_endpoint_id",
            "external_event_id",
            name="uq_lead_events_endpoint_external",
        ),
    )
    op.create_index(
        "ix_lead_events_project_type_occurred",
        "lead_events",
        ["project_id", "event_type", "occurred_at"],
    )
    op.create_index(
        "ix_lead_events_lead_occurred",
        "lead_events",
        ["lead_id", "occurred_at"],
    )
    op.create_index(
        "ix_lead_events_partner_integration_id",
        "lead_events",
        ["partner_integration_id"],
    )
    op.create_index(
        "ix_lead_events_attributed_manager_id",
        "lead_events",
        ["attributed_manager_id"],
    )

    op.create_table(
        "postback_receipts",
        sa.Column("endpoint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lead_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_method", sa.String(length=10), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column(
            "query_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "body_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["endpoint_id"], ["postback_endpoints.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_event_id"], ["lead_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_postback_receipts_endpoint_created_at",
        "postback_receipts",
        ["endpoint_id", "created_at"],
    )
    op.create_index(
        "ix_postback_receipts_project_status",
        "postback_receipts",
        ["project_id", "status"],
    )
    op.create_index("ix_postback_receipts_lead_id", "postback_receipts", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_postback_receipts_lead_id", table_name="postback_receipts")
    op.drop_index("ix_postback_receipts_project_status", table_name="postback_receipts")
    op.drop_index("ix_postback_receipts_endpoint_created_at", table_name="postback_receipts")
    op.drop_table("postback_receipts")

    op.drop_index("ix_lead_events_attributed_manager_id", table_name="lead_events")
    op.drop_index("ix_lead_events_partner_integration_id", table_name="lead_events")
    op.drop_index("ix_lead_events_lead_occurred", table_name="lead_events")
    op.drop_index("ix_lead_events_project_type_occurred", table_name="lead_events")
    op.drop_table("lead_events")

    op.drop_index("ix_postback_endpoints_partner_integration_id", table_name="postback_endpoints")
    op.drop_index("ix_postback_endpoints_project_id", table_name="postback_endpoints")
    op.drop_table("postback_endpoints")

    op.drop_index("ix_lead_submissions_manual_source", table_name="lead_submissions")
    op.drop_column("lead_submissions", "submission_source")
    op.drop_column("lead_submissions", "routing_decision_reason")
    op.drop_column("lead_submissions", "submitted_manually")

    op.drop_constraint("ck_chats_unanswered_push_count_nonnegative", "chats", type_="check")
    op.drop_column("chats", "has_out_of_scenario_message")
    op.drop_column("chats", "unanswered_push_count")

    op.drop_constraint("ck_projects_push_unread_threshold_positive", "projects", type_="check")
    op.drop_constraint("ck_projects_project_format", "projects", type_="check")
    op.drop_column("projects", "confidence_thresholds")
    op.drop_column("projects", "confidence_weights")
    op.drop_column("projects", "push_unread_threshold")
    op.drop_column("projects", "vip_tags")
    op.drop_column("projects", "project_format")
