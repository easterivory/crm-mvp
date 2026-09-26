"""Opt-in channel entry funnel policies."""
from alembic import op
import sqlalchemy as sa

revision = "20260926_0078"
down_revision = "20260916_0077"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("restart_funnel_on_rejoin", "start_funnel_on_direct_join"):
        op.add_column("telegram_channels", sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("telegram_channels", "start_funnel_on_direct_join")
    op.drop_column("telegram_channels", "restart_funnel_on_rejoin")
