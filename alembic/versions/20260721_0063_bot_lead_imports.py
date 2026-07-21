"""bot lead migration imports

Revision ID: 20260721_0063
Revises: 20260720_0062
Create Date: 2026-07-21 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260721_0063"
down_revision = "20260720_0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bot_lead_imports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "bot_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "imported_by_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "source_system",
            sa.String(length=50),
            server_default="chatterfy",
            nullable=False,
        ),
        sa.Column("spreadsheet_id", sa.String(length=255), nullable=False),
        sa.Column("spreadsheet_url", sa.Text(), nullable=False),
        sa.Column(
            "worksheet_title",
            sa.String(length=100),
            server_default="Перенос лидов",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="created",
            nullable=False,
        ),
        sa.Column("preview_checksum", sa.String(length=64), nullable=True),
        sa.Column(
            "preview_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("total_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("imported_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('created','validated','completed','failed')",
            name="ck_bot_lead_imports_status",
        ),
        sa.CheckConstraint(
            "total_rows >= 0 AND imported_count >= 0 AND updated_count >= 0 "
            "AND skipped_count >= 0 AND error_count >= 0",
            name="ck_bot_lead_imports_counts_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["bot_id"],
            ["bots.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["imported_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "spreadsheet_id",
            name="uq_bot_lead_imports_spreadsheet_id",
        ),
    )
    op.create_index(
        "ix_bot_lead_imports_project_id",
        "bot_lead_imports",
        ["project_id"],
    )
    op.create_index(
        "ix_bot_lead_imports_bot_id",
        "bot_lead_imports",
        ["bot_id"],
    )
    op.create_index(
        "ix_bot_lead_imports_status",
        "bot_lead_imports",
        ["status"],
    )
    op.create_index(
        "ix_bot_lead_imports_created_at",
        "bot_lead_imports",
        ["created_at"],
    )

    op.add_column(
        "chats",
        sa.Column(
            "is_imported",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.add_column(
        "chats",
        sa.Column(
            "lead_import_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "chats",
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "chats",
        sa.Column("import_username_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "chats",
        sa.Column(
            "import_identity_pending",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_chats_lead_import_id_bot_lead_imports",
        "chats",
        "bot_lead_imports",
        ["lead_import_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_chats_lead_import_id", "chats", ["lead_import_id"])
    op.create_index(
        "ix_chats_import_username_key",
        "chats",
        ["import_username_key"],
    )
    op.create_index(
        "uq_chats_pending_import_username",
        "chats",
        ["project_id", "bot_id", "import_username_key"],
        unique=True,
        postgresql_where=sa.text(
            "import_identity_pending IS TRUE AND is_deleted IS FALSE"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_chats_pending_import_username", table_name="chats")
    op.drop_index("ix_chats_import_username_key", table_name="chats")
    op.drop_index("ix_chats_lead_import_id", table_name="chats")
    op.drop_constraint(
        "fk_chats_lead_import_id_bot_lead_imports",
        "chats",
        type_="foreignkey",
    )
    op.drop_column("chats", "import_identity_pending")
    op.drop_column("chats", "import_username_key")
    op.drop_column("chats", "imported_at")
    op.drop_column("chats", "lead_import_id")
    op.drop_column("chats", "is_imported")

    op.drop_index("ix_bot_lead_imports_created_at", table_name="bot_lead_imports")
    op.drop_index("ix_bot_lead_imports_status", table_name="bot_lead_imports")
    op.drop_index("ix_bot_lead_imports_bot_id", table_name="bot_lead_imports")
    op.drop_index("ix_bot_lead_imports_project_id", table_name="bot_lead_imports")
    op.drop_table("bot_lead_imports")
