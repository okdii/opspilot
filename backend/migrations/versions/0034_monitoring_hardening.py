"""Add extra_nginx_log_paths, detected_webroot to server; block_category to security_actions.

Revision ID: 0034_monitoring_hardening
Revises: 0033_ip_intel
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0034_monitoring_hardening"
down_revision = "0033_ip_intel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("server", sa.Column(
        "extra_nginx_log_paths", JSONB, nullable=True, server_default=sa.text("'[]'::jsonb")))
    op.add_column("server", sa.Column(
        "detected_webroot", sa.String(255), nullable=True))
    op.add_column("security_actions", sa.Column(
        "block_category", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("server", "extra_nginx_log_paths")
    op.drop_column("server", "detected_webroot")
    op.drop_column("security_actions", "block_category")
