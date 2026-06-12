"""Add bantime_seconds, findtime_seconds, maxretry to fail2ban_jails.

Revision ID: 0026_fail2ban_jail_config
Revises: 0025_fail2ban_action_check
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_fail2ban_jail_config"
down_revision = "0025_fail2ban_action_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fail2ban_jails", sa.Column("bantime_seconds", sa.Integer(), nullable=True))
    op.add_column("fail2ban_jails", sa.Column("findtime_seconds", sa.Integer(), nullable=True))
    op.add_column("fail2ban_jails", sa.Column("maxretry", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("fail2ban_jails", "maxretry")
    op.drop_column("fail2ban_jails", "findtime_seconds")
    op.drop_column("fail2ban_jails", "bantime_seconds")
