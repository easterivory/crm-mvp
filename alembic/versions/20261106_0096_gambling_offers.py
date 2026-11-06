"""Opt-in offers, immutable personal links and payout terms. No historical backfill."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20261106_0096"
down_revision = "20261105_0095"
branch_labels = None
depends_on = None


def identity():
    return [sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]


def fk(name, target, nullable=False):
    return sa.Column(name, pg.UUID(as_uuid=True), sa.ForeignKey(target), nullable=nullable)


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table("offer_payout_policies", *identity(), fk("project_id", "projects.id"),
        sa.Column("name", sa.String(255), nullable=False), sa.Column("partner_name", sa.String(255), nullable=False),
        sa.Column("count_scope", sa.String(30), nullable=False), sa.Column("current_version", sa.Integer(), nullable=False))
    op.create_index("ix_offer_payout_policies_project_id", "offer_payout_policies", ["project_id"])
    op.create_table("offer_payout_versions", *identity(), fk("policy_id", "offer_payout_policies.id"),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("terms_json", pg.JSONB(), nullable=False),
        fk("created_by_id", "users.id", True),
        sa.UniqueConstraint("policy_id", "version", name="uq_offer_payout_version"))
    op.create_table("gambling_offers", *identity(), fk("project_id", "projects.id"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("name", sa.String(255), nullable=False), sa.Column("partner_name", sa.String(255), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False), sa.Column("postbacks_enabled", sa.Boolean(), nullable=False),
        sa.Column("identifier_parameter", sa.String(100)), fk("endpoint_id", "postback_endpoints.id", True),
        fk("payout_policy_id", "offer_payout_policies.id", True), sa.Column("is_active", sa.Boolean(), nullable=False))
    op.create_index("ix_gambling_offers_project_id", "gambling_offers", ["project_id"])
    op.create_table("offer_payout_assignments", *identity(), fk("offer_id", "gambling_offers.id"),
        fk("policy_id", "offer_payout_policies.id", True), fk("created_by_id", "users.id", True))
    op.create_index("ix_offer_payout_assignment_at", "offer_payout_assignments", ["offer_id", "created_at"])
    op.create_table("offer_links", *identity(), fk("project_id", "projects.id"), fk("offer_id", "gambling_offers.id"),
        fk("lead_id", "leads.id"), sa.Column("run_key", sa.String(100), nullable=False),
        sa.Column("token", sa.String(64), nullable=False, unique=True), sa.Column("issued_url", sa.Text(), nullable=False),
        fk("endpoint_id", "postback_endpoints.id", True),
        sa.Column("attribution_json", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("lead_id", "offer_id", "run_key", name="uq_offer_link_run"))
    for column in ("project_id", "offer_id", "lead_id"):
        op.create_index(f"ix_offer_links_{column}", "offer_links", [column])
    op.create_table("offer_conversions", *identity(), fk("project_id", "projects.id"), fk("offer_id", "gambling_offers.id"),
        fk("lead_id", "leads.id"), fk("offer_link_id", "offer_links.id"), fk("event_id", "lead_events.id"),
        sa.Column("event_type", sa.String(30), nullable=False), sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        fk("payout_version_id", "offer_payout_versions.id", True), sa.Column("qualified", sa.Boolean()),
        sa.Column("qualification_reason", sa.String(255)), fk("reviewed_by_id", "users.id", True),
        sa.Column("event_time_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("review_json", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("event_id"))
    op.create_index("uq_offer_first_conversion", "offer_conversions", ["offer_id", "lead_id", "event_type"],
        unique=True, postgresql_where=sa.text("event_type IN ('registration','deposit')"))
    op.create_index("ix_offer_conversion_finance", "offer_conversions", ["project_id", "occurred_at", "payout_version_id"])
    op.add_column("funnel_versions", sa.Column("offer_id", pg.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_funnel_version_offer", "funnel_versions", "gambling_offers", ["offer_id"], ["id"])


def downgrade():
    raise RuntimeError("Do not drop issued offer links, conversion identities or payout versions. Roll back code only.")
