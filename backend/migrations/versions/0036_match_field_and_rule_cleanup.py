"""Add match_field to log_alert_rule; delete two false-positive media PHP rules.

Revision ID: 0036_match_field_and_rule_cleanup
Revises: 0035_sppb_detection_rules
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0036_match_field_and_rule_cleanup"
down_revision = "0035_sppb_detection_rules"
branch_labels = None
depends_on = None

_BAD_PATTERNS = ("%/media/%.PHP%", "%/media/%.pHp%")


def upgrade() -> None:
    op.add_column("log_alert_rule", sa.Column("match_field", sa.String(50), nullable=True))
    conn = op.get_bind()
    for pattern in _BAD_PATTERNS:
        conn.execute(
            sa.text("DELETE FROM log_alert_rule WHERE pattern = :p"),
            {"p": pattern},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM log_alert_rule WHERE match_field IS NOT NULL"))
    op.drop_column("log_alert_rule", "match_field")
