"""Optional photo albums for scheduled operator messages."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261010_0081"
down_revision = "20261008_0080"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("scheduled_messages", sa.Column("album_files", JSONB(), nullable=True))


def downgrade():
    op.drop_column("scheduled_messages", "album_files")
