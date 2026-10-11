"""Opt-in TikTok integration and transactional event delivery outbox."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20261011_0082"
down_revision = "20261010_0081"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tiktok_integrations",
        sa.Column("tracking_link_id", UUID(as_uuid=True), sa.ForeignKey("tracking_links.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("pixel_id", sa.String(120), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=True),
        sa.Column("test_event_code", sa.String(100), nullable=True),
        sa.Column("mappings_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "tiktok_deliveries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tracking_link_id", UUID(as_uuid=True), sa.ForeignKey("tracking_links.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(100), nullable=False, unique=True),
        sa.Column("source_event", sa.String(50), nullable=False),
        sa.Column("payload_json", JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_tiktok_deliveries_tracking_link_id", "tiktok_deliveries", ["tracking_link_id"])
    op.create_index("ix_tiktok_deliveries_due", "tiktok_deliveries", ["status", "next_attempt_at"])
    op.create_index("ix_tiktok_deliveries_link_created", "tiktok_deliveries", ["tracking_link_id", "created_at"])
    op.create_index("ix_tiktok_deliveries_created", "tiktok_deliveries", ["created_at"])


def downgrade():
    op.drop_table("tiktok_deliveries")
    op.drop_table("tiktok_integrations")
