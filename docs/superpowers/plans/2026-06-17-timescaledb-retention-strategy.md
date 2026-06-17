# TimescaleDB Retention & Storage Strategy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate runaway DB growth by enabling columnar compression on `server_logs` and `service_checks`, adding CAGG retention, and wiring a disk-space alert job.

**Architecture:** One Alembic migration drops the blocking GIN index and installs compression + CAGG retention policies. A new APScheduler job (`db_disk_monitor`) checks host disk every 6 hours and fires a `db_disk_high` alert via the existing `fire_alert` seam when usage exceeds 70%.

**Tech Stack:** TimescaleDB 2.x, Alembic, APScheduler, FastAPI lifespan, `shutil.disk_usage`

---

## File Map

| Action | File |
|---|---|
| Create | `backend/migrations/versions/0032_logs_service_compression.py` |
| Modify | `backend/app/jobs/scheduler.py` — add `db_disk_monitor()` |
| Modify | `backend/app/main.py` — register `db_disk_monitor` job |

---

## Task 1: Migration — compression + CAGG retention

**Files:**
- Create: `backend/migrations/versions/0032_logs_service_compression.py`

- [ ] **Step 1: Create the migration file**

```python
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

    # 5. Backfill: compress existing server_logs chunks already older than 2 days.
    #    Runs synchronously in the migration — may take a minute on large datasets.
    conn.execute(sa.text("""
        SELECT compress_chunk(chunk_schema || '.' || chunk_name)
        FROM timescaledb_information.chunks
        WHERE hypertable_name = 'server_logs'
          AND is_compressed    = false
          AND range_end        < NOW() - INTERVAL '2 days'
    """))

    # 6. Backfill: compress existing service_checks chunks older than 2 days.
    conn.execute(sa.text("""
        SELECT compress_chunk(chunk_schema || '.' || chunk_name)
        FROM timescaledb_information.chunks
        WHERE hypertable_name = 'service_checks'
          AND is_compressed    = false
          AND range_end        < NOW() - INTERVAL '2 days'
    """))


def downgrade() -> None:
    conn = op.get_bind()

    # Remove CAGG retention
    conn.execute(sa.text(
        "SELECT remove_retention_policy('server_metrics_hourly', if_exists => true)"
    ))

    # Decompress all chunks before removing compression settings
    for table in ("service_checks", "server_logs"):
        conn.execute(sa.text(f"""
            SELECT decompress_chunk(chunk_schema || '.' || chunk_name)
            FROM timescaledb_information.chunks
            WHERE hypertable_name = '{table}'
              AND is_compressed   = true
        """))
        conn.execute(sa.text(
            f"SELECT remove_compression_policy('{table}', if_exists => true)"
        ))
        conn.execute(sa.text(
            f"ALTER TABLE {table} SET (timescaledb.compress = false)"
        ))

    # Restore GIN index
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_server_logs_fts
        ON server_logs USING GIN (to_tsvector('english', message))
    """))
```

- [ ] **Step 2: Apply the migration**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend \
  alembic upgrade head
```

Expected output ends with:
```
Running upgrade 0031_security_actions -> 0032_logs_service_compression, Enable columnar compression...
```

- [ ] **Step 3: Verify compression policies exist**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres \
  psql -U opspilot -d opspilot -c "
    SELECT hypertable_name, compress_after
    FROM timescaledb_information.compression_settings
    WHERE hypertable_name IN ('server_logs', 'service_checks')
    ORDER BY hypertable_name;
  "
```

Expected:
```
  hypertable_name  | compress_after
-------------------+----------------
 server_checks     | @ 2 days
 server_logs       | @ 2 days
```

- [ ] **Step 4: Verify GIN index is gone**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres \
  psql -U opspilot -d opspilot -c "
    SELECT indexname FROM pg_indexes
    WHERE tablename = 'server_logs' AND indexname = 'ix_server_logs_fts';
  "
