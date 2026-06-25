"""ensure tracking lead statuses exist

Revision ID: 20260626_0046
Revises: 20260625_0045
Create Date: 2026-06-26 00:00:00.000000
"""
from __future__ import annotations

from alembic import op


revision = "20260626_0046"
down_revision = "20260625_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO lead_statuses (code, name, sort_order, is_final, created_at)
        VALUES
            ('submitted', 'Submitted', 25, false, now()),
            ('applied', 'Applied', 28, false, now())
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            sort_order = EXCLUDED.sort_order,
            is_final = EXCLUDED.is_final
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM lead_statuses WHERE code IN ('submitted', 'applied')")
