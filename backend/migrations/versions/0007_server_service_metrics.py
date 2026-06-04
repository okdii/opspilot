"""add server_service_metrics hypertable

Revision ID: 0007_server_service_metrics
Revises: 0006_alert_rule_enabled
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_server_service_metrics"
down_revision = "0006_alert_rule_enabled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        CREATE TABLE server_service_metrics (
            time            TIMESTAMPTZ NOT NULL,
            server_id       UUID        NOT NULL REFERENCES server(id) ON DELETE CASCADE,
            service_name    TEXT        NOT NULL,
            status          TEXT        NOT NULL,
            cpu_pct         FLOAT,
            mem_mb          FLOAT,
            uptime_seconds  INTEGER
        )
    """))
    conn.execute(sa.text(
        "SELECT create_hypertable('server_service_metrics', 'time', chunk_time_interval => INTERVAL '1 day')"
    ))
    conn.execute(sa.text("""
        CREATE INDEX ix_ssm_server_service_time
        ON server_service_metrics (server_id, service_name, time DESC)
    """))
    conn.execute(sa.text("SELECT add_retention_policy('server_service_metrics', INTERVAL '30 days')"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("SELECT remove_retention_policy('server_service_metrics', if_exists => true)"))
    conn.execute(sa.text("DROP TABLE IF EXISTS server_service_metrics"))
