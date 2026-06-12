"""Clear fail2ban_ban_events corrupted by migration 0027 wrong direction.

Migration 0027 had an AT TIME ZONE direction bug that ADDED the UTC offset
instead of subtracting it, making timestamps worse. Deleting all events is
the safest fix — the collector re-populates from the server log within 5 min
with correct UTC timestamps (collector fix landed in v1.2.23).

Revision ID: 0028_fail2ban_reset_events
Revises: 0027_fail2ban_fix_timestamps
"""
from alembic import op

revision = "0028_fail2ban_reset_events"
down_revision = "0027_fail2ban_fix_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM fail2ban_ban_events;")


def downgrade() -> None:
    pass
