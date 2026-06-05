"""Add security audit columns to ssl_cert table.

Revision ID: 0011_ssl_cert_security
Revises: 0010_security_scans
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_ssl_cert_security"
down_revision = "0010_security_scans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ssl_cert", sa.Column("security_grade", sa.String(2), nullable=True))
    op.add_column("ssl_cert", sa.Column("security_score", sa.Integer, nullable=True))
    op.add_column("ssl_cert", sa.Column("security_scanned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ssl_cert", sa.Column("security_findings", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("ssl_cert", "security_findings")
    op.drop_column("ssl_cert", "security_scanned_at")
    op.drop_column("ssl_cert", "security_score")
    op.drop_column("ssl_cert", "security_grade")
