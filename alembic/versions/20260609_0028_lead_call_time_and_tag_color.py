"""lead preferred call time and tag color

Revision ID: 20260609_0028
Revises: 20260603_0027
Create Date: 2026-06-09 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260609_0028"
down_revision = "20260603_0027"
branch_labels = None
depends_on = None


TAG_COLOR_SQL_ARRAY = """
ARRAY[
    '#BFDBFE',
    '#C7D2FE',
    '#DDD6FE',
    '#FBCFE8',
    '#FECACA',
    '#FED7AA',
    '#FDE68A',
    '#D9F99D',
    '#BBF7D0',
    '#A7F3D0',
    '#BAE6FD',
    '#E9D5FF'
]
"""


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("preferred_call_time", sa.String(length=255), nullable=True),
    )
    op.execute(
        """
        UPDATE leads
        SET preferred_call_time = call_time_text
        WHERE preferred_call_time IS NULL
          AND call_time_text IS NOT NULL
        """
    )

    op.add_column(
        "tags",
        sa.Column("color", sa.String(length=7), nullable=True),
    )
    op.execute(
        f"""
        UPDATE tags
        SET color = ({TAG_COLOR_SQL_ARRAY})[
            ((('x' || substr(md5(id::text), 1, 8))::bit(32)::bigint % 12) + 1)::int
        ]
        WHERE color IS NULL
        """
    )
    op.alter_column(
        "tags",
        "color",
        existing_type=sa.String(length=7),
        nullable=False,
        server_default=sa.text("'#BFDBFE'"),
    )
    op.create_check_constraint(
        "ck_tags_color_hex",
        "tags",
        "color ~ '^#[0-9A-Fa-f]{6}$'",
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE leads
        SET call_time_text = preferred_call_time
        WHERE call_time_text IS NULL
          AND preferred_call_time IS NOT NULL
        """
    )
    op.drop_constraint("ck_tags_color_hex", "tags", type_="check")
    op.drop_column("tags", "color")
    op.drop_column("leads", "preferred_call_time")
