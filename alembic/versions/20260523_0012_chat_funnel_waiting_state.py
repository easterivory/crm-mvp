"""Add waiting flag to chat funnel state.

Revision ID: 20260523_0012
Revises: 20260521_0011
Create Date: 2026-05-23 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260523_0012"
down_revision: Union[str, None] = "20260521_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_funnel_states",
        sa.Column(
            "waiting_for_answer",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_funnel_states", "waiting_for_answer")
