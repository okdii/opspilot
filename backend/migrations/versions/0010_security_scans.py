"""Add service_security_scans table and last_security_scan column.

Revision ID: 0010_security_scans
Revises: 0009_settings_timezone
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010_security_scans"
down_revision = "0009_settings_timezone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "service",
        sa.Column("last_security_scan", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "service_security_scans",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "service_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("service.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("grade", sa.String(2), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("tls_version", sa.String(20), nullable=True),
        sa.Column("tls_ok", sa.Boolean(), nullable=True),
        sa.Column("cipher_suite", sa.String(120), nullable=True),
        sa.Column("cipher_ok", sa.Boolean(), nullable=True),
        sa.Column("pfs_supported", sa.Boolean(), nullable=True),
        sa.Column("key_size", sa.Integer(), nullable=True),
        sa.Column("key_size_ok", sa.Boolean(), nullable=True),
        sa.Column("self_signed", sa.Boolean(), nullable=True),
        sa.Column("ocsp_stapling", sa.Boolean(), nullable=True),
        sa.Column("https_redirect", sa.Boolean(), nullable=True),
        sa.Column("hsts", sa.Boolean(), nullable=True),
        sa.Column("hsts_max_age", sa.Integer(), nullable=True),
        sa.Column("csp", sa.Boolean(), nullable=True),
        sa.Column("x_frame_options", sa.Boolean(), nullable=True),
        sa.Column("x_content_type", sa.Boolean(), nullable=True),
        sa.Column("referrer_policy", sa.Boolean(), nullable=True),
        sa.Column("permissions_policy", sa.Boolean(), nullable=True),
        sa.Column("server_disclosure", sa.Boolean(), nullable=True),
        sa.Column("x_powered_by", sa.String(255), nullable=True),
        sa.Column(
            "findings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    op.create_index(
        "ix_service_security_scans_service_id_scanned_at",
        "service_security_scans",
        ["service_id", sa.text("scanned_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_service_security_scans_service_id_scanned_at", table_name="service_security_scans")
    op.drop_table("service_security_scans")
    op.drop_column("service", "last_security_scan")
