"""Versioned incoming postbacks and atomic business deduplication."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20261103_0094"
down_revision = "20261103_0093"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("lead_events", sa.Column("attribution_locked", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("lead_events", sa.Column("attributed_bot_id", pg.UUID(as_uuid=True)))
    op.add_column("lead_events", sa.Column("attributed_buyer_id", pg.UUID(as_uuid=True)))
    op.add_column("partner_integrations", sa.Column("legacy_callback_disabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("postback_endpoints", sa.Column("processing_kind", sa.String(30), nullable=False, server_default="lifecycle_event"))
    op.add_column("postback_endpoints", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("postback_endpoints", sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    for column in [sa.Column("submission_id", pg.UUID(as_uuid=True)), sa.Column("endpoint_revision", sa.Integer()),
        sa.Column("attempt_log", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("received_at", sa.DateTime(timezone=True)), sa.Column("occurred_at", sa.DateTime(timezone=True)),
        sa.Column("processed_at", sa.DateTime(timezone=True))]:
        op.add_column("postback_receipts", column)
    op.add_column("lead_submissions", sa.Column("external_id", sa.String(255)))
    op.add_column("lead_submissions", sa.Column("callback_occurred_at", sa.DateTime(timezone=True)))
    op.create_index("ix_lead_submissions_external_id", "lead_submissions", ["external_id"])
    op.create_table("postback_endpoint_revisions",
        sa.Column("endpoint_id", pg.UUID(as_uuid=True), primary_key=True), sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False), sa.Column("config_json", pg.JSONB(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_index("ix_postback_endpoint_revisions_token_hash", "postback_endpoint_revisions", ["token_hash"])
    op.create_table("postback_business_effects",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("endpoint_id", pg.UUID(as_uuid=True), nullable=False), sa.Column("external_event_id", sa.String(255), nullable=False),
        sa.Column("namespace", sa.String(200), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False), sa.Column("result_json", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("namespace", "external_event_id", name="uq_postback_business_event"))
    op.create_table("postback_relay_health", sa.Column("instance_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False), sa.Column("stats_json", pg.JSONB(), nullable=False))
    op.create_table("postback_bindings",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("project_id", pg.UUID(as_uuid=True), nullable=False), sa.Column("namespace", sa.String(100), nullable=False),
        sa.Column("identifier_type", sa.String(30), nullable=False), sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("lead_id", pg.UUID(as_uuid=True), nullable=False), sa.Column("submission_id", pg.UUID(as_uuid=True)),
        sa.Column("attribution_json", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("project_id", "namespace", "identifier_type", "external_id", name="uq_postback_binding_identity"))
    op.create_table("postback_followups",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("project_id", pg.UUID(as_uuid=True), nullable=False), sa.Column("receipt_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False), sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("payload_json", pg.JSONB(), nullable=False), sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.String(255)), sa.UniqueConstraint("receipt_id", "kind", name="uq_postback_followup"))
    op.create_index("ix_postback_followups_status_created", "postback_followups", ["status", "created_at"])


def downgrade():
    raise RuntimeError("Keep postback audit and deduplication data; roll back code without dropping tables.")
