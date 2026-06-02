"""Initial schema — all tables, hypertables, aggregates, indexes, retention policies

Revision ID: 0001
Revises:
Create Date: 2026-06-01
"""
import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── TimescaleDB extension ────────────────────────────────────────────────
    conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))

    # ── Relational tables ─────────────────────────────────────────────────────

    op.create_table(
        "organization",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("slug", sa.String(50), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_organization_slug", "organization", ["slug"])

    op.create_table(
        "user",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("username", sa.String(80), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_user_username", "user", ["username"])

    op.create_table(
        "user_organization",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("user_id", "org_id"),
    )

    op.create_table(
        "session",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jti", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
    )
    op.create_index("ix_session_jti", "session", ["jti"])

    op.create_table(
        "invite",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("token", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_invite_token", "invite", ["token"])

    op.create_table(
        "server",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("host", sa.Text, nullable=False),
        sa.Column("ssh_port", sa.Integer, nullable=False, server_default="22"),
        sa.Column("ssh_user", sa.String(80), nullable=False),
        sa.Column("ssh_auth_type", sa.String(20), nullable=False),
        sa.Column("ssh_key_encrypted", sa.Text, nullable=True),
        sa.Column("ssh_password_encrypted", sa.Text, nullable=True),
        sa.Column("os_distro", sa.String(120), nullable=True),
        sa.Column("kernel_version", sa.String(80), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.String(30)), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_server_org_id", "server", ["org_id"])

    op.create_table(
        "onboarding_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("server.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_onboarding_log_server_id", "onboarding_log", ["server_id"])

    op.create_table(
        "service",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("server.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("port", sa.Integer, nullable=True),
        sa.Column("expected_status", sa.Integer, nullable=True),
        sa.Column("interval_sec", sa.Integer, nullable=False, server_default="60"),
        sa.Column("timeout_sec", sa.Integer, nullable=False, server_default="10"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_public", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ignore_ssl_errors", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("last_checked", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(20), nullable=True),
    )
    op.create_index("ix_service_server_id", "service", ["server_id"])

    op.create_table(
        "incident",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("service.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_sec", sa.Integer, nullable=True),
    )
    op.create_index("ix_incident_service_id", "incident", ["service_id"])

    op.create_table(
        "domain",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("registrar", sa.String(120), nullable=True),
        sa.Column("expiry_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("days_remaining", sa.Integer, nullable=True),
        sa.Column("warn_days", sa.Integer, nullable=False, server_default="60"),
        sa.Column("critical_days", sa.Integer, nullable=False, server_default="30"),
        sa.Column("last_checked", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(30), nullable=True),
    )
    op.create_index("ix_domain_org_id", "domain", ["org_id"])

    op.create_table(
        "ssl_cert",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("domain.id", ondelete="CASCADE"), nullable=False),
        sa.Column("port", sa.Integer, nullable=False, server_default="443"),
        sa.Column("issuer", sa.String(255), nullable=True),
        sa.Column("expiry_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("days_remaining", sa.Integer, nullable=True),
        sa.Column("warn_days", sa.Integer, nullable=False, server_default="30"),
        sa.Column("critical_days", sa.Integer, nullable=False, server_default="7"),
        sa.Column("last_checked", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(30), nullable=True),
    )
    op.create_index("ix_ssl_cert_domain_id", "ssl_cert", ["domain_id"])

    op.create_table(
        "maintenance_window",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("server.id", ondelete="CASCADE"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_maintenance_window_server_id", "maintenance_window", ["server_id"])

    op.create_table(
        "alert_rule",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("server.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric", sa.String(50), nullable=False),
        sa.Column("threshold", sa.Float, nullable=False),
        sa.Column("rolling_window_min", sa.Integer, nullable=False, server_default="5"),
        sa.Column("cooldown_min", sa.Integer, nullable=False, server_default="60"),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_alert_rule_server_id", "alert_rule", ["server_id"])

    op.create_table(
        "log_alert_rule",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("server.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("pattern", sa.Text, nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("threshold", sa.Integer, nullable=False, server_default="1"),
        sa.Column("window_sec", sa.Integer, nullable=False, server_default="60"),
        sa.Column("cooldown_min", sa.Integer, nullable=False, server_default="60"),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_log_alert_rule_server_id", "log_alert_rule", ["server_id"])

    op.create_table(
        "cron_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("server.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("schedule", sa.String(80), nullable=False),
        sa.Column("grace_period_min", sa.Integer, nullable=False, server_default="5"),
        sa.Column("ping_token", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("last_ping_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_ping_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_duration_sec", sa.Integer, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
    )
    op.create_index("ix_cron_job_server_id", "cron_job", ["server_id"])

    op.create_table(
        "cron_job_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("cron_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cron_job.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_sec", sa.Integer, nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False),
    )
    op.create_index("ix_cron_job_run_cron_job_id", "cron_job_run", ["cron_job_id"])

    op.create_table(
        "backup_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("server.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("expected_interval_hours", sa.Integer, nullable=False, server_default="24"),
        sa.Column("ping_token", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("last_ping_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_size_bytes", sa.BigInteger, nullable=True),
        sa.Column("last_status_text", sa.Text, nullable=True),
        sa.Column("previous_size_bytes", sa.BigInteger, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_backup_job_server_id", "backup_job", ["server_id"])

    op.create_table(
        "backup_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("backup_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("backup_job.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=True),
        sa.Column("exit_code", sa.Integer, nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False),
    )
    op.create_index("ix_backup_run_backup_job_id", "backup_run", ["backup_job_id"])

    op.create_table(
        "db_credential",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("server.id", ondelete="CASCADE"), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer, nullable=False, server_default="3306"),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("password_encrypted", sa.Text, nullable=False),
        sa.Column("is_replica", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("last_deadlock_count", sa.Integer, nullable=True),
    )
    op.create_index("ix_db_credential_server_id", "db_credential", ["server_id"])

    op.create_table(
        "alert",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("server.id", ondelete="SET NULL"), nullable=True),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("service.id", ondelete="SET NULL"), nullable=True),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("domain.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ssl_cert_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ssl_cert.id", ondelete="SET NULL"), nullable=True),
        sa.Column("cron_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cron_job.id", ondelete="SET NULL"), nullable=True),
        sa.Column("backup_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("backup_job.id", ondelete="SET NULL"), nullable=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="firing"),
        sa.Column("consecutive_clear_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_alert_server_id", "alert", ["server_id"])
    op.create_index("ix_alert_state", "alert", ["state"])

    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("smtp_host", sa.String(255), nullable=True),
        sa.Column("smtp_port", sa.Integer, nullable=True),
        sa.Column("smtp_user", sa.String(255), nullable=True),
        sa.Column("smtp_password_encrypted", sa.Text, nullable=True),
        sa.Column("smtp_from", sa.String(255), nullable=True),
        sa.Column("base_url", sa.Text, nullable=True),
        sa.Column("metrics_retention_days", sa.Integer, nullable=False, server_default="30"),
        sa.Column("logs_retention_days", sa.Integer, nullable=False, server_default="30"),
        sa.Column("service_checks_retention_days", sa.Integer, nullable=False, server_default="90"),
    )
    # Insert single settings row
    conn.execute(sa.text("INSERT INTO app_settings (id) VALUES (1)"))

    # ── TimescaleDB hypertables ───────────────────────────────────────────────

    conn.execute(sa.text("""
        CREATE TABLE server_metrics (
            time        TIMESTAMPTZ      NOT NULL,
            server_id   UUID             NOT NULL REFERENCES server(id) ON DELETE CASCADE,
            metric_name TEXT             NOT NULL,
            value       DOUBLE PRECISION NOT NULL,
            labels      JSONB
        )
    """))
    conn.execute(sa.text(
        "SELECT create_hypertable('server_metrics', 'time', chunk_time_interval => INTERVAL '1 day')"
    ))
    conn.execute(sa.text(
        "CREATE INDEX ix_server_metrics_lookup ON server_metrics (server_id, metric_name, time DESC)"
    ))

    conn.execute(sa.text("""
        CREATE TABLE server_logs (
            time        TIMESTAMPTZ NOT NULL,
            server_id   UUID        NOT NULL REFERENCES server(id) ON DELETE CASCADE,
            source      TEXT        NOT NULL,
            severity    TEXT        NOT NULL,
            message     TEXT        NOT NULL,
            raw         JSONB
        )
    """))
    conn.execute(sa.text(
        "SELECT create_hypertable('server_logs', 'time', chunk_time_interval => INTERVAL '1 day')"
    ))
    conn.execute(sa.text("CREATE INDEX ix_server_logs_source   ON server_logs (server_id, source, time DESC)"))
    conn.execute(sa.text("CREATE INDEX ix_server_logs_severity ON server_logs (server_id, severity, time DESC)"))
    conn.execute(sa.text("CREATE INDEX ix_server_logs_fts ON server_logs USING GIN (to_tsvector('english', message))"))

    conn.execute(sa.text("""
        CREATE TABLE service_checks (
            time             TIMESTAMPTZ NOT NULL,
            service_id       UUID        NOT NULL REFERENCES service(id) ON DELETE CASCADE,
            status           TEXT        NOT NULL,
            response_time_ms INTEGER
        )
    """))
    conn.execute(sa.text(
        "SELECT create_hypertable('service_checks', 'time', chunk_time_interval => INTERVAL '1 day')"
    ))
    conn.execute(sa.text(
        "CREATE INDEX ix_service_checks_lookup ON service_checks (service_id, time DESC)"
    ))

    # ── Retention policies ────────────────────────────────────────────────────
    conn.execute(sa.text("SELECT add_retention_policy('server_metrics', INTERVAL '30 days')"))
    conn.execute(sa.text("SELECT add_retention_policy('server_logs',    INTERVAL '30 days')"))
    conn.execute(sa.text("SELECT add_retention_policy('service_checks', INTERVAL '90 days')"))

    # ── Continuous aggregates ─────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE MATERIALIZED VIEW server_metrics_hourly
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 hour', time) AS bucket,
            server_id,
            metric_name,
            AVG(value)          AS avg_value,
            MIN(value)          AS min_value,
            MAX(value)          AS max_value,
            last(value, time)   AS last_value
        FROM server_metrics
        GROUP BY bucket, server_id, metric_name
        WITH NO DATA
    """))
    conn.execute(sa.text("""
        SELECT add_continuous_aggregate_policy('server_metrics_hourly',
            start_offset      => INTERVAL '3 hours',
            end_offset        => INTERVAL '1 hour',
            schedule_interval => INTERVAL '1 hour')
    """))

    conn.execute(sa.text("""
        CREATE MATERIALIZED VIEW server_metrics_daily
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 day', time) AS bucket,
            server_id,
            metric_name,
            AVG(value)          AS avg_value,
            MIN(value)          AS min_value,
            MAX(value)          AS max_value,
            last(value, time)   AS last_value
        FROM server_metrics
        GROUP BY bucket, server_id, metric_name
        WITH NO DATA
    """))
    conn.execute(sa.text("""
        SELECT add_continuous_aggregate_policy('server_metrics_daily',
            start_offset      => INTERVAL '3 days',
            end_offset        => INTERVAL '1 day',
            schedule_interval => INTERVAL '1 day')
    """))

    # ── opspilot_writer (INSERT-only Telegraf user) ───────────────────────────
    writer_password = os.environ.get("OPSPILOT_WRITER_PASSWORD", "")
    conn.execute(sa.text("SELECT set_config('app.writer_password', :pwd, false)").bindparams(pwd=writer_password))
    conn.execute(sa.text("""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'opspilot_writer') THEN
            EXECUTE format(
              'CREATE ROLE opspilot_writer WITH LOGIN PASSWORD %L NOINHERIT',
              current_setting('app.writer_password')
            );
          END IF;
        END $$
    """))
    conn.execute(sa.text("GRANT INSERT ON server_metrics, server_logs, service_checks TO opspilot_writer"))


def downgrade() -> None:
    conn = op.get_bind()

    # Drop continuous aggregates
    conn.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS server_metrics_daily CASCADE"))
    conn.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS server_metrics_hourly CASCADE"))

    # Drop hypertables
    conn.execute(sa.text("DROP TABLE IF EXISTS service_checks CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS server_logs CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS server_metrics CASCADE"))

    # Drop relational tables in reverse FK order
    for tbl in [
        "app_settings", "alert", "db_credential",
        "backup_run", "backup_job", "cron_job_run", "cron_job",
        "log_alert_rule", "alert_rule", "maintenance_window",
        "ssl_cert", "domain", "incident", "service",
        "onboarding_log", "server", "invite",
        "session", "user_organization", "user", "organization",
    ]:
        conn.execute(sa.text(f"DROP TABLE IF EXISTS {tbl} CASCADE"))
