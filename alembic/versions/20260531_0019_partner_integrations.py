"""partner_integrations

Revision ID: 20260531_0019
Revises: 20260529_0016
Create Date: 2026-05-31 17:53:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260531_0019'
down_revision = '20260529_0016'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'partner_integrations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('postback_url', sa.String(), nullable=False),
        sa.Column('auth_token', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_partner_integrations_project_id', 'partner_integrations', ['project_id'])

    op.create_table(
        'lead_submissions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('lead_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('partner_integration_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('request_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('response_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['partner_integration_id'], ['partner_integrations.id'], ondelete='CASCADE')
    )
    op.create_index('ix_lead_submissions_lead_id', 'lead_submissions', ['lead_id'])
    op.create_index('ix_lead_submissions_partner_integration_id', 'lead_submissions', ['partner_integration_id'])
    op.create_index('ix_lead_submissions_status', 'lead_submissions', ['status'])

    op.add_column('leads', sa.Column('score_percent', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('leads', 'score_percent')
    op.drop_index('ix_lead_submissions_status', table_name='lead_submissions')
    op.drop_index('ix_lead_submissions_partner_integration_id', table_name='lead_submissions')
    op.drop_index('ix_lead_submissions_lead_id', table_name='lead_submissions')
    op.drop_table('lead_submissions')
    op.drop_index('ix_partner_integrations_project_id', table_name='partner_integrations')
    op.drop_table('partner_integrations')
