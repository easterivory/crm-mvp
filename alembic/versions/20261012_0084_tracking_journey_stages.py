"""Opt-in analytical stages and durable tag assignment facts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20261012_0084"
down_revision = "20261012_0083"
branch_labels = None
depends_on = None


def install_tag_history_trigger():
    op.execute("""
        CREATE FUNCTION record_lead_tag_history() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO lead_tag_history (lead_id, tag_id, tag_name, occurred_at, source)
            SELECT NEW.lead_id, NEW.tag_id, name, NEW.created_at, 'assignment'
            FROM tags WHERE id = NEW.tag_id;
            RETURN NEW;
        END; $$
    """)
    op.execute("CREATE TRIGGER lead_tag_history_insert AFTER INSERT ON lead_tags FOR EACH ROW EXECUTE FUNCTION record_lead_tag_history()")


def upgrade():
    op.create_table("tracking_journey_configs",
        sa.Column("funnel_id", UUID(as_uuid=True), sa.ForeignKey("funnels.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("config_json", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("lead_tag_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tag_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tag_name", sa.String(255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(20), nullable=False))
    op.create_index("ix_lead_tag_history_lead_tag_time", "lead_tag_history", ["lead_id", "tag_id", "occurred_at"])
    install_tag_history_trigger()
    # Only existing assignment timestamps are recoverable, not previously removed tags.
    op.execute("""INSERT INTO lead_tag_history (lead_id, tag_id, tag_name, occurred_at, source)
        SELECT lt.lead_id, lt.tag_id, t.name, lt.created_at, 'legacy_snapshot'
        FROM lead_tags lt JOIN tags t ON t.id = lt.tag_id""")


def downgrade():
    op.execute("DROP TRIGGER lead_tag_history_insert ON lead_tags")
    op.execute("DROP FUNCTION record_lead_tag_history()")
    op.drop_table("lead_tag_history")
    op.drop_table("tracking_journey_configs")
