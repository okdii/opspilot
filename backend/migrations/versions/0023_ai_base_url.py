"""Add ai_base_url to app_settings for custom provider

Revision ID: 0023_ai_base_url
Revises: 0022_daily_reports
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa

revision = "0023_ai_base_url"
down_revision = "0022_daily_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column("ai_base_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("app_settings", "ai_base_url")
