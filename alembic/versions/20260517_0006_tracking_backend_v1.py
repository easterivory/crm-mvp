"""add tracking backend v1 fields and manual spends

Revision ID: 20260517_0006
Revises: 20260515_0005
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260517_0006"
down_revision: Union[str, None] = "20260515_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tracking_links ADD COLUMN IF NOT EXISTS code VARCHAR(100)")
    op.execute("ALTER TABLE tracking_links ADD COLUMN IF NOT EXISTS title VARCHAR(255)")
    op.execute("ALTER TABLE tracking_links ADD COLUMN IF NOT EXISTS buyer_name VARCHAR(255)")
    op.execute("ALTER TABLE tracking_links ADD COLUMN IF NOT EXISTS ad_type VARCHAR(100)")
    op.execute("ALTER TABLE tracking_links ADD COLUMN IF NOT EXISTS payment_type VARCHAR(100)")
    op.execute("ALTER TABLE tracking_links ADD COLUMN IF NOT EXISTS invite_link TEXT")
    op.execute(
        "ALTER TABLE tracking_links ADD COLUMN IF NOT EXISTS "
        "is_active BOOLEAN NOT NULL DEFAULT true"
    )
    op.execute(
        "ALTER TABLE tracking_links ADD COLUMN IF NOT EXISTS "
        "created_by_user_id UUID REFERENCES users(id)"
    )
    op.execute(
        "ALTER TABLE tracking_links ADD COLUMN IF NOT EXISTS "
        "updated_at TIMESTAMP WITH TIME ZONE"
    )

    op.execute(
        """
        UPDATE tracking_links
        SET
            code = COALESCE(NULLIF(code, ''), ref_code),
            title = COALESCE(NULLIF(title, ''), name),
            updated_at = COALESCE(updated_at, created_at, now())
        WHERE code IS NULL
           OR code = ''
           OR title IS NULL
           OR title = ''
           OR updated_at IS NULL
        """
    )
    op.execute("ALTER TABLE tracking_links ALTER COLUMN code SET NOT NULL")
    op.execute("ALTER TABLE tracking_links ALTER COLUMN title SET NOT NULL")
    op.execute("ALTER TABLE tracking_links ALTER COLUMN updated_at SET DEFAULT now()")
    op.execute("ALTER TABLE tracking_links ALTER COLUMN updated_at SET NOT NULL")

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_tracking_links_code'
            ) THEN
                ALTER TABLE tracking_links
                    ADD CONSTRAINT uq_tracking_links_code UNIQUE (code);
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_links_code ON tracking_links (code)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_links_is_active "
        "ON tracking_links (is_active)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tracking_spends (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tracking_link_id UUID NOT NULL REFERENCES tracking_links(id),
            spend_date DATE NOT NULL,
            amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
            currency VARCHAR(3) NOT NULL DEFAULT 'USD',
            comment TEXT,
            source VARCHAR(32) NOT NULL DEFAULT 'crm_manual',
            created_by_user_id UUID REFERENCES users(id),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT ck_tracking_spends_amount_nonnegative CHECK (amount >= 0),
            CONSTRAINT ck_tracking_spends_source
                CHECK (source IN ('crm_manual', 'buyer_bot'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_spends_tracking_link_id "
        "ON tracking_spends (tracking_link_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_spends_spend_date "
        "ON tracking_spends (spend_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_spends_source "
        "ON tracking_spends (source)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tracking_spends_source")
    op.execute("DROP INDEX IF EXISTS ix_tracking_spends_spend_date")
    op.execute("DROP INDEX IF EXISTS ix_tracking_spends_tracking_link_id")
    op.execute("DROP TABLE IF EXISTS tracking_spends")

    op.execute("DROP INDEX IF EXISTS ix_tracking_links_is_active")
    op.execute("DROP INDEX IF EXISTS ix_tracking_links_code")
    op.execute("ALTER TABLE tracking_links DROP CONSTRAINT IF EXISTS uq_tracking_links_code")
    op.execute("ALTER TABLE tracking_links DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE tracking_links DROP COLUMN IF EXISTS created_by_user_id")
    op.execute("ALTER TABLE tracking_links DROP COLUMN IF EXISTS is_active")
    op.execute("ALTER TABLE tracking_links DROP COLUMN IF EXISTS invite_link")
    op.execute("ALTER TABLE tracking_links DROP COLUMN IF EXISTS payment_type")
    op.execute("ALTER TABLE tracking_links DROP COLUMN IF EXISTS ad_type")
    op.execute("ALTER TABLE tracking_links DROP COLUMN IF EXISTS buyer_name")
    op.execute("ALTER TABLE tracking_links DROP COLUMN IF EXISTS title")
    op.execute("ALTER TABLE tracking_links DROP COLUMN IF EXISTS code")
