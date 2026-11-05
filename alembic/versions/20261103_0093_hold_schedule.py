"""Opt-in project HOLD calendar; existing versions remain manual."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261103_0093"
down_revision = "20261102_0092"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("projects", sa.Column("hold_schedule", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("funnel_versions", sa.Column("hold_mode", sa.String(30), nullable=False, server_default="manual"))


def downgrade():
    raise RuntimeError("HOLD settings must be retained. Roll back application code without dropping these columns.")
