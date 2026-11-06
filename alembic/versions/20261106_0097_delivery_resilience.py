"""Bounded runtime failures and per-message advertising delivery progress."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261106_0097"
down_revision = "20261106_0096"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("runtime_dispatches", sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("runtime_dispatches", sa.Column("diagnostics_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("advertising_deliveries", sa.Column("progress_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))


def downgrade():
    raise RuntimeError("Do not discard delivery progress or recovery evidence; roll back code without dropping history")
