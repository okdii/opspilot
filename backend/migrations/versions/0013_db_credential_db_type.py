"""Add db_type column to db_credential table.

Revision ID: 0013_db_credential_db_type
Revises: 0012_ssl_cert_domain_port_unique
"""
import sqlalchemy as sa
from alembic import op

revision = "0013_db_credential_db_type"
down_revision = "0012_ssl_cert_domain_port_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("db_credential", sa.Column("db_type", sa.String(16), nullable=False, server_default="mysql"))


def downgrade() -> None:
    op.drop_column("db_credential", "db_type")
