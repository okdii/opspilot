"""Add exclude_pattern to log_alert_rule; delete orphan legacy rules; backfill exclusions.

Revision ID: 0037_exclude_pattern
Revises: 0036_match_field_cleanup
Create Date: 2026-06-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0037_exclude_pattern"
down_revision = "0036_match_field_cleanup"
branch_labels = None
depends_on = None

_ORPHAN_PATTERNS = ("%/media/%.PHP%", "%/media/%.pHp%")


def upgrade() -> None:
    # 1. Add column
    op.add_column("log_alert_rule",
        sa.Column("exclude_pattern", sa.String(255), nullable=True))

    conn = op.get_bind()

    # 2. Delete orphan legacy rules from all servers
    for pattern in _ORPHAN_PATTERNS:
        conn.execute(
            sa.text("DELETE FROM log_alert_rule WHERE pattern = :p"),
            {"p": pattern},
        )

    # 3. Backfill exclude_pattern on existing server rules
    conn.execute(
        sa.text(
            "UPDATE log_alert_rule "
            "SET exclude_pattern = :excl "
            "WHERE pattern = :pat"
        ),
        {"excl": "%jsvisit_counter%", "pat": "%POST%.php% 200 %"},
    )
    conn.execute(
        sa.text(
            "UPDATE log_alert_rule "
            "SET exclude_pattern = :excl "
            "WHERE pattern LIKE :pat"
        ),
        {"excl": "%/administrator/%", "pat": "%com_sppagebuilder%uploadCustomIcon%"},
    )


def downgrade() -> None:
    op.drop_column("log_alert_rule", "exclude_pattern")
