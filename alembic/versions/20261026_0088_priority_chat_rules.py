"""Opt-in project rules for the priority chat workspace."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261026_0088"
down_revision = "20261023_0087"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("projects", sa.Column("priority_chat_rules", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))


def downgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("projects", "priority_chat_rules")
