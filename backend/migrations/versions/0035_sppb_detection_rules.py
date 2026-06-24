"""Backfill SP Page Builder + case-insensitive PHP detection rules to existing servers.

Revision ID: 0035_sppb_detection_rules
Revises: 0034_monitoring_hardening
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0035_sppb_detection_rules"
down_revision = "0034_monitoring_hardening"
branch_labels = None
depends_on = None

NEW_RULES = [
    ("%access%", "%com_sppagebuilder%uploadCustomIcon%", "critical", 1, 300),
    ("%access%", "%/media/%.PHP%", "critical", 1, 300),
    ("%access%", "%/media/%.pHp%", "critical", 1, 300),
    ("%access%", "%POST%index.php% 200 %", "warning", 10, 60),
]


def upgrade() -> None:
    conn = op.get_bind()
    servers = conn.execute(sa.text("SELECT id FROM server")).fetchall()
    for (server_id,) in servers:
        for source, pattern, severity, threshold, window_sec in NEW_RULES:
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
                    "(server_id, source, pattern, severity, threshold, window_sec, cooldown_min, enabled) "
                    "VALUES (:sid, :source, :pattern, :severity, :threshold, :window_sec, 60, true)"
                ),
                {"sid": server_id, "source": source, "pattern": pattern,
                 "severity": severity, "threshold": threshold, "window_sec": window_sec},
            )


def downgrade() -> None:
    conn = op.get_bind()
    for source, pattern, *_ in NEW_RULES:
        conn.execute(
            sa.text("DELETE FROM log_alert_rule WHERE source = :source AND pattern = :pattern"),
            {"source": source, "pattern": pattern},
        )