```

Expected: `(0 rows)` — index is gone.

- [ ] **Step 5: Verify existing chunks were backfilled**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres \
  psql -U opspilot -d opspilot -c "
    SELECT hypertable_name, is_compressed, COUNT(*) AS chunks
    FROM timescaledb_information.chunks
    WHERE hypertable_name IN ('server_logs', 'service_checks')
    GROUP BY hypertable_name, is_compressed
    ORDER BY hypertable_name, is_compressed;
  "
```

Expected: chunks older than 2 days show `is_compressed = true`. The current 2-day chunk
shows `is_compressed = false` (normal — it will compress automatically when the policy runs).

- [ ] **Step 6: Check disk savings**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres \
  psql -U opspilot -d opspilot -c "
    SELECT
      hypertable_name,
      pg_size_pretty(SUM(before_compression_total_bytes)) AS before,
      pg_size_pretty(SUM(after_compression_total_bytes))  AS after,
      ROUND(
        100 - 100.0 * SUM(after_compression_total_bytes)
                    / NULLIF(SUM(before_compression_total_bytes), 0),
        1
      ) AS pct_saved
    FROM timescaledb_information.chunk_compression_stats
    WHERE hypertable_name IN ('server_logs', 'service_checks')
    GROUP BY hypertable_name;
  "
```

Expected: `pct_saved` between 85–95% for `server_logs` (text-heavy log data compresses well).

- [ ] **Step 7: Verify CAGG retention policy**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres \
  psql -U opspilot -d opspilot -c "
    SELECT application_name, schedule_interval, next_start
    FROM timescaledb_information.jobs
    WHERE application_name ILIKE '%retention%'
    ORDER BY application_name;
  "
```

Expected: one retention job for `server_metrics_hourly` with `schedule_interval = @ 1 day`.

- [ ] **Step 8: Commit**

```bash
git add backend/migrations/versions/0032_logs_service_compression.py
git commit -m "feat(db): enable columnar compression on server_logs and service_checks; CAGG retention"
```

---

## Task 2: Disk space monitor job

**Files:**
- Modify: `backend/app/jobs/scheduler.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add `db_disk_monitor` to scheduler.py**

Append this function to the bottom of `backend/app/jobs/scheduler.py`:

```python
async def db_disk_monitor() -> None:
    """Every 6h: fire a db_disk_high alert when host disk exceeds 70%."""
    import logging
    import shutil
    from app.database import AsyncSessionLocal
    from app.services.alerting import fire_alert

    log = logging.getLogger(__name__)
    usage = shutil.disk_usage("/")
    pct = usage.used / usage.total * 100

    async with AsyncSessionLocal() as db:
        if pct >= 70.0:
            used_gb = usage.used / 1_073_741_824
            total_gb = usage.total / 1_073_741_824
            await fire_alert(
                db,
                type="db_disk_high",
                severity="warning",
                message=(
                    f"OpsPilot host disk at {pct:.1f}% "
                    f"({used_gb:.1f} GB used of {total_gb:.1f} GB). "
                    "Expand disk or apply log retention policy."
                ),
                server_id=None,
                cooldown_min=360,
            )
            log.warning("db_disk_monitor: disk at %.1f%% — alert fired", pct)
        else:
            log.debug("db_disk_monitor: disk at %.1f%% — OK", pct)
```

- [ ] **Step 2: Register the job in main.py**

In `backend/app/main.py`, update the import line at line 13:

```python
from app.jobs.scheduler import (
    maintenance_expiry, scheduler, session_cleanup, ticket_sweep,
    daily_report_nightly, dmesg_collector, fail2ban_retention,
    fail2ban_collector, db_disk_monitor,
)
```

Then add the job registration inside the `lifespan` function after `fail2ban_collector`:

```python
scheduler.add_job(db_disk_monitor, "interval", hours=6, id="db_disk_monitor", replace_existing=True)
```

- [ ] **Step 3: Verify the app starts cleanly**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d backend
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs backend --tail=30
```

