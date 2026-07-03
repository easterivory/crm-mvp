"""partner request templates

Revision ID: 20260703_0053
Revises: 20260702_0052
Create Date: 2026-07-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260703_0053"
down_revision = "20260702_0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "partner_integrations",
        sa.Column(
            "request_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("partner_integrations", "request_config")
