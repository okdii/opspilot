"""Enable columnar compression on server_logs and service_checks; CAGG retention.

Revision ID: 0032_logs_service_compression
Revises: 0031_security_actions
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0032_logs_service_compression"
down_revision = "0031_security_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Drop unused GIN index — never used by queries (all searches use ILIKE),
    #    and TimescaleDB cannot apply columnar compression to tables that have GIN indexes.
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_server_logs_fts"))

    # 2. Enable compression on server_logs.
    #    segmentby = server_id + source so the engine skips whole segments on
    #    per-server and per-source queries (which cover every query in the codebase).
    conn.execute(sa.text("""
        ALTER TABLE server_logs SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'server_id, source',
            timescaledb.compress_orderby   = 'time DESC'
        )
    """))
    conn.execute(sa.text(
        "SELECT add_compression_policy('server_logs', INTERVAL '2 days')"
    ))

    # 3. Enable compression on service_checks.
    conn.execute(sa.text("""
        ALTER TABLE service_checks SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'service_id',
            timescaledb.compress_orderby   = 'time DESC'
        )
    """))
    conn.execute(sa.text(
        "SELECT add_compression_policy('service_checks', INTERVAL '2 days')"
    ))

    # 4. Cap the hourly CAGG at 90 days — it has no retention policy and grows forever.
    conn.execute(sa.text(
        "SELECT add_retention_policy('server_metrics_hourly', INTERVAL '90 days')"
    ))
    # server_metrics_daily intentionally has no retention policy — daily aggregates
    # are kept forever for long-term capacity planning. Their size is negligible.

    # 5. Backfill: compress existing server_logs chunks already older than 2 days.
    #    Runs synchronously in the migration — may take a minute on large datasets.
    conn.execute(sa.text("""
        SELECT compress_chunk(format('%I.%I', chunk_schema, chunk_name))
        FROM timescaledb_information.chunks
        WHERE hypertable_name = 'server_logs'
          AND is_compressed    = false
          AND range_end        < NOW() - INTERVAL '2 days'
    """))

    # 6. Backfill: compress existing service_checks chunks older than 2 days.
    conn.execute(sa.text("""
        SELECT compress_chunk(format('%I.%I', chunk_schema, chunk_name))
        FROM timescaledb_information.chunks
        WHERE hypertable_name = 'service_checks'
          AND is_compressed    = false
          AND range_end        < NOW() - INTERVAL '2 days'
    """))


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text(
        "SELECT remove_retention_policy('server_metrics_hourly', if_exists => true)"
    ))

    for table in ("service_checks", "server_logs"):
        conn.execute(sa.text(
            "SELECT decompress_chunk(format('%I.%I', chunk_schema, chunk_name)) "
            "FROM timescaledb_information.chunks "
            "WHERE hypertable_name = :t AND is_compressed = true"
        ), {"t": table})
        conn.execute(sa.text(
            "SELECT remove_compression_policy(CAST(:t AS regclass), if_exists => true)"
        ), {"t": table})

    conn.execute(sa.text("ALTER TABLE service_checks SET (timescaledb.compress = false)"))
    conn.execute(sa.text("ALTER TABLE server_logs SET (timescaledb.compress = false)"))

    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_server_logs_fts
        ON server_logs USING GIN (to_tsvector('english', message))
    """))
