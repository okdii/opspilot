# backend/migrations/versions/0018_job_last_label.py
"""Add last_label column to monitored_job.

Revision ID: 0018_job_last_label
Revises: 0017_job_run_label_started_at
"""
import sqlalchemy as sa
from alembic import op

revision = "0018_job_last_label"
down_revision = "0017_job_run_label_started_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("monitored_job", sa.Column("last_label", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("monitored_job", "last_label")
