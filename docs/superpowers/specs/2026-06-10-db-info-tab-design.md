# Database Info Tab — Design Spec
**Date:** 2026-06-10
**Status:** Approved

---

## Overview

Add a second tab ("Info") to the existing database monitoring page alongside the current "Metrics" tab. The Info tab shows a comprehensive snapshot of the monitored database instance, pulling data from three sources: stored credentials, existing Telegraf metrics, and a new on-demand live query endpoint.

---

## Layout

- New **"Info" tab** alongside the existing "Metrics" tab in `DatabasesView.vue` / `DbHealthDashboard.vue`
- Tab switch triggers a fetch; a **↻ Refresh** button re-fetches on demand
- Info body: **2-column grid of info blocks**, each block covering one category
- Footer bar: "Last fetched: X ago · Live query to database" + Refresh button
- Existing header (server name, host:port, last checked, connection status, action buttons) is unchanged

---

## Info Sections

### 1. Database Information
| Field | Source |
|---|---|
| Type | Credential (`db_type`) |
| Version | Live query |
| Hostname / IP | Credential (`host`) |
| Port | Credential (`port`) |
| Uptime | Live query |
| Data Directory | Live query |
| Character Set | Live query |
| Collation | Live query |
| Time Zone | Live query |
| Database Size | Live query |

### 2. Server Information
| Field | Source |
|---|---|
| Server Name | `Server.name` column |
| Operating System | `Server.os_distro` column |
| CPU Cores | Server metrics (`system.n_cpus`) |
| Total RAM | Server metrics (`mem.total`) |
| Storage Capacity | Server metrics (`disk.total`) |
| Storage Type | Not available — show "—" |

### 3. Connection Information
| Field | Source |
|---|---|
| Current Connections | Telegraf metric (`connections_active`) |
| Max Connections | Telegraf metric (`connections_max`) |
| Connection Usage % | Derived: current / max × 100, with mini progress bar |
| SSL / TLS | Live query |

### 4. Storage Information
| Field | Source |
|---|---|
| Total Databases | Live query |
| Total Tables | Live query |
| Largest Database | Live query |
| Largest Table | Live query |
| Used Storage | Live query (sum of data+index size across all user databases) |
| Free Storage | Server metrics (`disk.free` for the data-dir mount) |

### 5. Replication Information
Shown for all instances (primary shows role = "Primary", replica shows full detail).
| Field | Source |
|---|---|
| Role | Credential (`is_replica` → "Replica" or "Primary") |
| Replication Status | Telegraf metric (`replication_running`) |
| Replication Lag | Telegraf metric (`replication_lag_sec`) |

### 6. Backup Information
Sourced from `MonitoredJob` records linked to this server (`server_id`). Uses the job's denormalised last-run fields. If no `MonitoredJob` row exists for this server, show "No backup job configured".
| Field | Source |
|---|---|
| Last Backup | `MonitoredJob.last_ping_at` (latest run time) |
| Backup Status | `MonitoredJob.status` ("healthy" → Success, "failed"/"late" → Failed/Late) |
| Backup Size | `MonitoredJob.last_size_bytes` (formatted as human-readable) |

---

## Backend — New Endpoint

```
GET /api/servers/{server_id}/db-info?credential_id={id}
```

**Auth:** `CurrentUser` (same as db-metrics endpoints)

**Behaviour:**
1. Load `DBCredential` by `credential_id` + `server_id`
2. Decrypt password via `app.core.crypto.decrypt`
3. Connect to the monitored database using:
   - MySQL/MariaDB: `aiomysql` (new dependency)
   - PostgreSQL: `asyncpg` (already installed)
4. Run queries (see below), collect results
5. Close connection
6. Merge with: Server row (name, OS), Telegraf latest metrics (connections, replication), cron job records (backup)
7. Return single JSON object

**If the DB is unreachable:** return `200` with `"reachable": false` and populate only the static fields (credential + server + Telegraf). Never return 5xx for a down database.

**Timeout:** 5 seconds on the live DB connection attempt.

### MySQL / MariaDB queries
```sql
SHOW GLOBAL VARIABLES WHERE Variable_name IN (
  'version', 'datadir', 'character_set_server',
  'collation_server', 'time_zone'
);
SHOW GLOBAL STATUS WHERE Variable_name = 'Uptime';
SHOW GLOBAL STATUS WHERE Variable_name = 'Ssl_cipher';

SELECT
  SUM(data_length + index_length) AS total_size_bytes
FROM information_schema.tables;

SELECT COUNT(DISTINCT table_schema) AS total_databases
FROM information_schema.tables
WHERE table_schema NOT IN ('information_schema','performance_schema','mysql','sys');

SELECT COUNT(*) AS total_tables
FROM information_schema.tables
WHERE table_schema NOT IN ('information_schema','performance_schema','mysql','sys');

SELECT table_schema AS db_name,
       SUM(data_length + index_length) AS size_bytes
FROM information_schema.tables
GROUP BY table_schema
ORDER BY size_bytes DESC LIMIT 1;

SELECT table_schema, table_name,
       (data_length + index_length) AS size_bytes
FROM information_schema.tables
ORDER BY size_bytes DESC LIMIT 1;
```

