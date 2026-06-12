"""Add fail2ban monitoring tables

Revision ID: 0024_fail2ban
Revises: 0023_ai_base_url
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0024_fail2ban"
down_revision = "0023_ai_base_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fail2ban_jails",
        sa.Column("server_id", UUID(as_uuid=True), sa.ForeignKey("server.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jail_name", sa.Text(), nullable=False),
        sa.Column("currently_banned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_banned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currently_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("server_id", "jail_name"),
    )
    op.create_table(
        "fail2ban_banned_ips",
        sa.Column("server_id", UUID(as_uuid=True), sa.ForeignKey("server.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jail", sa.Text(), nullable=False),
        sa.Column("ip", sa.Text(), nullable=False),
        sa.Column("banned_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("server_id", "jail", "ip"),
    )
    op.create_table(
        "fail2ban_ban_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("server_id", UUID(as_uuid=True), sa.ForeignKey("server.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ip", sa.Text(), nullable=False),
        sa.Column("jail", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("server_id", "ip", "jail", "event_at", "action", name="uq_fail2ban_ban_events"),
    )
    op.create_index("ix_fail2ban_ban_events_server_event", "fail2ban_ban_events", ["server_id", "event_at"])
    op.create_table(
        "ip_geodata",
        sa.Column("ip", sa.Text(), primary_key=True),
        sa.Column("country_code", sa.Text(), nullable=True),
        sa.Column("country_name", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("isp", sa.Text(), nullable=True),
        sa.Column("cached_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )


def downgrade() -> None:
    op.drop_table("ip_geodata")
    op.drop_index("ix_fail2ban_ban_events_server_event", table_name="fail2ban_ban_events")
    op.drop_table("fail2ban_ban_events")
    op.drop_table("fail2ban_banned_ips")
    op.drop_table("fail2ban_jails")
