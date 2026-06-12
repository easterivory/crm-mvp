"""lead trash lifecycle and partner feedback

Revision ID: 20260612_0031
Revises: 20260609_0030
Create Date: 2026-06-12 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260612_0031"
down_revision = "20260609_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("is_trash", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_leads_is_trash", "leads", ["is_trash"])
    op.create_index("ix_leads_project_is_trash", "leads", ["project_id", "is_trash"])

    op.add_column("lead_submissions", sa.Column("partner_feedback", sa.Text(), nullable=True))
    op.create_unique_constraint(
        "uq_lead_submissions_lead_partner",
        "lead_submissions",
        ["lead_id", "partner_integration_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_lead_submissions_lead_partner",
        "lead_submissions",
        type_="unique",
    )
    op.drop_column("lead_submissions", "partner_feedback")

    op.drop_index("ix_leads_project_is_trash", table_name="leads")
    op.drop_index("ix_leads_is_trash", table_name="leads")
    op.drop_column("leads", "is_trash")
