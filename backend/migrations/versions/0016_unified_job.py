# backend/migrations/versions/0016_unified_job.py
"""Consolidate cron_job + backup_job → monitored_job; cron_job_run + backup_run → job_run.

Revision ID: 0016_unified_job
Revises: 0015_backup_files_count
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_unified_job"
down_revision = "0015_backup_files_count"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create monitored_job table ─────────────────────────────────────────
    op.create_table(
        "monitored_job",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "server_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("server.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("schedule", sa.String(120), nullable=False),
        sa.Column(
            "grace_period_min",
            sa.Integer,
            nullable=False,
            server_default=sa.text("10"),
        ),
        sa.Column(
            "ping_token",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'healthy'"),
        ),
        sa.Column("last_ping_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_ping_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_duration_sec", sa.Integer, nullable=True),
        sa.Column("last_size_bytes", sa.BigInteger, nullable=True),
        sa.Column("last_size_formatted", sa.Text, nullable=True),
        sa.Column("last_files_count", sa.Integer, nullable=True),
        sa.Column("last_exit_code", sa.Integer, nullable=True),
        sa.Column("previous_size_bytes", sa.BigInteger, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_monitored_job_server_id", "monitored_job", ["server_id"])

    # ── 2. Create job_run table ───────────────────────────────────────────────
    op.create_table(
        "job_run",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("monitored_job.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("duration_sec", sa.Integer, nullable=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=True),
        sa.Column("files_count", sa.Integer, nullable=True),
        sa.Column("exit_code", sa.Integer, nullable=True),
    )
    op.create_index("ix_job_run_job_id", "job_run", ["job_id"])

    # ── 3. Copy cron_job rows → monitored_job ────────────────────────────────
    op.execute(sa.text("""
        INSERT INTO monitored_job (
            id, server_id, name, description, schedule, grace_period_min,
            ping_token, status, last_ping_at, start_ping_at, last_duration_sec,
            last_size_bytes, last_size_formatted, last_files_count, last_exit_code,
            previous_size_bytes, created_at
        )
        SELECT
            id,
            server_id,
            name,
            NULL::text             AS description,
            schedule,
            grace_period_min,
            ping_token,
            status,
            last_ping_at,
            start_ping_at,
            last_duration_sec,
            NULL::bigint           AS last_size_bytes,
            NULL::text             AS last_size_formatted,
            NULL::integer          AS last_files_count,
            NULL::integer          AS last_exit_code,
            NULL::bigint           AS previous_size_bytes,
            NOW()                  AS created_at
        FROM cron_job
    """))

    # ── 4. Copy backup_job rows → monitored_job ──────────────────────────────
    # Convert expected_interval_hours → cron expression:
    #   24h  → '0 2 * * *'   (daily at 2am)
    #   168h → '0 2 * * 0'   (weekly Sunday 2am)
    #   other → '0 2 * * *'  (default daily at 2am)
    op.execute(sa.text("""
        INSERT INTO monitored_job (
            id, server_id, name, description, schedule, grace_period_min,
            ping_token, status, last_ping_at, start_ping_at, last_duration_sec,
            last_size_bytes, last_size_formatted, last_files_count, last_exit_code,
            previous_size_bytes, created_at
        )
        SELECT
            id,
            server_id,
            name,
            description,
            CASE expected_interval_hours
                WHEN 168 THEN '0 2 * * 0'
                ELSE           '0 2 * * *'
            END                    AS schedule,
            30                     AS grace_period_min,
            ping_token,
            status,
            last_ping_at,
            NULL::timestamptz      AS start_ping_at,
            NULL::integer          AS last_duration_sec,
            last_size_bytes,
            NULL::text             AS last_size_formatted,
            last_files_count,
            NULL::integer          AS last_exit_code,
            previous_size_bytes,
            created_at
        FROM backup_job
    """))

    # ── 5. Copy cron_job_run → job_run ────────────────────────────────────────
    op.execute(sa.text("""
        INSERT INTO job_run (
            id, job_id, ran_at, outcome, duration_sec,
            size_bytes, files_count, exit_code
        )
        SELECT
            r.id,
            mj.id              AS job_id,
            r.ran_at,
            r.outcome,
            r.duration_sec,
            NULL::bigint       AS size_bytes,
            NULL::integer      AS files_count,
            NULL::integer      AS exit_code
        FROM cron_job_run r
        JOIN monitored_job mj ON mj.id = r.cron_job_id
    """))

    # ── 6. Copy backup_run → job_run ─────────────────────────────────────────
    op.execute(sa.text("""
        INSERT INTO job_run (
            id, job_id, ran_at, outcome, duration_sec,
            size_bytes, files_count, exit_code
        )
        SELECT
            r.id,
            mj.id              AS job_id,
            r.ran_at,
            r.outcome,
            NULL::integer      AS duration_sec,
            r.size_bytes,
            r.files_count,
            r.exit_code
        FROM backup_run r
        JOIN monitored_job mj ON mj.id = r.backup_job_id
    """))

    # ── 7. Add job_id column to alert table ───────────────────────────────────
    op.add_column(
        "alert",
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("monitored_job.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # ── 8. Populate alert.job_id from cron_job_id and backup_job_id ──────────
    op.execute(sa.text("""
        UPDATE alert a
        SET job_id = mj.id
        FROM monitored_job mj
        WHERE a.cron_job_id IS NOT NULL
          AND mj.id = a.cron_job_id
    """))

    op.execute(sa.text("""
        UPDATE alert a
        SET job_id = mj.id
        FROM monitored_job mj
        WHERE a.backup_job_id IS NOT NULL
          AND mj.id = a.backup_job_id
    """))

    # ── 9. Update alert type strings ─────────────────────────────────────────
    op.execute(sa.text("""
        UPDATE alert
        SET type = CASE type
            WHEN 'cron_missing'    THEN 'job_missing'
            WHEN 'backup_missing'  THEN 'job_missing'
            WHEN 'backup_failure'  THEN 'job_failure'
            WHEN 'backup_size_drop' THEN 'job_size_drop'
            ELSE type
        END
        WHERE type IN ('cron_missing', 'backup_missing', 'backup_failure', 'backup_size_drop')
    """))

    # ── 10. Drop alert.cron_job_id and alert.backup_job_id ───────────────────
    # Drop FK constraints first, then the columns
    op.drop_constraint(
        "alert_cron_job_id_fkey",
        "alert",
        type_="foreignkey",
    )
    op.drop_constraint(
        "alert_backup_job_id_fkey",
        "alert",
        type_="foreignkey",
    )
    op.drop_column("alert", "cron_job_id")
    op.drop_column("alert", "backup_job_id")

    # ── 11. Drop old tables in dependency order ───────────────────────────────
    op.drop_table("backup_run")
    op.drop_table("cron_job_run")
    op.drop_table("backup_job")
    op.drop_table("cron_job")


def downgrade() -> None:
    # Destructive — data cannot be cleanly split back.
    pass
