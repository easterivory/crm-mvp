"""Order deferred Telegram block observations without changing existing chat state."""
from alembic import op
import sqlalchemy as sa

revision = "20261023_0087"
down_revision = "20261013_0086"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("chats", sa.Column("telegram_block_state_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("chats", "telegram_block_state_at")
