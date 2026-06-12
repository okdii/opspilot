"""Add CHECK constraint on fail2ban_ban_events.action

Revision ID: 0025_fail2ban_action_check
Revises: 0024_fail2ban
Create Date: 2026-06-12
"""
from alembic import op

revision = "0025_fail2ban_action_check"
down_revision = "0024_fail2ban"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_fail2ban_ban_events_action",
        "fail2ban_ban_events",
        "action IN ('ban', 'unban')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_fail2ban_ban_events_action",
        "fail2ban_ban_events",
        type_="check",
    )
