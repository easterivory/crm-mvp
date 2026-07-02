"""Add default Facebook CAPI credentials to buyer profiles.

Revision ID: 20260702_0052
Revises: 20260702_0051
"""

from alembic import op
import sqlalchemy as sa


revision = "20260702_0052"
down_revision = "20260702_0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("buyer_fb_pixel_id", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("buyer_fb_capi_token", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "buyer_fb_capi_token")
    op.drop_column("users", "buyer_fb_pixel_id")
