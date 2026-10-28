"""Persist in-flight broadcasts to prevent automatic replay after worker failure."""
from alembic import op

revision = "20261028_0089"
down_revision = "20261026_0088"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("ALTER TABLE broadcast_recipients DROP CONSTRAINT IF EXISTS ck_broadcast_recipients_status")
    op.execute("ALTER TABLE broadcast_recipients ADD CONSTRAINT ck_broadcast_recipients_status CHECK (status IN ('pending','sending','sent','failed','skipped')) NOT VALID")


def downgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("UPDATE broadcast_recipients SET status='failed', last_error='Delivery interrupted during downgrade; outcome unknown' WHERE status='sending'")
    op.execute("ALTER TABLE broadcast_recipients DROP CONSTRAINT IF EXISTS ck_broadcast_recipients_status")
    op.execute("ALTER TABLE broadcast_recipients ADD CONSTRAINT ck_broadcast_recipients_status CHECK (status IN ('pending','sent','failed','skipped')) NOT VALID")
