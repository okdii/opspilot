"""Security auto-response: actions ledger + auto-response settings.

Revision ID: 0031_security_actions
Revises: 0030_security_detection
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0031_security_actions"
down_revision = "0030_security_detection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_actions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("server_id", UUID(as_uuid=True),
                  sa.ForeignKey("server.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_id", UUID(as_uuid=True),
                  sa.ForeignKey("alert.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action_type", sa.String(40), nullable=False),
        sa.Column("target", sa.Text, nullable=True),
        sa.Column("tier", sa.SmallInteger, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending_approval"),
        sa.Column("actor", sa.String(255), nullable=False, server_default="auto"),
        sa.Column("confidence", sa.String(10), nullable=True),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("reversal", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_security_actions_alert", "security_actions", ["alert_id"])
    op.create_index("ix_security_actions_server_status", "security_actions",
                    ["server_id", "status"])
    op.add_column("server", sa.Column(
        "auto_response_enabled", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("server", sa.Column(
        "block_ttl_hours", sa.Integer, nullable=False, server_default="24"))
    op.add_column("app_settings", sa.Column(
        "auto_response_enabled", sa.Boolean, nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("app_settings", "auto_response_enabled")
    op.drop_column("server", "block_ttl_hours")
    op.drop_column("server", "auto_response_enabled")
    op.drop_index("ix_security_actions_server_status", table_name="security_actions")
    op.drop_index("ix_security_actions_alert", table_name="security_actions")
    op.drop_table("security_actions")
