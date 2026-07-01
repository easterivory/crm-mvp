"""Preserve existing manual tracking budgets under the explicit cost model.

Revision ID: 20260701_0050
Revises: 20260701_0049
Create Date: 2026-07-01
"""

from alembic import op


revision = "20260701_0050"
down_revision = "20260701_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE tracking_links
        SET cost_model = 'cpm'
        WHERE spend > 0
           OR EXISTS (
                SELECT 1
                FROM tracking_spends
                WHERE tracking_spends.tracking_link_id = tracking_links.id
           )
        """
    )
    op.execute(
        """
        INSERT INTO tracking_spends (
            id,
            tracking_link_id,
            spend_date,
            amount,
            currency,
            comment,
            source,
            created_at,
            updated_at
        )
        SELECT
            gen_random_uuid(),
            tracking_links.id,
            COALESCE(tracking_links.created_at::date, CURRENT_DATE),
            tracking_links.spend,
            'USD',
            'Перенесено из старого поля бюджета tracking link',
            'crm_manual',
            now(),
            now()
        FROM tracking_links
        WHERE tracking_links.spend > 0
          AND NOT EXISTS (
              SELECT 1
              FROM tracking_spends
              WHERE tracking_spends.tracking_link_id = tracking_links.id
          )
        """
    )
    op.alter_column("tracking_links", "cost_model", server_default="cpm")


def downgrade() -> None:
    op.alter_column("tracking_links", "cost_model", server_default="fix_pdp")
    # Existing spend rows do not reveal which non-manual model a link used.
