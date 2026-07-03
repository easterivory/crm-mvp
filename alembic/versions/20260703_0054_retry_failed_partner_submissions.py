"""allow retrying failed partner submissions

Revision ID: 20260703_0054
Revises: 20260703_0053
Create Date: 2026-07-03 00:00:00.000000
"""

from alembic import op


revision = "20260703_0054"
down_revision = "20260703_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_lead_submissions_lead_partner",
        "lead_submissions",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_lead_submissions_lead_partner",
        "lead_submissions",
        ["lead_id", "partner_integration_id"],
    )
