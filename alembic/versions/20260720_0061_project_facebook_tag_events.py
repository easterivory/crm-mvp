"""project-level Facebook tag event rules

Revision ID: 20260720_0061
Revises: 20260718_0060
Create Date: 2026-07-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260720_0061"
down_revision = "20260718_0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "facebook_tag_event_rules",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "facebook_tag_event_rules")
