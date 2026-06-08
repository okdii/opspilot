# PostgreSQL Monitoring Support — Design Spec

**Date:** 2026-06-08
**Feature:** Add PostgreSQL as a second supported database type alongside MariaDB/MySQL
**Approach:** Option A — unified flow, `db_type` field gates metric set per server

---

## Overview

Extend the existing Database Monitoring feature (`/databases`) to support PostgreSQL in addition to MariaDB/MySQL. A server can monitor one DB type at a time (MySQL or PostgreSQL), chosen when credentials are first configured. All credential CRUD, the server tab strip, and the Pinia store stay structurally identical — only the metric map, Telegraf input block, setup SQL, and dashboard panels differ per type.

---

## Data Model

### `DBCredential` (backend model)

Add one column:

```python
db_type: str  # 'mysql' | 'postgres', default 'mysql', NOT NULL
```

Migration: `ALTER TABLE db_credential ADD COLUMN db_type VARCHAR(16) NOT NULL DEFAULT 'mysql'`.
All existing rows get `db_type = 'mysql'` — fully backward compatible.

---

## Backend (`backend/app/routers/databases.py`)

### Schema changes

`DBCredentialIn` and `DBCredentialPatch` gain:
```python
db_type: Literal['mysql', 'postgres'] = 'mysql'
```

`list_db_credentials` response includes `db_type` per server.

### PostgreSQL metric map

```python
_PG_METRIC_MAP: dict[str, tuple[str, bool]] = {
    'connections_active':   ('postgresql.numbackends',          False),
    'transactions_per_sec': ('postgresql.xact_commit',          True),   # rate, rollbacks added separately
    'cache_hit_rate':       ('postgresql.blks_hit_rate',        False),  # pre-computed by Telegraf
    'deadlocks':            ('postgresql.deadlocks',            True),
    'tuple_ops_per_sec':    ('postgresql.tup_inserted',         True),   # backend sums inserted+updated+deleted
    'temp_files_per_min':   ('postgresql.temp_files',           True),
    'checkpoints_per_min':  ('postgresql.checkpoints_timed',    True),
    'replication_lag_sec':  ('postgresql.replication_delay',    False),  # replica only
}
```

`tuple_ops_per_sec` requires summing three Telegraf counters server-side before returning the rate.

### Metric endpoint changes

`get_db_metrics_latest` and `get_db_metrics`: look up the credential's `db_type`, then select `_METRIC_MAP` (MySQL) or `_PG_METRIC_MAP` (PostgreSQL). No other logic changes.

`get_db_metrics_latest` PostgreSQL response shape:
```json
{
  "connections_active": 12,
  "transactions_per_sec": 340.5,
  "cache_hit_rate": 99.2,
  "deadlocks": 0,
  "tuple_ops_per_sec": 850.0,
  "temp_files_per_min": 0,
  "checkpoints_per_min": 0.4,
  "replication_lag_sec": null,
  "replication_running": null,
  "last_collected_at": "2026-06-08T..."
}
```

### Deadlock alert evaluator

The existing `db_deadlock_evaluator` works against `mysql.innodb_deadlocks`. Add an equivalent for PostgreSQL using `postgresql.deadlocks` counter from `_PG_METRIC_MAP`. Same delta-tracking logic, same `db_deadlock` alert type.

---

## Telegraf / Agent Template

The onboarding service renders `telegraf.conf` from a Jinja2 template. The template gains a conditional block:

```jinja
{% if db_type == 'mysql' %}
[[inputs.mysql]]
  servers = ["{{ mysql_dsn }}"]
  ...existing block...
{% elif db_type == 'postgres' %}
[[inputs.postgresql]]
  address = "postgres://{{ pg_user }}:{{ pg_password }}@{{ pg_host }}:{{ pg_port }}/postgres?sslmode=disable"
  ignored_databases = ["template0", "template1"]
{% endif %}
```

The `inputs.postgresql` plugin collects from `pg_stat_database`, `pg_stat_bgwriter`, and `pg_stat_replication` automatically.

