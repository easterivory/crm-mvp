"""add funnel builder domain

Revision ID: 20260520_0009
Revises: 20260519_0008
Create Date: 2026-05-20
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260520_0009"
down_revision: Union[str, None] = "20260519_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS name VARCHAR(255)")
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS age INTEGER")
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS country VARCHAR(100)")
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS call_time_text VARCHAR(255)")
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS has_card BOOLEAN")
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS "
        "custom_fields JSONB NOT NULL DEFAULT '{}'::jsonb"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS funnels (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES projects(id),
            bot_id UUID NOT NULL REFERENCES bots(id),
            name VARCHAR(255) NOT NULL,
            description TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            created_by_user_id UUID REFERENCES users(id),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT ck_funnels_status CHECK (status IN ('active', 'archived'))
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_funnels_project_id ON funnels(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_funnels_bot_id ON funnels(bot_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_funnels_status ON funnels(status)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_funnels_project_bot_status "
        "ON funnels(project_id, bot_id, status)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS funnel_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            funnel_id UUID NOT NULL REFERENCES funnels(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            created_by_user_id UUID REFERENCES users(id),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            published_at TIMESTAMP WITH TIME ZONE,
            CONSTRAINT ck_funnel_versions_status
                CHECK (status IN ('draft', 'published', 'archived')),
            CONSTRAINT uq_funnel_versions_funnel_version_number
                UNIQUE (funnel_id, version_number)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_funnel_versions_funnel_id "
        "ON funnel_versions(funnel_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_funnel_versions_status "
        "ON funnel_versions(status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_funnel_versions_published_at "
        "ON funnel_versions(published_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_funnel_versions_one_published_per_funnel "
        "ON funnel_versions(funnel_id) WHERE status = 'published'"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS funnel_steps (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            funnel_version_id UUID NOT NULL REFERENCES funnel_versions(id) ON DELETE CASCADE,
            key VARCHAR(100) NOT NULL,
            title VARCHAR(255) NOT NULL,
            step_type VARCHAR(50) NOT NULL,
            block_type VARCHAR(100) NOT NULL,
            position_x DOUBLE PRECISION NOT NULL DEFAULT 0,
            position_y DOUBLE PRECISION NOT NULL DEFAULT 0,
            config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            validation_json JSONB,
            ui_schema_json JSONB,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT uq_funnel_steps_version_key UNIQUE (funnel_version_id, key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_funnel_steps_funnel_version_id "
        "ON funnel_steps(funnel_version_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_funnel_steps_step_type ON funnel_steps(step_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_funnel_steps_block_type ON funnel_steps(block_type)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS funnel_edges (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            funnel_version_id UUID NOT NULL REFERENCES funnel_versions(id) ON DELETE CASCADE,
            from_step_id UUID NOT NULL REFERENCES funnel_steps(id) ON DELETE CASCADE,
            to_step_id UUID NOT NULL REFERENCES funnel_steps(id) ON DELETE CASCADE,
            condition_json JSONB,
            priority INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_funnel_edges_funnel_version_id "
        "ON funnel_edges(funnel_version_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_funnel_edges_from_step_id "
        "ON funnel_edges(from_step_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_funnel_edges_to_step_id "
        "ON funnel_edges(to_step_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS funnel_push_rules (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            funnel_version_id UUID NOT NULL REFERENCES funnel_versions(id) ON DELETE CASCADE,
            step_id UUID NOT NULL REFERENCES funnel_steps(id) ON DELETE CASCADE,
            delay_minutes INTEGER NOT NULL,
            message_text TEXT NOT NULL,
            action_after_send VARCHAR(50) NOT NULL DEFAULT 'stay',
            target_step_id UUID REFERENCES funnel_steps(id) ON DELETE SET NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT ck_funnel_push_rules_action_after_send CHECK (
                action_after_send IN ('stay', 'move_to_step', 'finish', 'assign_operator')
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_funnel_push_rules_funnel_version_id "
        "ON funnel_push_rules(funnel_version_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_funnel_push_rules_step_id "
        "ON funnel_push_rules(step_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_funnel_push_rules_is_active "
        "ON funnel_push_rules(is_active)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS funnel_field_mappings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            funnel_version_id UUID NOT NULL REFERENCES funnel_versions(id) ON DELETE CASCADE,
            step_id UUID NOT NULL REFERENCES funnel_steps(id) ON DELETE CASCADE,
            source VARCHAR(50) NOT NULL,
            lead_field_key VARCHAR(100) NOT NULL,
            transform_rule_json JSONB,
            is_required BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT ck_funnel_field_mappings_source CHECK (
                source IN ('user_answer', 'button_value', 'computed_value')
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_funnel_field_mappings_funnel_version_id "
        "ON funnel_field_mappings(funnel_version_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_funnel_field_mappings_step_id "
        "ON funnel_field_mappings(step_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_funnel_field_mappings_lead_field_key "
        "ON funnel_field_mappings(lead_field_key)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_funnel_states (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            chat_id UUID NOT NULL REFERENCES chats(id),
            funnel_id UUID NOT NULL REFERENCES funnels(id),
            funnel_version_id UUID NOT NULL REFERENCES funnel_versions(id),
            current_step_id UUID NOT NULL REFERENCES funnel_steps(id),
            entered_step_at TIMESTAMP WITH TIME ZONE NOT NULL,
            completed_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT uq_chat_funnel_states_chat_id UNIQUE (chat_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chat_funnel_states_chat_id "
        "ON chat_funnel_states(chat_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chat_funnel_states_funnel_id "
        "ON chat_funnel_states(funnel_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chat_funnel_states_funnel_version_id "
        "ON chat_funnel_states(funnel_version_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chat_funnel_states_current_step_id "
        "ON chat_funnel_states(current_step_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chat_funnel_states_completed_at "
        "ON chat_funnel_states(completed_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chat_funnel_states_entered_step_at "
        "ON chat_funnel_states(entered_step_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_funnel_states")
    op.execute("DROP TABLE IF EXISTS funnel_field_mappings")
    op.execute("DROP TABLE IF EXISTS funnel_push_rules")
    op.execute("DROP TABLE IF EXISTS funnel_edges")
    op.execute("DROP TABLE IF EXISTS funnel_steps")
    op.execute("DROP INDEX IF EXISTS uq_funnel_versions_one_published_per_funnel")
    op.execute("DROP TABLE IF EXISTS funnel_versions")
    op.execute("DROP TABLE IF EXISTS funnels")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS custom_fields")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS has_card")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS call_time_text")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS country")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS age")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS name")
