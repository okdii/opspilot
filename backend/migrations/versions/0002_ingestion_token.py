"""Add ingestion_token to server; expand onboarding_log for spec 03

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Per-server ingestion token (for Telegraf/Fluent Bit HTTPS push) ───────
    op.add_column(
        "server",
        sa.Column(
            "ingestion_token",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.create_index("ix_server_ingestion_token", "server", ["ingestion_token"], unique=True)

    # ── Onboarding log — extend to match spec 03 §10 ──────────────────────────
    op.add_column("onboarding_log", sa.Column("step_number", sa.Integer, nullable=True))
    op.add_column("onboarding_log", sa.Column("duration_ms", sa.Integer, nullable=True))
    op.add_column("onboarding_log", sa.Column("ssh_output", sa.Text, nullable=True))
    op.add_column("onboarding_log", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("onboarding_log", "started_at")
    op.drop_column("onboarding_log", "ssh_output")
    op.drop_column("onboarding_log", "duration_ms")
    op.drop_column("onboarding_log", "step_number")
    op.drop_index("ix_server_ingestion_token", "server")
    op.drop_column("server", "ingestion_token")
