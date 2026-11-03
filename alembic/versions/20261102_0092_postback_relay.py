"""Transport receipts for the optional external postback gateway."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20261102_0092"
down_revision = "20261102_0091"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table("postback_relay_deliveries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("response_json", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))


def downgrade():
    raise RuntimeError("Do not delete transport deduplication history while gateway retries may exist")
