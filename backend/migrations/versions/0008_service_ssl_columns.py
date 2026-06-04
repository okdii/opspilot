"""Add SSL tracking columns to service table.

Revision ID: 0008_service_ssl_columns
Revises: 0007_server_service_metrics
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_service_ssl_columns"
down_revision = "0007_server_service_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("service", sa.Column("ssl_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("service", sa.Column("ssl_warn_days", sa.Integer(), nullable=False, server_default="30"))
    op.add_column("service", sa.Column("ssl_critical_days", sa.Integer(), nullable=False, server_default="7"))
    op.add_column("service", sa.Column("ssl_expiry_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column("service", sa.Column("ssl_days_remaining", sa.Integer(), nullable=True))
    op.add_column("service", sa.Column("ssl_status", sa.String(30), nullable=True))
    op.add_column("service", sa.Column("ssl_issuer", sa.String(255), nullable=True))
    op.add_column("service", sa.Column("ssl_last_checked", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for col in ("ssl_enabled", "ssl_warn_days", "ssl_critical_days",
                "ssl_expiry_date", "ssl_days_remaining", "ssl_status",
                "ssl_issuer", "ssl_last_checked"):
        op.drop_column("service", col)
