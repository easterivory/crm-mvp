"""Opt-in traffic quality rules and durable buyer notifications."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20261002_0079"
down_revision = "20260926_0078"
branch_labels = None
depends_on = None


def upgrade():
    for table, key, target in (
        ("traffic_quality_settings", "project_id", "projects.id"),
        ("traffic_quality_overrides", "link_id", "tracking_links.id"),
    ):
        op.create_table(table,
            sa.Column(key, pg.UUID(as_uuid=True), sa.ForeignKey(target, ondelete="CASCADE"), primary_key=True),
            sa.Column("config", pg.JSONB(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("traffic_quality_states",
        sa.Column("link_id", pg.UUID(as_uuid=True), sa.ForeignKey("tracking_links.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("rule_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("last_notified_at", sa.DateTime(timezone=True)),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", pg.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("traffic_quality_deliveries",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("link_id", pg.UUID(as_uuid=True), sa.ForeignKey("tracking_links.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bot_kind", sa.String(16), nullable=False),
        sa.Column("dedup_key", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("dedup_key", name="uq_quality_delivery_key"))
    for field in ("project_id", "status", "available_at"):
        op.create_index(f"ix_traffic_quality_deliveries_{field}", "traffic_quality_deliveries", [field])
    op.create_table("traffic_quality_acknowledgements",
        sa.Column("link_id", pg.UUID(as_uuid=True), sa.ForeignKey("tracking_links.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generations", pg.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))


def downgrade():
    for table in ("traffic_quality_acknowledgements", "traffic_quality_deliveries", "traffic_quality_states", "traffic_quality_overrides", "traffic_quality_settings"):
        op.drop_table(table)
