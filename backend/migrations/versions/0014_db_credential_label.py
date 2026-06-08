# backend/migrations/versions/0014_db_credential_label.py
"""Add label column to db_credential table.

Revision ID: 0014_db_credential_label
Revises: 0013_db_credential_db_type
"""
import sqlalchemy as sa
from alembic import op

revision = "0014_db_credential_label"
down_revision = "0013_db_credential_db_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("db_credential", sa.Column("label", sa.String(60), nullable=True))


def downgrade() -> None:
    op.drop_column("db_credential", "label")
