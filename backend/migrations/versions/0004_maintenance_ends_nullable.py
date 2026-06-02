"""maintenance_window.ends_at nullable for indefinite maintenance

Revision ID: 0004_maintenance_ends_nullable
Revises: 0003_settings_columns
Create Date: 2026-06-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_maintenance_ends_nullable"
down_revision: Union[str, None] = "0003_settings_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("maintenance_window", "ends_at", existing_type=sa.DateTime(timezone=True), nullable=True)


def downgrade() -> None:
    op.alter_column("maintenance_window", "ends_at", existing_type=sa.DateTime(timezone=True), nullable=False)
