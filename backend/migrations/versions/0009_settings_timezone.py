"""Add timezone column to app_settings.

Revision ID: 0009_settings_timezone
Revises: 0008_service_ssl_columns
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_settings_timezone"
down_revision = "0008_service_ssl_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("timezone", sa.String(60), nullable=False, server_default="UTC"),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "timezone")
