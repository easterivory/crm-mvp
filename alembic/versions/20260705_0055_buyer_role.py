"""add a dedicated buyer role

Revision ID: 20260705_0055
Revises: 20260703_0054
Create Date: 2026-07-05 00:00:00.000000
"""

from alembic import op


revision = "20260705_0055"
down_revision = "20260703_0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO roles (name)
        VALUES ('buyer')
        ON CONFLICT (name) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE users AS candidate
        SET role_id = buyer_role.id
        FROM roles AS buyer_role, roles AS manager_role
        WHERE buyer_role.name = 'buyer'
          AND manager_role.name = 'manager'
          AND candidate.role_id = manager_role.id
          AND (
              candidate.buyer_telegram_id IS NOT NULL
              OR candidate.buyer_invite_token IS NOT NULL
              OR EXISTS (
                  SELECT 1
                  FROM tracking_links AS link
                  WHERE link.buyer_id = candidate.id
              )
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE users AS candidate
        SET role_id = manager_role.id
        FROM roles AS buyer_role, roles AS manager_role
        WHERE buyer_role.name = 'buyer'
          AND manager_role.name = 'manager'
          AND candidate.role_id = buyer_role.id
        """
    )
    op.execute("DELETE FROM roles WHERE name = 'buyer'")
