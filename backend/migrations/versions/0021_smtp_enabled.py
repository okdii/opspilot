"""Add smtp_enabled column to app_settings

Revision ID: 0021_smtp_enabled
Revises: 0020_discord_settings
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0021_smtp_enabled"
down_revision = "0020_discord_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("smtp_enabled", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "smtp_enabled")
