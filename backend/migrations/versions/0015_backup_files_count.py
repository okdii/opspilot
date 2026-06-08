# backend/migrations/versions/0015_backup_files_count.py
"""Add files_count to backup_run and last_files_count to backup_job.

Revision ID: 0015_backup_files_count
Revises: 0014_db_credential_label
"""
import sqlalchemy as sa
from alembic import op

revision = "0015_backup_files_count"
down_revision = "0014_db_credential_label"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("backup_run", sa.Column("files_count", sa.Integer(), nullable=True))
    op.add_column("backup_job", sa.Column("last_files_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("backup_run", "files_count")
    op.drop_column("backup_job", "last_files_count")
