"""Add discord notification columns to app_settings

Revision ID: 0020_discord_settings
Revises: 0019_service_mutes
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0020_discord_settings"
down_revision = "0019_service_mutes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column("discord_webhook_url", sa.Text(), nullable=True))
    op.add_column("app_settings", sa.Column("discord_enabled", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("app_settings", "discord_webhook_url")
    op.drop_column("app_settings", "discord_enabled")
