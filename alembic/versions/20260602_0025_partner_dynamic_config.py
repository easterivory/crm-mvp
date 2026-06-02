"""partner_dynamic_config

Revision ID: 20260602_0025
Revises: 20260601_0024
Create Date: 2026-06-02 00:00:00.000000
"""

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260602_0025"
down_revision = "20260601_0024"
branch_labels = None
depends_on = None


DEFAULT_RESPONSE_MAPPING = {
    "status_path": "status",
    "success_values": ["success", "accepted", "ok"],
    "duplicate_values": ["duplicate"],
    "rejected_values": ["rejected", "error"],
    "status_mapping": {},
}

DEFAULT_RETRY_CONFIG = {
    "max_attempts": 3,
    "delays_seconds": [60, 300, 900],
    "timeout_seconds": 30,
}


def _jsonb_default(value: object) -> sa.TextClause:
    return sa.text(f"'{json.dumps(value, separators=(',', ':'))}'::jsonb")


def upgrade() -> None:
    op.add_column(
        "partner_integrations",
        sa.Column("auth_type", sa.String(length=30), server_default="header", nullable=False),
    )
    op.add_column(
        "partner_integrations",
        sa.Column(
            "auth_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "partner_integrations",
        sa.Column(
            "field_mapping",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "partner_integrations",
        sa.Column(
            "required_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "partner_integrations",
        sa.Column(
            "response_mapping",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=_jsonb_default(DEFAULT_RESPONSE_MAPPING),
            nullable=False,
        ),
    )
    op.add_column(
        "partner_integrations",
        sa.Column(
            "retry_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=_jsonb_default(DEFAULT_RETRY_CONFIG),
            nullable=False,
        ),
    )

    op.execute(
        """
        UPDATE partner_integrations
        SET auth_config = jsonb_build_object(
            'header_name', 'Authorization',
            'token', auth_token
        )
        WHERE auth_token IS NOT NULL
          AND auth_token <> ''
          AND auth_config = '{}'::jsonb
        """
    )

    op.create_check_constraint(
        "ck_partner_integrations_auth_type",
        "partner_integrations",
        "auth_type IN ('header', 'query_param', 'bearer')",
    )
    op.create_index(
        "ix_partner_integrations_project_active",
        "partner_integrations",
        ["project_id", "is_active"],
    )

    op.add_column(
        "lead_submissions",
        sa.Column("partner_status", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "lead_submissions",
        sa.Column("partner_status_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_lead_submissions_partner_status",
        "lead_submissions",
        ["partner_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_lead_submissions_partner_status", table_name="lead_submissions")
    op.drop_column("lead_submissions", "partner_status_updated_at")
    op.drop_column("lead_submissions", "partner_status")

    op.drop_index("ix_partner_integrations_project_active", table_name="partner_integrations")
    op.drop_constraint(
        "ck_partner_integrations_auth_type",
        "partner_integrations",
        type_="check",
    )
    op.drop_column("partner_integrations", "retry_config")
    op.drop_column("partner_integrations", "response_mapping")
    op.drop_column("partner_integrations", "required_fields")
    op.drop_column("partner_integrations", "field_mapping")
    op.drop_column("partner_integrations", "auth_config")
    op.drop_column("partner_integrations", "auth_type")
