"""Optional push photos and project-scoped parked domains."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260916_0077"
down_revision = "20260824_0076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("funnel_push_rules", sa.Column("photo_upload_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_funnel_push_rules_photo_upload", "funnel_push_rules", "broadcast_uploads", ["photo_upload_id"], ["id"])
    op.create_index("uq_project_domains_project_name", "project_domains", ["project_id", "domain_name"], unique=True)
    op.drop_index("ix_project_domains_domain_name", table_name="project_domains")
    op.create_index("ix_project_domains_domain_name", "project_domains", ["domain_name"])


def downgrade() -> None:
    # Refuse a lossy rollback: an older version cannot represent shared domains.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT domain_name FROM project_domains GROUP BY domain_name HAVING count(*) > 1) THEN
            RAISE EXCEPTION 'Remove duplicate project domain bindings before downgrading 0077';
        END IF;
        IF EXISTS (SELECT 1 FROM funnel_push_rules WHERE message_text = '') THEN
            RAISE EXCEPTION 'Add text to photo-only push rules before downgrading 0077';
        END IF;
    END $$""")
    op.drop_index("ix_project_domains_domain_name", table_name="project_domains")
    op.create_index("ix_project_domains_domain_name", "project_domains", ["domain_name"], unique=True)
    op.drop_index("uq_project_domains_project_name", table_name="project_domains")
    op.drop_constraint("fk_funnel_push_rules_photo_upload", "funnel_push_rules", type_="foreignkey")
    op.drop_column("funnel_push_rules", "photo_upload_id")
