"""Attacker intelligence: ip_intel reputation cache + AbuseIPDB settings.

Revision ID: 0033_ip_intel
Revises: 0032_logs_service_compression
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0033_ip_intel"
down_revision = "0032_logs_service_compression"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ip_intel",
        sa.Column("ip", sa.Text, primary_key=True),
        sa.Column("abuse_score", sa.SmallInteger, nullable=True),
        sa.Column("country_code", sa.String(2), nullable=True),
        sa.Column("isp", sa.Text, nullable=True),
        sa.Column("usage_type", sa.Text, nullable=True),
        sa.Column("total_reports", sa.Integer, nullable=True),
        sa.Column("last_reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw", JSONB, nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
    )
    op.add_column("app_settings", sa.Column(
        "abuseipdb_enabled", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("app_settings", sa.Column(
        "abuseipdb_api_key_encrypted", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("app_settings", "abuseipdb_api_key_encrypted")
    op.drop_column("app_settings", "abuseipdb_enabled")
    op.drop_table("ip_intel")
