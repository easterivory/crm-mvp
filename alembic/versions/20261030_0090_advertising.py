"""Opt-in advertising queues. Existing CRM rows are not modified."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20261030_0090"
down_revision = "20261028_0089"
branch_labels = depends_on = None


def identity():
    return [sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def updated():
    return sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def project():
    return sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False)


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table("advertising_configs",
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled_at", sa.DateTime(timezone=True)),
        sa.Column("settings_json", JSONB(), nullable=False, server_default="{}"), updated())
    op.create_table("advertising_slots", *identity(), updated(), project(),
        sa.Column("name", sa.String(255), nullable=False), sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("delay_minutes", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("content_json", JSONB(), nullable=False))
    op.create_index("ix_advertising_slots_project_id", "advertising_slots", ["project_id"])
    op.create_table("advertising_enrollments", *identity(), updated(), project(),
        sa.Column("chat_id", UUID(as_uuid=True), sa.ForeignKey("chats.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("reason", sa.Text()),
        sa.Column("source", sa.String(20), nullable=False), sa.Column("stop_main", sa.Boolean(), nullable=False),
        sa.Column("marker_tag_id", UUID(as_uuid=True)))
    op.create_index("ix_advertising_enrollments_chat_id", "advertising_enrollments", ["chat_id"])
    op.create_index("ix_ad_enrollment_due", "advertising_enrollments", ["status", "due_at"])
    op.create_index("ix_ad_enrollment_project_created", "advertising_enrollments", ["project_id", "created_at"])
    op.create_index("uq_ad_enrollment_live_chat", "advertising_enrollments", ["chat_id"], unique=True,
        postgresql_where=sa.text("status IN ('waiting','active','completed','protected','stopped')"))
    op.create_table("advertising_deliveries", *identity(), updated(),
        sa.Column("enrollment_id", UUID(as_uuid=True), sa.ForeignKey("advertising_enrollments.id"), nullable=False),
        sa.Column("slot_id", UUID(as_uuid=True), sa.ForeignKey("advertising_slots.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False), sa.Column("delay_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("revision", sa.Integer()),
        sa.Column("content_snapshot", JSONB()), sa.Column("sent_at", sa.DateTime(timezone=True)), sa.Column("error", sa.Text()),
        sa.UniqueConstraint("enrollment_id", "slot_id", name="uq_ad_delivery_slot"))
    op.create_index("ix_advertising_deliveries_enrollment_id", "advertising_deliveries", ["enrollment_id"])
    op.create_index("ix_advertising_deliveries_status", "advertising_deliveries", ["status"])
    op.create_table("advertising_audit", *identity(), project(),
        sa.Column("actor_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("event", sa.String(80), nullable=False), sa.Column("details", JSONB(), nullable=False))
    op.create_index("ix_advertising_audit_project_id", "advertising_audit", ["project_id"])


def downgrade():
    # Destructive downgrade is deliberately explicit; do not erase delivery history.
    raise RuntimeError("Advertising history must be backed up and archived before removing these tables")
