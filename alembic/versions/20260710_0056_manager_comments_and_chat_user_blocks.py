"""compatibility marker for manager comments and Telegram block status

Revision ID: 20260710_0056
Revises: 20260709_0056
Create Date: 2026-07-10 00:00:00.000000

The schema change lives in ``20260709_0056`` because that revision id reached
production before this canonical id was committed.  Keeping this no-op marker
preserves both migration histories.
"""

revision = "20260710_0056"
down_revision = "20260709_0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
