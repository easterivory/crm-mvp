"""allow lead update chat audit events

Revision ID: 20260609_0029
Revises: 20260609_0028
Create Date: 2026-06-09 00:15:00.000000
"""
from __future__ import annotations

from alembic import op


revision = "20260609_0029"
down_revision = "20260609_0028"
branch_labels = None
depends_on = None


NEW_EVENT_TYPES = (
    "'status_change','tag_added','manager_assigned','SLA_breached','note_added','lead_updated'"
)
OLD_EVENT_TYPES = "'status_change','tag_added','manager_assigned','SLA_breached','note_added'"


def upgrade() -> None:
    op.drop_constraint("ck_chat_event_logs_event_type", "chat_event_logs", type_="check")
    op.create_check_constraint(
        "ck_chat_event_logs_event_type",
        "chat_event_logs",
        f"event_type IN ({NEW_EVENT_TYPES})",
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE chat_event_logs
        SET event_type = 'note_added'
        WHERE event_type = 'lead_updated'
        """
    )
    op.drop_constraint("ck_chat_event_logs_event_type", "chat_event_logs", type_="check")
    op.create_check_constraint(
        "ck_chat_event_logs_event_type",
        "chat_event_logs",
        f"event_type IN ({OLD_EVENT_TYPES})",
    )
