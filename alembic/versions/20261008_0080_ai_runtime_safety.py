"""AI request reservations and per-model protocol capabilities."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20261008_0080"
down_revision = "20261002_0079"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ai_provider_connections",
        sa.Column(
            "model_options_json",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_table(
        "ai_budget_reservations",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount_usd", sa.Numeric(18, 8), nullable=False),
        sa.CheckConstraint("amount_usd >= 0", name="ck_ai_budget_reservations_amount"),
        sa.Column("settled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_ai_budget_reservations_project_created",
        "ai_budget_reservations",
        ["project_id", "created_at"],
    )


def downgrade():
    op.drop_table("ai_budget_reservations")
    op.drop_column("ai_provider_connections", "model_options_json")
