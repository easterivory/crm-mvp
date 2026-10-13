"""Tracking indexes and durable standalone info-bot delivery checkpoints."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261013_0085"
down_revision = "20261012_0084"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        # A failed concurrent build leaves an invalid index with the same name.
        for name in ("ix_messages_project_start_lookup", "ix_chats_project_external_user"):
            if op.get_context().as_sql:
                continue
            valid = op.get_bind().execute(sa.text("SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relname=:name AND n.nspname=current_schema()"), {"name": name}).scalar()
            if valid is False:
                op.execute(f"DROP INDEX CONCURRENTLY {name}")
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_messages_project_start_lookup ON messages (chat_id, created_at, id) INCLUDE (tracking_link_id) WHERE sender_type = 'user' AND message_type = 'text' AND (split_part(lower(trim(body)), ' ', 1) = '/start' OR split_part(lower(trim(body)), ' ', 1) LIKE '/start@%')")
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_chats_project_external_user ON chats (project_id, external_user_id, id)")
    op.create_table("info_bot_deliveries",
        sa.Column("bot_id", sa.String(64), primary_key=True),
        sa.Column("update_id", sa.BigInteger(), primary_key=True),
        sa.Column("plan_json", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_info_bot_deliveries_bot_created", "info_bot_deliveries", ["bot_id", "created_at"])
    op.create_table("info_bot_cursors",
        sa.Column("bot_id", sa.String(64), primary_key=True),
        sa.Column("next_update_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def downgrade():
    op.execute("DROP TABLE IF EXISTS info_bot_cursors")
    op.execute("DROP TABLE IF EXISTS info_bot_deliveries")
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_chats_project_external_user")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_messages_project_start_lookup")
