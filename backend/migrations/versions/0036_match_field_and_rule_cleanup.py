"""Add match_field to log_alert_rule; delete two false-positive media PHP rules.

Revision ID: 0036_match_field_and_rule_cleanup
Revises: 0035_sppb_detection_rules
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0036_match_field_cleanup"
down_revision = "0035_sppb_detection_rules"
branch_labels = None
depends_on = None

_BAD_PATTERNS = ("%/media/%.PHP%", "%/media/%.pHp%")

_NEW_RULE = ("%access%", "%/media/%.php%", "critical", 1, 300, "url")


def upgrade() -> None:
    op.add_column("log_alert_rule", sa.Column("match_field", sa.String(50), nullable=True))
    conn = op.get_bind()
    for pattern in _BAD_PATTERNS:
        conn.execute(
            sa.text("DELETE FROM log_alert_rule WHERE pattern = :p"),
            {"p": pattern},
        )
    # Backfill the field-scoped replacement rule to all existing servers
    source, pattern, severity, threshold, window_sec, match_field = _NEW_RULE
    servers = conn.execute(sa.text("SELECT id FROM server")).fetchall()
    for (server_id,) in servers:
        exists = conn.execute(
            sa.text(
                "SELECT 1 FROM log_alert_rule "
                "WHERE server_id = :sid AND source = :source AND pattern = :pattern LIMIT 1"
            ),
            {"sid": server_id, "source": source, "pattern": pattern},
        ).first()
        if exists:
            continue
        conn.execute(
            sa.text(
                "INSERT INTO log_alert_rule "
                "(server_id, source, pattern, severity, threshold, window_sec, cooldown_min, enabled, match_field) "
                "VALUES (:sid, :source, :pattern, :severity, :threshold, :window_sec, 60, true, :match_field)"
            ),
            {"sid": server_id, "source": source, "pattern": pattern,
             "severity": severity, "threshold": threshold, "window_sec": window_sec,
             "match_field": match_field},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM log_alert_rule WHERE match_field IS NOT NULL"))
    # Also remove the backfilled field-scoped rule (match_field will be gone after drop)
    source, pattern, *_ = _NEW_RULE
    conn.execute(
        sa.text("DELETE FROM log_alert_rule WHERE source = :source AND pattern = :pattern"),
        {"source": source, "pattern": pattern},
    )
    op.drop_column("log_alert_rule", "match_field")