---

## Frontend

### `databases.ts` store

```typescript
export type DbType = 'mysql' | 'postgres'

export interface DbCredentialStatus {
  // ...existing fields...
  db_type: DbType  // new
}

export interface DbCredentialPayload {
  // ...existing fields...
  db_type: DbType  // new
}

export type DbPgMetricName =
  | 'connections_active'
  | 'transactions_per_sec'
  | 'cache_hit_rate'
  | 'deadlocks'
  | 'tuple_ops_per_sec'
  | 'temp_files_per_min'
  | 'checkpoints_per_min'
  | 'replication_lag_sec'
```

`DbMetricsLatest` gains PostgreSQL-specific fields (all nullable):
```typescript
transactions_per_sec: number | null
cache_hit_rate: number | null
tuple_ops_per_sec: number | null
temp_files_per_min: number | null
checkpoints_per_min: number | null
```

### `DbCredentialModal.vue`

- DB type selector at the top: two pill buttons `MySQL / MariaDB` | `PostgreSQL`
- Selecting PostgreSQL: port default switches to `5432`, username hint to `opspilot`
- Selecting MySQL: port reverts to `3306`, username hint to `opspilot_monitor`
- On edit (`existing` prop present): selector is disabled (can't change DB type after setup)

### `DbNoCredentials.vue`

Receives `dbType` prop. Shows the appropriate setup SQL:

**MySQL/MariaDB:**
```sql
CREATE USER 'opspilot_monitor'@'%' IDENTIFIED BY '<password>';
GRANT PROCESS, REPLICATION CLIENT, SELECT ON *.* TO 'opspilot_monitor'@'%';
FLUSH PRIVILEGES;
```

**PostgreSQL:**
```sql
CREATE USER opspilot WITH PASSWORD '<password>';
GRANT pg_monitor TO opspilot;
```

### `DatabasesView.vue`

- Subtitle: `"MariaDB & PostgreSQL health metrics per server"`
- Passes `selected.db_type` down to `DbNoCredentials` and `DbHealthDashboard`

### `DbHealthDashboard.vue`

Receives `dbType: DbType` prop.

**`dbType === 'mysql'`** — existing panels, no changes.

**`dbType === 'postgres'`** — new panel set:

| Panel | Type | Explanation |
|---|---|---|
| Connections | Stat card + gauge | "Nearing max_connections means new app connections will be rejected." |
| Transactions/sec | Area chart | "Sudden drops reveal connection failures or application errors." |
| Cache Hit Rate | Stat card + gauge | "Below 99% means frequent disk reads — tune shared_buffers or add RAM." |
| Deadlocks | Bar chart | "Any deadlock means two transactions blocked each other — one silently failed." |
| Tuple Ops/sec | Area chart | "Combined inserts + updates + deletes — reflects write load on the database." |
| Temp Files/min | Bar chart | "Spilling to disk means queries need more work_mem or indexes are missing." |
| Checkpoints/min | Line chart | "Frequent checkpoints mean heavy write load — consider tuning checkpoint_timeout." |
| Replication Lag | Line chart (replica only) | "Over a few seconds means reads from the replica return stale data." |

Header label: `"MariaDB"` → `"PostgreSQL"` when `dbType === 'postgres'`.

---

## What Is Not Changing

- Credential CRUD endpoints (`POST`, `PATCH`, `DELETE`) — identical for both DB types
- Server tab strip and badge logic in `DatabasesView`
- Alert types (`db_connections`, `db_replication_lag`, `db_replication_stopped`) — generic metric evaluator handles both via AlertRules
- Historical data retention on credential removal

---

## Scope Boundaries

- No per-database breakdown (all metrics are cluster-level)
- No `pg_stat_statements` integration (slow query analysis out of scope)
- No automatic `db_type` detection — user selects explicitly at setup
- No migration path from MySQL to PostgreSQL on the same server (delete + re-add)
