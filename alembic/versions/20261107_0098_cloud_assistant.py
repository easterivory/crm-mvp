"""Add opt-in assistant state; never alter existing business records."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20261107_0098"
down_revision = "20261106_0097"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("postback_endpoints", sa.Column("ever_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    def uid(name="id", target=None, primary=False):
        args = [UUID(as_uuid=True)]
        if target: args.append(sa.ForeignKey(target))
        return sa.Column(name, *args, primary_key=primary, nullable=False,
            server_default=sa.text("gen_random_uuid()") if primary else None)
    def created(): return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    def stamp(name, nullable=True): return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)
    op.create_table("assistant_connections", uid(primary=True), created(), uid("user_id", "users.id"),
        sa.Column("client_id", sa.String(255), nullable=False), sa.Column("resource", sa.Text, nullable=False),
        sa.Column("issuer", sa.Text, nullable=False), sa.Column("project_ids", JSONB, nullable=False),
        sa.Column("scopes", JSONB, nullable=False), sa.Column("policy_version", sa.Integer, nullable=False), stamp("revoked_at"), stamp("last_used_at"))
    op.create_table("assistant_oauth_codes", sa.Column("digest", sa.String(64), primary_key=True), created(),
        uid("connection_id", "assistant_connections.id"), sa.Column("redirect_uri", sa.Text, nullable=False),
        sa.Column("challenge", sa.String(128), nullable=False), stamp("expires_at", False), stamp("consumed_at"))
    op.create_table("assistant_oauth_tokens", uid(primary=True), created(), uid("connection_id", "assistant_connections.id"),
        sa.Column("access_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("refresh_digest", sa.String(64), nullable=False, unique=True), sa.Column("scopes", JSONB, nullable=False),
        stamp("expires_at", False), stamp("refresh_expires_at", False), stamp("refresh_used_at"), stamp("revoked_at"))
    op.create_table("assistant_change_proposals", uid(primary=True), created(), uid("connection_id", "assistant_connections.id"),
        uid("user_id", "users.id"), uid("project_id", "projects.id"),
        sa.Column("request_id", sa.String(100), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("handler_version", sa.Integer, nullable=False), sa.Column("status", sa.String(30), nullable=False),
        sa.Column("plan_json", JSONB, nullable=False), sa.Column("snapshot_json", JSONB, nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False), stamp("expires_at", False),
        sa.Column("approved_by_id", UUID(as_uuid=True), sa.ForeignKey("users.id")), stamp("approved_at"),
        sa.Column("result_json", JSONB), sa.Column("error_code", sa.String(100)),
        sa.CheckConstraint("status IN ('draft','pending_approval','applied','rejected','cancelled','expired','stale','failed')", name="ck_assistant_proposal_status"))
    op.create_table("assistant_secure_inputs", uid(primary=True), created(), uid("user_id", "users.id"), uid("project_id", "projects.id"),
        sa.Column("kind", sa.String(30), nullable=False), sa.Column("encrypted_value", sa.LargeBinary, nullable=False),
        stamp("expires_at", False), sa.Column("bound_proposal_id", UUID(as_uuid=True), sa.ForeignKey("assistant_change_proposals.id")))
    for table, column in [("assistant_connections", "user_id"), ("assistant_oauth_codes", "connection_id"),
        ("assistant_oauth_codes", "expires_at"), ("assistant_oauth_tokens", "connection_id"),
        ("assistant_oauth_tokens", "refresh_expires_at"), ("assistant_change_proposals", "user_id"),
        ("assistant_change_proposals", "expires_at"), ("assistant_secure_inputs", "expires_at")]:
        op.create_index(f"ix_{table}_{column}", table, [column])
    op.create_index("uq_assistant_proposal_request", "assistant_change_proposals", ["connection_id", "request_id"], unique=True)
    op.create_index("ix_assistant_proposals_project_status", "assistant_change_proposals", ["project_id", "status", "created_at"])


def downgrade():
    raise RuntimeError("Retain assistant approvals and audit history; disable the module instead")