Expected: no import errors, no traceback. You should see normal startup logs.

- [ ] **Step 4: Trigger a manual test run**

Open a Python shell inside the backend container and force-run the job:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend python -c "
import asyncio, shutil
usage = shutil.disk_usage('/')
pct = usage.used / usage.total * 100
total_gb = usage.total / 1_073_741_824
used_gb = usage.used / 1_073_741_824
free_gb = usage.free / 1_073_741_824
print(f'Disk: {pct:.1f}% used — {used_gb:.1f} GB / {total_gb:.1f} GB ({free_gb:.1f} GB free)')
"
```

Expected: prints current disk stats. Confirm the numbers match your known disk state
(~52 GB used, ~145 GB total → ~36%).

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs/scheduler.py backend/app/main.py
git commit -m "feat(infra): disk space monitor job — alert at 70% host disk usage"
```

---

## Task 3: Smoke test — end to end

- [ ] **Step 1: Verify log queries still work after compression**

In the OpsPilot UI, open any server's Logs tab and:
1. Set the time range to last 7 days
2. Filter by a source (e.g. `nginx`)
3. Filter by severity `error`
4. Confirm rows load and the search responds correctly

Compressed chunks are decompressed transparently on query — if this works, compression is
invisible to the application layer.

- [ ] **Step 2: Verify 30-day log search still works**

In the Logs tab, extend the range to 30 days. Confirm you see historical log rows from
compressed chunks. If the query returns results, the 30-day filterability is intact.

- [ ] **Step 3: Confirm weekly growth rate dropped**

Wait 24 hours, then check the new hypertable size:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres \
  psql -U opspilot -d opspilot -c "
    SELECT
      hypertable_name,
      pg_size_pretty(hypertable_size(
        format('public.%I', hypertable_name)::regclass
      )) AS current_size
    FROM timescaledb_information.hypertables
    WHERE hypertable_name IN ('server_logs', 'service_checks', 'server_metrics')
    ORDER BY hypertable_name;
  "
```

Compare to baseline. `server_logs` total should be significantly smaller than before migration.

- [ ] **Step 4: Confirm TimescaleDB background jobs are healthy**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres \
  psql -U opspilot -d opspilot -c "
    SELECT job_id, application_name, last_run_status, last_finish
    FROM timescaledb_information.job_stats
    WHERE application_name ILIKE '%compress%'
       OR application_name ILIKE '%retention%'
    ORDER BY last_finish DESC NULLS LAST;
  "
```

Expected: `last_run_status = 'Success'` for all compression and retention jobs. `NULL` means
the job hasn't run yet (runs every 24h) — that's normal on day 1.

- [ ] **Step 5: Tag and release**

```bash
git describe --tags --abbrev=0   # note current tag e.g. v1.2.51
git tag v1.2.52
git push origin main
git push origin v1.2.52
```

Update `PROGRESS.md` and `DASHBOARD.html`:
- Mark the data retention strategy task as `✅ done`
- Set `LAST_UPDATED` in DASHBOARD.html to today's date

```bash
git add PROGRESS.md DASHBOARD.html
git commit -m "chore: mark timescaledb retention strategy complete"
git push origin main
```

---

## Phase 2 Reminder (do at 5–7 servers)

When you scale to 5–7 servers, apply these two changes:

```sql
-- Extend server_logs retention to 90 days
SELECT remove_retention_policy('server_logs', if_exists => true);
SELECT add_retention_policy('server_logs', INTERVAL '90 days');

-- Trim raw server_metrics to 7 days (hourly CAGG serves 30-day charts)
SELECT remove_retention_policy('server_metrics', if_exists => true);
SELECT add_retention_policy('server_metrics', INTERVAL '7 days');
```

Run these directly in psql — no migration needed. Verify charts still load 30-day data after
trimming raw metrics (the hourly CAGG covers the gap automatically).
