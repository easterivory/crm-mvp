"""snapshot submission and lifecycle event attribution

Revision ID: 20260728_0067
Revises: 20260728_0066
Create Date: 2026-07-28 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260728_0067"
down_revision = "20260728_0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_submissions",
        sa.Column("tracking_link_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_lead_submissions_tracking_link_id",
        "lead_submissions",
        "tracking_links",
        ["tracking_link_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_lead_submissions_tracking_status_completed",
        "lead_submissions",
        ["tracking_link_id", "status", "completed_at"],
        unique=False,
    )

    op.add_column(
        "lead_events",
        sa.Column("tracking_link_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "lead_events",
        sa.Column("funnel_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "lead_events",
        sa.Column("funnel_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_lead_events_tracking_link_id",
        "lead_events",
        "tracking_links",
        ["tracking_link_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_lead_events_funnel_id",
        "lead_events",
        "funnels",
        ["funnel_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_lead_events_funnel_version_id",
        "lead_events",
        "funnel_versions",
        ["funnel_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_lead_events_tracking_type_occurred",
        "lead_events",
        ["tracking_link_id", "event_type", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_lead_events_funnel_version_type_occurred",
        "lead_events",
        ["funnel_version_id", "event_type", "occurred_at"],
        unique=False,
    )

    # Existing rows receive the attribution that is currently available.
    # New rows snapshot these values at write time and are not affected by
    # later chat resets or tracking-link changes.
    op.execute(
        """
        UPDATE lead_submissions AS submission
        SET tracking_link_id = chat.tracking_link_id
        FROM leads AS lead
        JOIN chats AS chat ON chat.id = lead.chat_id
        WHERE submission.lead_id = lead.id
          AND submission.tracking_link_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE lead_events AS event
        SET tracking_link_id = chat.tracking_link_id
        FROM leads AS lead
        JOIN chats AS chat ON chat.id = lead.chat_id
        WHERE event.lead_id = lead.id
          AND event.tracking_link_id IS NULL
        """
    )
    op.execute(
        """
        INSERT INTO lead_events (
            id,
            project_id,
            lead_id,
            created_by_user_id,
            attributed_manager_id,
            tracking_link_id,
            funnel_id,
            funnel_version_id,
            event_type,
            source,
            payload_json,
            occurred_at,
            created_at
        )
        SELECT
            gen_random_uuid(),
            lead.project_id,
            lead.id,
            NULL,
            lead.manager_id,
            chat.tracking_link_id,
            state.funnel_id,
            state.funnel_version_id,
            CASE rule.value->>'source_event'
                WHEN 'registration' THEN 'registration'
                WHEN 'sale' THEN 'deposit'
                WHEN 'resale' THEN 'redeposit'
            END,
            'tag',
            jsonb_build_object(
                'tag_id', tag.id::text,
                'tag_name', tag.name,
                'migrated_from_existing_tag', true
            ),
            lead_tag.created_at,
            lead_tag.created_at
        FROM lead_tags AS lead_tag
        JOIN leads AS lead ON lead.id = lead_tag.lead_id
        JOIN chats AS chat ON chat.id = lead.chat_id
        JOIN tags AS tag ON tag.id = lead_tag.tag_id
        JOIN projects AS project ON project.id = lead.project_id
        LEFT JOIN chat_funnel_states AS state ON state.chat_id = chat.id
        CROSS JOIN LATERAL jsonb_array_elements(
            COALESCE(project.facebook_tag_event_rules, '[]'::jsonb)
        ) AS rule(value)
        WHERE rule.value->>'tag_id' = tag.id::text
          AND rule.value->>'source_event' IN ('registration', 'sale', 'resale')
          AND NOT EXISTS (
              SELECT 1
              FROM lead_events AS existing
              WHERE existing.lead_id = lead.id
                AND existing.event_type = CASE rule.value->>'source_event'
                    WHEN 'registration' THEN 'registration'
                    WHEN 'sale' THEN 'deposit'
                    WHEN 'resale' THEN 'redeposit'
                END
          )
        """
    )
    op.execute(
        """
        UPDATE lead_events AS event
        SET funnel_id = state.funnel_id,
            funnel_version_id = state.funnel_version_id
        FROM leads AS lead
        JOIN chat_funnel_states AS state ON state.chat_id = lead.chat_id
        WHERE event.lead_id = lead.id
          AND (event.funnel_id IS NULL OR event.funnel_version_id IS NULL)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM lead_events
        WHERE source = 'tag'
          AND payload_json->>'migrated_from_existing_tag' = 'true'
        """
    )
    op.drop_index(
        "ix_lead_events_funnel_version_type_occurred",
        table_name="lead_events",
    )
    op.drop_index(
        "ix_lead_events_tracking_type_occurred",
        table_name="lead_events",
    )
    op.drop_constraint(
        "fk_lead_events_funnel_version_id",
        "lead_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_lead_events_funnel_id",
        "lead_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_lead_events_tracking_link_id",
        "lead_events",
        type_="foreignkey",
    )
    op.drop_column("lead_events", "funnel_version_id")
    op.drop_column("lead_events", "funnel_id")
    op.drop_column("lead_events", "tracking_link_id")

    op.drop_index(
        "ix_lead_submissions_tracking_status_completed",
        table_name="lead_submissions",
    )
    op.drop_constraint(
        "fk_lead_submissions_tracking_link_id",
        "lead_submissions",
        type_="foreignkey",
    )
    op.drop_column("lead_submissions", "tracking_link_id")
