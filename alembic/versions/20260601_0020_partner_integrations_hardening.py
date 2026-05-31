"""partner_integrations_hardening

Revision ID: 20260601_0020
Revises: 20260531_0019
Create Date: 2026-06-01 00:00:00.000000

"""
from alembic import op


revision = "20260601_0020"
down_revision = "20260531_0019"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE partner_integrations ALTER COLUMN id SET DEFAULT gen_random_uuid()"
    )
    op.execute(
        "ALTER TABLE lead_submissions ALTER COLUMN id SET DEFAULT gen_random_uuid()"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_partner_integrations_project_id_projects'
            ) THEN
                ALTER TABLE partner_integrations
                ADD CONSTRAINT fk_partner_integrations_project_id_projects
                FOREIGN KEY (project_id)
                REFERENCES projects(id)
                ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )


def downgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_partner_integrations_project_id_projects'
            ) THEN
                ALTER TABLE partner_integrations
                DROP CONSTRAINT fk_partner_integrations_project_id_projects;
            END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE lead_submissions ALTER COLUMN id DROP DEFAULT")
    op.execute("ALTER TABLE partner_integrations ALTER COLUMN id DROP DEFAULT")
