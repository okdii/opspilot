# backend/migrations/versions/0017_job_run_label_started_at.py
"""Add label and started_at columns to job_run.

Revision ID: 0017_job_run_label_started_at
Revises: 0016_unified_job
"""
import sqlalchemy as sa
from alembic import op

revision = "0017_job_run_label_started_at"
down_revision = "0016_unified_job"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_run", sa.Column("label", sa.String(255), nullable=True))
    op.add_column("job_run", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("job_run", "started_at")
    op.drop_column("job_run", "label")
