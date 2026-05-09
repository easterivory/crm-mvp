"""baseline schema with bot engine tables

Revision ID: 20260509_0001
Revises:
Create Date: 2026-05-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260509_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    from app.models import Base  # noqa: WPS433 - baseline migration owns schema.

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    op.create_index(
        "uq_messages_chat_external_message_id",
        "messages",
        ["chat_id", "external_message_id"],
        unique=True,
        postgresql_where=sa.text("external_message_id IS NOT NULL"),
    )

    op.execute(
        """
        INSERT INTO roles (name)
        VALUES ('super_admin'), ('admin'), ('manager')
        ON CONFLICT (name) DO NOTHING
        """
    )

    op.execute(
        """
        INSERT INTO lead_statuses (code, name, sort_order, is_final)
        VALUES
            ('new', 'New', 10, false),
            ('in_progress', 'In progress', 20, false),
            ('qualified', 'Qualified', 30, true),
            ('lost', 'Lost', 40, true)
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            sort_order = EXCLUDED.sort_order,
            is_final = EXCLUDED.is_final
        """
    )


def downgrade() -> None:
    op.drop_index(
        "uq_messages_chat_external_message_id",
        table_name="messages",
        postgresql_where=sa.text("external_message_id IS NOT NULL"),
    )

    from app.models import Base  # noqa: WPS433 - baseline migration owns schema.

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
