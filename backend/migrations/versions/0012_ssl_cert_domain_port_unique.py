"""Add unique constraint on ssl_cert (domain_id, port).

Revision ID: 0012_ssl_cert_domain_port_unique
Revises: 0011_ssl_cert_security
"""
from alembic import op

revision = "0012_ssl_cert_domain_port_unique"
down_revision = "0011_ssl_cert_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_ssl_cert_domain_port", "ssl_cert", ["domain_id", "port"])


def downgrade() -> None:
    op.drop_constraint("uq_ssl_cert_domain_port", "ssl_cert")
