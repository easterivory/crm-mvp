"""lead duplicate identity indexes

Revision ID: 20260612_0032
Revises: 20260612_0031
Create Date: 2026-06-12 00:30:00.000000
"""
from __future__ import annotations

from alembic import op


revision = "20260612_0032"
down_revision = "20260612_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_leads_phone", "leads", ["phone"])
    op.execute(
        """
        CREATE INDEX ix_leads_phone_digits
        ON leads ((regexp_replace(coalesce(phone, ''), '\\D', '', 'g')))
        WHERE phone IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX ix_leads_username_lower
        ON leads ((lower(replace(coalesce(username, ''), '@', ''))))
        WHERE username IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_leads_username_lower", table_name="leads")
    op.drop_index("ix_leads_phone_digits", table_name="leads")
    op.drop_index("ix_leads_phone", table_name="leads")
