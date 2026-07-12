"""facebook campaign mappings and technical-domain landers

Revision ID: 20260712_0057
Revises: 20260710_0056
Create Date: 2026-07-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260712_0057"
down_revision = "20260710_0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tracking_links",
        sa.Column(
            "fb_campaign_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tracking_links",
        sa.Column(
            "fb_event_mappings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("tracking_links", sa.Column("fb_proxy_url", sa.Text(), nullable=True))
    op.add_column(
        "tracking_links",
        sa.Column("fb_test_event_code", sa.String(length=100), nullable=True),
    )
    op.create_index(
        "ix_tracking_links_fb_campaign_enabled",
        "tracking_links",
        ["fb_campaign_enabled"],
        unique=False,
    )

    op.drop_constraint(
        "project_landers_domain_id_fkey",
        "project_landers",
        type_="foreignkey",
    )
    op.alter_column(
        "project_landers",
        "domain_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.create_foreign_key(
        "project_landers_domain_id_fkey",
        "project_landers",
        "project_domains",
        ["domain_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Technical-domain landers have no custom domain. They cannot be represented
    # by the previous schema, so fail loudly instead of deleting production data.
    bind = op.get_bind()
    orphan_count = bind.execute(
        sa.text("SELECT count(*) FROM project_landers WHERE domain_id IS NULL")
    ).scalar_one()
    if orphan_count:
        raise RuntimeError(
            "Cannot downgrade while technical-domain landers exist; assign domains first"
        )

    op.drop_constraint(
        "project_landers_domain_id_fkey",
        "project_landers",
        type_="foreignkey",
    )
    op.alter_column(
        "project_landers",
        "domain_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.create_foreign_key(
        "project_landers_domain_id_fkey",
        "project_landers",
        "project_domains",
        ["domain_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_index("ix_tracking_links_fb_campaign_enabled", table_name="tracking_links")
    op.drop_column("tracking_links", "fb_test_event_code")
    op.drop_column("tracking_links", "fb_proxy_url")
    op.drop_column("tracking_links", "fb_event_mappings_json")
    op.drop_column("tracking_links", "fb_campaign_enabled")
