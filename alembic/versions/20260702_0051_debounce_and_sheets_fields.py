"""Add Telegram input debounce markers and configurable Sheets exports.

Revision ID: 20260702_0051
Revises: 20260701_0050
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260702_0051"
down_revision = "20260701_0050"
branch_labels = None
depends_on = None


DEFAULT_EXPORT_FIELDS = (
    "created_at",
    "name",
    "phone",
    "telegram",
    "country",
    "age",
    "tracking_link",
    "buyer",
    "status",
    "cpl",
    "score",
)


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("funnel_processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE messages SET funnel_processed_at = created_at "
        "WHERE sender_type = 'user'"
    )
    op.create_index(
        "ix_messages_funnel_processed_at",
        "messages",
        ["funnel_processed_at"],
    )
    op.create_index(
        "ix_messages_chat_user_debounce",
        "messages",
        ["chat_id", "sender_type", "created_at"],
        postgresql_where=sa.text("sender_type = 'user'"),
    )

    op.add_column(
        "project_google_sheets_configs",
        sa.Column(
            "bot_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "project_google_sheets_configs",
        sa.Column(
            "export_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(
                "'[\"created_at\", \"name\", \"phone\", \"telegram\", "
                "\"country\", \"age\", \"tracking_link\", \"buyer\", "
                "\"status\", \"cpl\", \"score\"]'::jsonb"
            ),
            nullable=False,
        ),
    )
    op.add_column(
        "project_google_sheets_configs",
        sa.Column(
            "custom_field_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("project_google_sheets_configs", "custom_field_keys")
    op.drop_column("project_google_sheets_configs", "export_fields")
    op.drop_column("project_google_sheets_configs", "bot_ids")
    op.drop_index("ix_messages_chat_user_debounce", table_name="messages")
    op.drop_index("ix_messages_funnel_processed_at", table_name="messages")
    op.drop_column("messages", "funnel_processed_at")