### PostgreSQL queries
```sql
SELECT version();
SELECT pg_postmaster_start_time();
SHOW data_directory;
SHOW server_encoding;
SHOW lc_collate;
SHOW TimeZone;
SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid();

SELECT SUM(pg_database_size(datname)) AS total_size_bytes
FROM pg_database WHERE datistemplate = false;

SELECT COUNT(*) FROM pg_database WHERE datistemplate = false;

SELECT SUM(n_tables) AS total_tables
FROM (
  SELECT COUNT(*) AS n_tables FROM information_schema.tables
  WHERE table_schema NOT IN ('pg_catalog','information_schema')
) t;

SELECT datname, pg_database_size(datname) AS size_bytes
FROM pg_database WHERE datistemplate = false
ORDER BY size_bytes DESC LIMIT 1;

SELECT schemaname || '.' || relname AS table_name,
       pg_total_relation_size(relid) AS size_bytes
FROM pg_stat_user_tables
ORDER BY size_bytes DESC LIMIT 1;
```

### Response schema
```json
{
  "reachable": true,
  "db": {
    "type": "mysql",
    "version": "10.6.12-MariaDB",
    "host": "127.0.0.1",
    "port": 3306,
    "uptime_seconds": 1234567,
    "data_directory": "/var/lib/mysql",
    "character_set": "utf8mb4",
    "collation": "utf8mb4_general_ci",
    "time_zone": "SYSTEM",
    "size_bytes": 2576980377
  },
  "server": {
    "name": "prod-db-01",
    "os": "Ubuntu 22.04",
    "cpu_cores": 4,
    "ram_bytes": 8589934592,
    "disk_total_bytes": 107374182400
  },
  "connections": {
    "current": 8,
    "max": 151,
    "ssl_enabled": true,
    "ssl_version": "TLSv1.3"
  },
  "storage": {
    "total_databases": 4,
    "total_tables": 87,
    "largest_db": { "name": "opspilot", "size_bytes": 1932735283 },
    "largest_table": { "name": "server_metrics", "size_bytes": 1153433600 },
    "used_bytes": 2576980377,
    "free_bytes": 104797201923
  },
  "replication": {
    "role": "primary",
    "running": true,
    "lag_sec": 0
  },
  "backup": {
    "last_run_at": "2026-06-10T02:00:00Z",
    "status": "success",
    "size_bytes": 1288490188
  }
}
```

---

## Frontend — New Component

**File:** `frontend/src/components/databases/DbInfoPanel.vue`

**Props:**
```ts
{
  serverId: string
  credentialId: string
  status: DbInstanceStatus   // for replication lag from existing Telegraf data
}
```

**State:**
- `loading: ref<boolean>` — skeleton shown while fetching
- `info: ref<DbInfo | null>` — fetched data
- `fetchedAt: ref<Date | null>` — timestamp for "Last fetched" footer
- `error: ref<string | null>` — shown if fetch fails entirely

**Behaviour:**
- Fetches on mount (`onMounted`)
- Refresh button calls the same fetch function
- Formats `uptime_seconds` as "Xd Xh Xm"
- Formats `*_bytes` fields as human-readable (GB / MB)
- Connection usage % shows a mini inline progress bar (green <60%, yellow 60–80%, red >80%)
- SSL: shows green pill "✓ Enabled (TLS vX.X)" or muted "—" if not enabled
- Replication: only shows the section if `status.is_replica` or `info.replication.running != null`
- Backup: if `info.backup == null`, shows "No backup job configured"
- Null fields from live query: display as "—"

**Integration in `DatabasesView.vue`:**
- Add `activeTab: ref<'metrics' | 'info'>('metrics')` state
- Render tab bar with "Metrics" and "Info" buttons
- Conditionally render `DbHealthDashboard` (metrics) or `DbInfoPanel` (info) based on `activeTab`
- Pass `credentialId` and `status` to `DbInfoPanel`

---

## New Dependency

Add to `backend/requirements.txt`:
```
aiomysql==0.2.0
```

---

## Error States

| Situation | Behaviour |
|---|---|
| DB unreachable (timeout/refused) | Show static fields, live-query rows show "—", yellow banner: "Could not connect to database — showing cached data only" |
| Partial query failure | Affected field shows "—", no error shown |
| Server metrics missing | OS/CPU/RAM show "—" |
| No backup job | Backup section shows "No backup job configured" |

---

## Out of Scope

- Storage type (SSD/HDD) — not exposed by OS or DB
- Periodic background polling of info (Telegraf not involved)
- Writing/modifying any DB settings from this panel
