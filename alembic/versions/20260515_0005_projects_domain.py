"""add project slug status and archive fields

Revision ID: 20260515_0005
Revises: 20260511_0004
Create Date: 2026-05-15
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260515_0005"
down_revision: Union[str, None] = "20260511_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS slug VARCHAR(255)")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS description TEXT")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS status VARCHAR(20)")
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS "
        "updated_at TIMESTAMP WITH TIME ZONE"
    )

    op.execute(
        """
        WITH source AS (
            SELECT
                id,
                COALESCE(
                    NULLIF(
                        trim(
                            both '-' from regexp_replace(
                                lower(COALESCE(name, 'project')),
                                '[^a-z0-9]+',
                                '-',
                                'g'
                            )
                        ),
                        ''
                    ),
                    'project'
                ) AS base_slug,
                created_at
            FROM projects
            WHERE slug IS NULL OR slug = ''
        ),
        numbered AS (
            SELECT
                id,
                base_slug,
                row_number() OVER (
                    PARTITION BY base_slug
                    ORDER BY created_at, id
                ) AS rn
            FROM source
        )
        UPDATE projects AS project
        SET slug = CASE
            WHEN numbered.rn = 1 THEN numbered.base_slug
            ELSE numbered.base_slug || '-' || numbered.rn::text
        END
        FROM numbered
        WHERE project.id = numbered.id
        """
    )
    op.execute("UPDATE projects SET status = 'active' WHERE status IS NULL")
    op.execute("UPDATE projects SET updated_at = created_at WHERE updated_at IS NULL")

    op.execute("ALTER TABLE projects ALTER COLUMN slug SET NOT NULL")
    op.execute("ALTER TABLE projects ALTER COLUMN status SET DEFAULT 'active'")
    op.execute("ALTER TABLE projects ALTER COLUMN status SET NOT NULL")
    op.execute("ALTER TABLE projects ALTER COLUMN updated_at SET DEFAULT now()")
    op.execute("ALTER TABLE projects ALTER COLUMN updated_at SET NOT NULL")

    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_projects_slug ON projects (slug)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_projects_status ON projects (status)")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_projects_status'
            ) THEN
                ALTER TABLE projects
                    ADD CONSTRAINT ck_projects_status
                    CHECK (status IN ('active', 'archived'));
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP CONSTRAINT IF EXISTS ck_projects_status")
    op.execute("DROP INDEX IF EXISTS ix_projects_status")
    op.execute("DROP INDEX IF EXISTS ix_projects_slug")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS status")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS description")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS slug")
