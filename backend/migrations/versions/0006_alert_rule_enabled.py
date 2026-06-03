"""add enabled column to alert_rule and log_alert_rule

Revision ID: 0006_alert_rule_enabled
Revises: 0005_server_metrics_compression
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_alert_rule_enabled"
down_revision = "0005_server_metrics_compression"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "alert_rule",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "log_alert_rule",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("log_alert_rule", "enabled")
    op.drop_column("alert_rule", "enabled")
