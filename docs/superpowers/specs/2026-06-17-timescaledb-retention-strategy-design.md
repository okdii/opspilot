# TimescaleDB Data Retention & Storage Strategy

**Date:** 2026-06-17
**Status:** Approved
**Author:** Brainstorming session

---

## Problem

OpsPilot's TimescaleDB is growing at ~12 GB/week with only 2 monitored servers. The root cause
is `server_logs` having no compression policy and a GIN full-text index that blocks columnar
compression. At this growth rate, the 93 GB of free disk is exhausted in ~8 weeks. Scaling to
10 servers without intervention fills the disk in ~1–2 weeks.

---

## Goals

- Prevent disk exhaustion while preserving full operational visibility
- Keep 30-day raw log history fully searchable
- Keep 30-day metric trend data available for charts
- Support growth from 2 → 10+ servers without runaway storage costs
- Prefer simple, incremental changes — no big-bang refactors

---

## Current State

| Table | Hypertable | Chunk interval | Compression | Retention |
|---|---|---|---|---|
| `server_metrics` | ✅ | 1 day | ✅ after 2 days | 30 days |
| `server_logs` | ✅ | 1 day | ❌ none | 30 days |
| `service_checks` | ✅ | 1 day | ❌ none | 90 days |
| `server_metrics_hourly` CAGG | — | — | — | ❌ none (grows forever) |
| `server_metrics_daily` CAGG | — | — | — | ❌ none (grows forever) |

**Identified problems:**
1. `server_logs` has no compression — accounts for ~94% of weekly growth
2. `server_logs` has a GIN index on `message` that blocks TimescaleDB columnar compression
3. The GIN index is unused — all queries use `ILIKE`, not `@@` FTS operators
4. `service_checks` has no compression
5. CAGG retention policies are missing — both aggregate views grow indefinitely

---

## Capacity Model

### Before fix (current)

| Scale | Weekly growth | Runway on 93 GB free |
|---|---|---|
| 2 servers | 12 GB | ~8 weeks |
| 10 servers | ~60 GB | ~1–2 weeks |

### After fix (with compression)

Compression ratio assumption: 15× on log text (typical for structured syslog/access log lines).

| Scale | Weekly growth | Monthly growth | Runway on 93 GB free |
|---|---|---|---|
| 2 servers | ~0.8 GB | ~3 GB | ~30 months ✅ |
| 5 servers | ~2 GB | ~8 GB | ~11 months ✅ |
| 10 servers | ~4 GB | ~16 GB | ~5 months ⚠️ |
| 20 servers | ~8 GB | ~32 GB | ~3 months ❌ |

Growth is linear per server. All figures assume the current log volume profile (11 Fluent Bit
sources including mariadb general log, Telegraf at 10s interval).

---

## Target Data Lifecycle

### server_logs

```
Day 0–2    raw, uncompressed        fast recent queries
Day 2–30   compressed (15× smaller) still fully queryable via ILIKE
Day 30+    dropped by retention     gone forever
```

The 30-day retention window is preserved — users retain full search capability. When scaling to
5–7 servers, extend to 90 days (compression keeps it affordable).

### server_metrics

```
Day 0–2    raw, uncompressed        high-resolution debugging
Day 2–7    compressed               fast recent trend queries
Day 7+     dropped from raw         raw data gone
              ↕
Hourly CAGG  avg/min/max per hour   serves 30-day charts (keep 90 days)
Daily CAGG   avg/min/max per day    long-term capacity planning (keep forever)
```

Charts pivot from raw → hourly CAGG automatically. No UI changes required since
`server_metrics_hourly` already exists and covers the 30-day view.

### service_checks

```
Day 0–2    raw, uncompressed
Day 2–90   compressed
Day 90+    dropped by retention
```

---

## Three-Phase Rollout

### Phase 1 — Immediate (today, 2 servers)

**Goal:** Eliminate the disk crisis. No data deleted, no retention changes.

Actions:
1. Drop the GIN index on `server_logs.message` (unused, blocks compression)
2. Enable columnar compression on `server_logs` (compress after 2 days)
3. Enable columnar compression on `service_checks` (compress after 2 days)
4. Add retention policies to `server_metrics_hourly` CAGG (90 days)
5. Add retention policies to `server_metrics_daily` CAGG (none — keep forever)
6. Add disk usage alert rule at 70% disk used (~100 GB)

**Expected outcome:** Weekly growth drops from 12 GB → ~0.8 GB. Runway extends to ~30 months.

### Phase 2 — When scaling to 5–7 servers

**Goal:** Extend log history, optimise metrics raw window.

Actions:
1. Extend `server_logs` retention from 30 → 90 days
2. Trim `server_metrics` raw retention from 30 → 7 days (hourly CAGG serves 30-day charts)
3. Verify chart queries use `server_metrics_hourly` for date ranges beyond 7 days

**Expected outcome:** ~11 months runway at 5 servers with 90-day log history.

### Phase 3 — When disk alert fires (70%)

