"""Add content monitoring columns to service table.

Revision ID: 0029_content_monitoring
Revises: 0028_fail2ban_reset_events
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0029_content_monitoring"
down_revision = "0028_fail2ban_reset_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("service", sa.Column("expected_keyword", sa.Text(), nullable=True))
    op.add_column(
        "service",
        sa.Column(
            "forbidden_keywords_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )


def downgrade() -> None:
    op.drop_column("service", "forbidden_keywords_enabled")
    op.drop_column("service", "expected_keyword")
