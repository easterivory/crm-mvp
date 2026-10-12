"""Optional tag-based tracking lead qualification; existing projects keep statuses."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261012_0083"
down_revision = "20261011_0082"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("projects", sa.Column("tracking_lead_count_mode", sa.String(16), nullable=False, server_default="statuses"))
    op.add_column("projects", sa.Column("tracking_lead_tag_ids", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.create_check_constraint("ck_projects_tracking_lead_count_mode", "projects", "tracking_lead_count_mode IN ('statuses', 'tags')")


def downgrade():
    op.drop_constraint("ck_projects_tracking_lead_count_mode", "projects", type_="check")
    op.drop_column("projects", "tracking_lead_tag_ids")
    op.drop_column("projects", "tracking_lead_count_mode")
