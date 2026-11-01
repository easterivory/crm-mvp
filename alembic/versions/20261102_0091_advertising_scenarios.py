"""Multiple advertising scenarios; preserve existing queue identities."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261102_0091"
down_revision = "20261030_0090"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("advertising_configs", sa.Column("id", postgresql.UUID(as_uuid=True)))
    op.add_column("advertising_configs", sa.Column("name", sa.String(255), nullable=False, server_default="Основной"))
    op.execute("UPDATE advertising_configs SET id = project_id")
    op.alter_column("advertising_configs", "id", nullable=False)
    op.drop_constraint("advertising_configs_pkey", "advertising_configs", type_="primary")
    op.create_primary_key("advertising_configs_pkey", "advertising_configs", ["id"])
    op.create_index("ix_advertising_configs_project_id", "advertising_configs", ["project_id"])
    # Slots could be drafted before the first settings save in the old UI.
    op.execute("""INSERT INTO advertising_configs (id, project_id, name, enabled, settings_json, updated_at)
        SELECT project_id, project_id, 'Основной', false, '{}'::jsonb, now()
        FROM (SELECT project_id FROM advertising_slots UNION SELECT project_id FROM advertising_enrollments) p
        ON CONFLICT (id) DO NOTHING""")
    for table in ("advertising_slots", "advertising_enrollments", "advertising_audit"):
        op.add_column(table, sa.Column("scenario_id", postgresql.UUID(as_uuid=True)))
        op.execute(f"UPDATE {table} SET scenario_id = project_id")
        op.alter_column(table, "scenario_id", nullable=False)
        op.create_index(f"ix_{table}_scenario_id", table, ["scenario_id"])
        if table != "advertising_audit":
            op.create_foreign_key(f"{table}_scenario_id_fkey", table, "advertising_configs", ["scenario_id"], ["id"])


def downgrade():
    raise RuntimeError("Multiple scenario queues cannot be merged automatically. Restore a verified backup instead.")
