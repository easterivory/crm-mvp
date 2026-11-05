"""Durable Telegram intake and transaction-safe queue dispatch."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20261105_0095"
down_revision = "20261103_0094"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table("telegram_inbox",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("bot_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("update_id", sa.BigInteger(), nullable=False),
        sa.Column("peer_key", sa.String(100), nullable=False),
        sa.Column("payload_json", pg.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.UniqueConstraint("bot_id", "update_id", name="uq_telegram_inbox_update"))
    op.create_index("ix_telegram_inbox_due", "telegram_inbox", ["status", "available_at"])
    op.create_index("ix_telegram_inbox_peer", "telegram_inbox", ["bot_id", "peer_key", "created_at", "update_id"],
                    postgresql_where=sa.text("status IN ('pending', 'processing')"))
    op.create_index("ix_telegram_inbox_completed", "telegram_inbox", ["completed_at"], postgresql_where=sa.text("status = 'done'"))
    op.create_table("runtime_dispatches",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("dedupe_key", sa.String(200), nullable=False, unique=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("payload_json", pg.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()))
    op.create_index("ix_runtime_dispatches_due", "runtime_dispatches", ["status", "available_at"])
    op.create_index("ix_runtime_dispatches_completed", "runtime_dispatches", ["completed_at"], postgresql_where=sa.text("status = 'done'"))


def downgrade():
    raise RuntimeError("Do not drop accepted Telegram updates or pending dispatches when rolling back code.")
