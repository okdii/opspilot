# backend/migrations/versions/0019_service_mutes.py
"""Add server_service_mutes table.

Revision ID: 0019_service_mutes
Revises: 0018_job_last_label
"""
import sqlalchemy as sa
from alembic import op

revision = "0019_service_mutes"
down_revision = "0018_job_last_label"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_service_mutes",
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("service_name", sa.Text(), nullable=False),
        sa.Column(
            "muted_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["server_id"], ["server.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("server_id", "service_name"),
    )


def downgrade() -> None:
    op.drop_table("server_service_mutes")
