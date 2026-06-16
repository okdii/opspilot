"""Backfill security detection rules + server_logs index.

Revision ID: 0030_security_detection
Revises: 0029_content_monitoring
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0030_security_detection"
down_revision = "0029_content_monitoring"
branch_labels = None
depends_on = None

SECURITY_RULES = [
    ("%access%", "%com_jce%profiles.import%", "critical", 1, 300),
    ("%access%", "%POST%.php% 200 %", "critical", 1, 300),
    ("%access%", "%/images/%.php% 200 %", "critical", 1, 300),
    ("%access%", "%/media/%.php% 200 %", "critical", 1, 300),
    ("%access%", "%/uploads/%.php% 200 %", "critical", 1, 300),
    ("%access%", "%/files/%.php% 200 %", "critical", 1, 300),
    ("%access%", "%/tmp/%.php% 200 %", "critical", 1, 300),
    ("%access%", "%/cache/%.php% 200 %", "critical", 1, 300),
    ("%access%", "% 404 %", "warning", 20, 300),
    ("auditd", "%webroot_write%", "critical", 1, 300),
    ("auditd", "%webshell_exec%", "critical", 1, 300),
    ("auditd", "%ssh_key_change%", "critical", 1, 300),
    ("auditd", "%log_tamper%", "critical", 1, 300),
    ("mariadb_general", "%CREATE USER%", "critical", 1, 300),
    ("mariadb_general", "%GRANT ALL%", "critical", 1, 300),
    ("auth", "%Accepted publickey%", "warning", 1, 300),
]


def upgrade() -> None:
    conn = op.get_bind()
    servers = conn.execute(sa.text("SELECT id FROM server")).fetchall()
    for (server_id,) in servers:
        for source, pattern, severity, threshold, window_sec in SECURITY_RULES:
            exists = conn.execute(
                sa.text(
                    "SELECT 1 FROM log_alert_rule "
                    "WHERE server_id = :sid AND source = :source AND pattern = :pattern "
                    "LIMIT 1"
                ),
                {"sid": server_id, "source": source, "pattern": pattern},
            ).first()
            if exists:
                continue
            conn.execute(
                sa.text(
                    "INSERT INTO log_alert_rule "
                    "(server_id, source, pattern, severity, threshold, window_sec, "
                    " cooldown_min, enabled) "
                    "VALUES (:sid, :source, :pattern, :severity, :threshold, :window_sec, "
                    " 60, true)"
                ),
                {
                    "sid": server_id, "source": source, "pattern": pattern,
                    "severity": severity, "threshold": threshold, "window_sec": window_sec,
                },
            )
    op.create_index(
        "ix_server_logs_server_time", "server_logs", ["server_id", sa.text("time DESC")],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_server_logs_server_time", table_name="server_logs", if_exists=True)
    conn = op.get_bind()
    for source, pattern, *_ in SECURITY_RULES:
        conn.execute(
            sa.text("DELETE FROM log_alert_rule WHERE source = :source AND pattern = :pattern"),
            {"source": source, "pattern": pattern},
        )
