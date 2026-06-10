"""Add daily_report table and AI provider settings

Revision ID: 0022_daily_reports
Revises: 0021_smtp_enabled
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0022_daily_reports"
down_revision = "0021_smtp_enabled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_report",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("server_id", UUID(as_uuid=True), sa.ForeignKey("server.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("band", sa.Text(), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column("findings", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("data_snapshot", JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("ai_provider", sa.Text(), nullable=True),
        sa.Column("ai_model", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.UniqueConstraint("server_id", "report_date", name="uq_daily_report_server_date"),
    )
    op.create_index("ix_daily_report_server_id", "daily_report", ["server_id"])
    op.add_column("app_settings", sa.Column("ai_provider", sa.String(30), nullable=False, server_default="disabled"))
    op.add_column("app_settings", sa.Column("ai_model", sa.String(80), nullable=False, server_default="claude-sonnet-4-6"))
    op.add_column("app_settings", sa.Column("ai_api_key_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("app_settings", "ai_api_key_encrypted")
    op.drop_column("app_settings", "ai_model")
    op.drop_column("app_settings", "ai_provider")
    op.drop_index("ix_daily_report_server_id", table_name="daily_report")
    op.drop_table("daily_report")