**Goal:** Recover headroom without emergency actions.

Actions (choose one or both):
- Expand disk by 200 GB (cheapest option, no data impact)
- Or trim `server_logs` retention to 180 days if log growth is the driver

---

## SQL Policy Design

### Phase 1 SQL

```sql
-- 1. Drop the unused GIN index that blocks compression
DROP INDEX IF EXISTS ix_server_logs_fts;

-- 2. Enable compression on server_logs
ALTER TABLE server_logs SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'server_id, source',
    timescaledb.compress_orderby   = 'time DESC'
);
SELECT add_compression_policy('server_logs', INTERVAL '2 days');

-- 3. Enable compression on service_checks
ALTER TABLE service_checks SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'service_id',
    timescaledb.compress_orderby   = 'time DESC'
);
SELECT add_compression_policy('service_checks', INTERVAL '2 days');

-- 4. Add retention to hourly CAGG (90 days)
SELECT add_retention_policy('server_metrics_hourly', INTERVAL '90 days');

-- 5. Daily CAGG: no retention (keep forever)
-- No action needed — omitting the policy means it never drops.

-- 6. Manually compress existing uncompressed server_logs chunks (backfill)
SELECT compress_chunk(chunk_schema || '.' || chunk_name)
FROM timescaledb_information.chunks
WHERE hypertable_name = 'server_logs'
  AND is_compressed = false
  AND range_end < NOW() - INTERVAL '2 days';
```

### Phase 2 SQL (run when at 5–7 servers)

```sql
-- Extend server_logs retention to 90 days
SELECT remove_retention_policy('server_logs', if_exists => true);
SELECT add_retention_policy('server_logs', INTERVAL '90 days');

-- Trim server_metrics raw to 7 days
SELECT remove_retention_policy('server_metrics', if_exists => true);
SELECT add_retention_policy('server_metrics', INTERVAL '7 days');
```

---

## Compression Configuration Notes

### server_logs compress_segmentby choice

`server_id, source` is chosen because:
- Queries always filter by `server_id` (enforced by the router)
- Queries frequently filter by `source` (auth, nginx, syslog, etc.)
- This lets TimescaleDB skip entire compressed segments without decompressing

### GIN index removal

The `ix_server_logs_fts` index was created in migration `0001` for potential full-text search.
No code in the codebase uses `@@` or `to_tsvector` queries against `server_logs` — all log
search uses `ILIKE`. The index is safe to drop and actively harmful for compression.

---

## Operational Guardrails

### Disk alert threshold

Add an alert rule to OpsPilot at **70% disk used (~100 GB on this host)**. At the current Phase 1
growth rate of ~0.8 GB/week, 70% gives approximately 8+ weeks of warning before critical.

### Monitoring queries (run periodically)

```sql
-- Check hypertable sizes
SELECT hypertable_name,
       pg_size_pretty(total_bytes) AS total,
       pg_size_pretty(compressed_total_bytes) AS compressed,
       num_chunks
FROM timescaledb_information.hypertable_detailed_size(NULL)
ORDER BY total_bytes DESC;

-- Check compression savings on server_logs
SELECT
  pg_size_pretty(SUM(before_compression_total_bytes)) AS before,
  pg_size_pretty(SUM(after_compression_total_bytes))  AS after,
  ROUND(100 - 100.0 * SUM(after_compression_total_bytes)
              / NULLIF(SUM(before_compression_total_bytes), 0), 1) AS pct_saved
FROM timescaledb_information.chunk_compression_stats
WHERE hypertable_name = 'server_logs';

-- Check retention policy jobs
SELECT application_name, schedule_interval, next_start, last_run_status
FROM timescaledb_information.jobs
WHERE application_name ILIKE '%retention%' OR application_name ILIKE '%compress%';
```

### Runbook: growth spike

1. Run the hypertable size query above to find the fast-growing table
2. Check if compression jobs are running: `SELECT * FROM timescaledb_information.job_stats`
3. If a compression job failed, re-run manually: `SELECT run_job(<job_id>)`
4. If `server_logs` is the driver, check if a new high-volume log source was added
5. If disk > 80%, immediately set `server_logs` retention to 60 days to recover headroom

---

## Settings UI Integration

The existing `app_settings` table exposes `metrics_retention_days`, `logs_retention_days`, and
`service_checks_retention_days` to the UI via the retention service. These remain the user-facing
controls — no new columns needed. Phase 2 changes are applied via the existing
`apply_retention()` service function.

The new compression policies are set-and-forget — they require no UI surface.

---

## Assumptions & Constraints

- Compression ratio of 15× is a conservative estimate for mixed log text; real-world may be
  10–20× depending on log verbosity
- Growth scales linearly per server — actual growth depends on server workload (mariadb general
  log volume is the biggest variable)
- `server_metrics_hourly` CAGG is assumed to be the source for all chart queries beyond 24h;
  this must be verified before applying Phase 2 raw retention trim
- No compliance or audit retention requirements beyond operational visibility
