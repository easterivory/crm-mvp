"""Enable configured submission pushes without sending the historical backlog."""
from alembic import op
import sqlalchemy as sa

revision = "20261013_0086"
down_revision = "20261013_0085"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("projects", sa.Column(
        "funnel_push_enabled_at", sa.DateTime(timezone=True),
        nullable=False, server_default=sa.func.now(),
    ))


def downgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("projects", "funnel_push_enabled_at")
