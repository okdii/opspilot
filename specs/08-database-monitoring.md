# Spec 08 — Database Deep Monitoring

**Version:** 1.0  
**Date:** 2026-06-01  
**Status:** Approved

---

## 1. Overview

Database deep monitoring collects real MariaDB health metrics via Telegraf's `inputs.mysql` plugin. The admin provides a read-only MariaDB monitoring user's credentials per server — OpsPilot re-deploys the Telegraf config over SSH automatically, injecting `inputs.mysql` and restarting the agent. No manual SSH step is needed after credential entry.

This feature is opt-in per server. Servers without credentials show a "Set up DB monitoring" prompt. Servers with credentials show a full health dashboard with connection metrics, query throughput, InnoDB stats, deadlock tracking, and (if a replica) replication lag.

PRD references: §5.8, §5.16.9, §9 (DBCredential model)

---

## 2. Routes

| Route | Access | Description |
|---|---|---|
| `/databases` | All roles | DB monitoring overview — all servers in active org |

Single-page design. No separate detail URL — server selection is handled within the page via a server tab strip. Credential add/edit opens a modal.

---

## 3. Page Layout

### 3.1 Overall Structure

```
┌───────────────────────────────────────────────────────────────────┐
│ Database Monitoring                                               │
│                                                                   │
│ [ web-01 ✓ ]  [ db-01 ✓ ]  [ app-02 — ]  [ worker-01 — ]       │
│                                                                   │
│ ─────────────────────────────────────────────────────────────── │
│                                                                   │
│  [Content area — changes per selected server tab]                 │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

The server tab strip lists all servers in the active org. Each tab shows the server name and a badge:
- `✓` (green) — DB credentials configured and last check succeeded
- `⚠` (amber) — credentials configured but last check failed (connection error)
- `—` (grey) — no credentials configured yet

The first tab with credentials is selected by default on page load. If no servers have credentials, the first server tab is selected and the no-credentials state is shown.

### 3.2 No-Credentials State

When the selected server has no `DBCredential` record:

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│   MariaDB monitoring is not configured for web-01             │
│                                                                │
│   To enable deep database metrics, create a read-only         │
│   MariaDB monitoring user on this server, then enter          │
│   the credentials below.                                      │
│                                                                │
│   Step 1 — Run on web-01:                                     │
│   ┌──────────────────────────────────────────────────────┐    │
│   │ CREATE USER 'opspilot_monitor'@'%'                   │    │
│   │   IDENTIFIED BY '<password>';                        │    │
│   │ GRANT PROCESS, REPLICATION CLIENT,                   │    │
│   │   SELECT ON *.* TO 'opspilot_monitor'@'%';           │    │
│   │ FLUSH PRIVILEGES;                                    │    │
│   └──────────────────────────────────────────────────────┘    │
│                            [Copy SQL]                          │
│                                                                │
│   Step 2 — Enter credentials in OpsPilot:                     │
│                                                                │
│           [Set Up DB Monitoring for web-01]                   │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

The SQL block is a styled code block with a `[Copy SQL]` button. The `[Set Up DB Monitoring for web-01]` button opens the credential modal.

Visible to all roles, but the button and credential form are Admin only. Viewers and Operators see the same text but without the button.

---

## 4. Credential Modal

### 4.1 Trigger

- No-credentials state: `[Set Up DB Monitoring for server-name]` button
- Configured state: `[Edit Credentials]` link in the health dashboard header

### 4.2 Form Fields

| Field | Type | Default | Validation |
|---|---|---|---|
| Host | Text | `127.0.0.1` | Required; hostname or IP; no protocol prefix |
| Port | Number | `3306` | Required; 1–65535 |
| Username | Text | `opspilot_monitor` | Required; max 80 chars |
| Password | Password | — | Required; max 255 chars |
| Is Replica | Toggle | Off | Enables replication monitoring section |

When **Is Replica** is toggled on, an info block appears:

```
ℹ Replication alerts enabled
  Alerts will fire if:
  • Replication thread stops running
  • Replication lag exceeds 30 seconds
```

### 4.3 Edit Mode

In edit mode the modal title changes to "Edit DB Credentials — web-01". Password field shows a placeholder `••••••••` — leaving it empty preserves the existing encrypted password. A note reads: "Leave password blank to keep existing credentials."

### 4.4 Submit Behaviour

**POST `/api/servers/:id/db-credentials`** (create) or **PATCH `/api/servers/:id/db-credentials`** (update).

On success:
1. Modal closes.
2. Toast: "Credentials saved. Re-deploying Telegraf config..."
3. The server tab badge changes to amber spinner state ("Deploying...").
4. Backend triggers SSH re-deploy (same job as "Re-deploy agents" — steps 6–10 only).
5. Re-deploy progress is visible via the Onboarding slide-over if the admin navigates there, but the databases page itself just shows the spinner and then resolves.
6. After re-deploy completes (WS event `onboarding_complete` or poll), badge updates to `✓` green and the DB health dashboard loads.
7. If re-deploy fails: badge shows `⚠` amber; toast: "Telegraf re-deploy failed — check onboarding log."

### 4.5 Delete Credentials

Available via `[⋮] → Remove DB Monitoring` in the health dashboard header.

Confirmation modal:
```
Remove DB monitoring for web-01?

This will:
  • Remove stored credentials
  • Remove inputs.mysql from Telegraf config (re-deploy required)
  • Stop collecting DB metrics (existing history is retained)

[Cancel]  [Remove]
```

On confirm: DELETE `/api/servers/:id/db-credentials` → triggers SSH re-deploy to remove `inputs.mysql` from Telegraf config → server tab badge resets to `—`.

---

## 5. DB Health Dashboard

Shown when a server has credentials configured and data is flowing.

### 5.1 Dashboard Header

```
┌─────────────────────────────────────────────────────────────────┐
│  web-01 — MariaDB 10.6.12                                       │
│  127.0.0.1:3306  ·  Last checked: 10s ago  ·  ✓ Connected      │
│                                            [Edit Credentials] [⋮]│
└─────────────────────────────────────────────────────────────────┘
```

MariaDB version is read from the `version` field returned by `inputs.mysql`. "Connected" / "Connection Error" reflects whether the last Telegraf collection cycle succeeded.

### 5.2 Summary Stat Cards

Four stat cards in a row:

| Card | Value | Sub-label |
|---|---|---|
| Connections | e.g., `24 / 151` | `16% of max` |
| Queries/sec | e.g., `342 qps` | `5-min avg` |
| Buffer Pool Hit | e.g., `98.4%` | `InnoDB cache` |
| Slow Queries | e.g., `2 /min` | `last 5 min` |

Connections card background turns amber when > 60% of max, red when > 80%.
Buffer Pool Hit card background turns red when < 90%.

### 5.3 Time Range Tabs

All charts on this page share the same time range selector:

**1h / 6h / 24h / 7d / 30d**

Time range → data source:
- 1h / 6h: raw `server_metrics` (10s interval)
- 24h: `server_metrics_hourly` aggregates
- 7d / 30d: `server_metrics_daily` aggregates

---

## 6. Charts

### 6.1 Active Connections (Line Chart)

- Y-axis: connection count
- Two lines: `connections_active` (solid blue) and `connections_max` (dashed red — ceiling line)
- When `connections_active / connections_max` > 80%, the area under the `connections_active` line fills red
- X-axis: time ticks per range (same scale as dashboard charts)
- Tooltip shows: time, active connections, max connections, utilisation %

### 6.2 Connections Gauge (Radial Gauge)

- Current connections as % of `connections_max`
- Displayed beside the connections line chart (two columns)
- Colour thresholds: green → amber (60%) → red (80%)
- Centre label: `24 / 151`

### 6.3 Queries Per Second (Area Line Chart)

- Y-axis: queries/sec
- Smooth area fill below the line
- Shows `queries_per_sec` metric over the selected time range
- No threshold overlay — trend reference only

### 6.4 Slow Queries (Bar Chart)

- Y-axis: slow queries per minute
- Each bar = one minute bucket (or wider for longer ranges)
- Threshold overlay: dashed red horizontal line at the configured slow query alert threshold
- Bars above threshold coloured red; bars below green
- Tooltip: time, slow query count

### 6.5 InnoDB Buffer Pool Hit Rate (Radial Gauge)

- Current 5-min rolling average hit rate %
- Colour thresholds:
  - ≥ 95%: green
  - 90–94%: amber
  - < 90%: red (also fires alert)
- Centre label: `98.4%`
- Sub-label: "Target ≥ 95%"

### 6.6 Deadlocks (Bar Chart)

- Y-axis: new deadlocks per hour (derived from cumulative `innodb_deadlocks` counter — backend computes delta)
- Each bar = one hour bucket
- Any bar > 0 is coloured red; bars at 0 are dark grey
- No threshold line — any occurrence is significant
- Tooltip: time bucket, deadlock count

### 6.7 Replication Section

Shown only when `is_replica = true` on the `DBCredential`. Collapsible panel labelled "Replication Status".

#### Replication Status Banner

```
┌──────────────────────────────────────────────────────────────┐
│  ✓ Replication Running    Lag: 0.4s behind master            │
└──────────────────────────────────────────────────────────────┘
```

- If `replication_running = false`: banner turns red — "✕ Replication Stopped — Alert fired"
- If lag > 30s: banner turns amber — "⚠ Replication Lag: 42s behind master"

#### Replication Lag Chart (Line Chart)

- Y-axis: seconds behind master
- Dashed red threshold line at 30s
- Area above 30s fills red
- Only rendered when `is_replica = true`

### 6.8 Table Locks & Aborted Connections (Combined Panel)

Two smaller line charts side-by-side:

**Table Lock Waits (per min)**
- Rate derived from cumulative `table_locks_waited` counter
- Threshold overlay at configured rate (default: 10/min)

**Aborted Connections (per min)**
- Rate derived from cumulative `aborted_connections` counter
- Threshold overlay at configured rate (default: 5/min)

These are secondary metrics — rendered below the primary charts in a collapsed "Advanced Metrics" panel. Expanded on click.

---

## 7. Chart Layout (Full Page)

```
┌─────────────────────────────────────────────────────────────────┐
│  [Summary Cards: Connections | QPS | Buffer Pool Hit | Slow Q]  │
├─────────────────────────────────────────────────────────────────┤
│  Time Range: [1h] [6h] [24h] [7d] [30d]                        │
├──────────────────────────┬──────────────────────────────────────┤
│  Connections Gauge       │  Active Connections (line chart)     │
│       (radial)           │                                      │
├──────────────────────────┴──────────────────────────────────────┤
│  Queries Per Second (area chart)                                │
├─────────────────────────────────────────────────────────────────┤
│  Slow Queries (bar chart)         │  Buffer Pool Hit (radial)  │
├─────────────────────────────────────────────────────────────────┤
│  Deadlocks (bar chart)                                          │
├─────────────────────────────────────────────────────────────────┤
│  ▼ Replication Status (visible if is_replica = true)           │
│    Replication banner                                           │
│    Replication Lag (line chart)                                 │
├─────────────────────────────────────────────────────────────────┤
│  ▼ Advanced Metrics (collapsed)                                 │
│    Table Lock Waits  │  Aborted Connections                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. WebSocket Integration

DB metrics flow through the same `server_metrics:{server_id}` channel as CPU/RAM/disk metrics. The frontend subscribes on page load for the selected server tab using `{ "action": "subscribe", "server_id": "..." }`.

Relevant metric names for live updates:
- `connections_active`, `connections_max`
- `queries_per_sec`
- `slow_queries_per_min`
- `innodb_buffer_pool_hit_rate`
- `innodb_deadlocks`
- `replication_lag_sec`, `replication_running`
- `table_locks_waited`, `aborted_connections`

The frontend `useMetricsStore` already handles these via the existing WS batch push payload — no new WS channel or subscription type needed.

On server tab change:
- Send `unsubscribe` for previous server
- Send `subscribe` for newly selected server
- Load chart data for new server via REST

---

## 9. Backend — Metric Evaluation

DB metrics are collected by Telegraf (not the OpsPilot backend directly). Telegraf's `inputs.mysql` plugin reads from MariaDB and writes rows to the `server_metrics` hypertable every 10 seconds.

The OpsPilot alert evaluator (APScheduler job, runs every 60 seconds) reads the latest DB metric rows and evaluates alert conditions:

```
1. connections_active / connections_max > 0.80 (rolling 5-min avg)
   → fire 'db_connections' alert (critical)

2. innodb_buffer_pool_hit_rate < 90 (rolling 5-min avg)
   → fire 'db_connections' alert ... actually type = 'db_connections'
   → fire alert type = 'db_connections' for connections, no — let's be precise:
   Connections: alert type 'db_connections'
   Buffer pool: evaluated but no separate alert type in v1 — included in 'db_connections' alert message

3. innodb_deadlocks (current) > DBCredential.last_deadlock_count
   → fire 'db_deadlock' alert (critical)
   → UPDATE DBCredential SET last_deadlock_count = current value

4. If is_replica = true:
   replication_running = false → fire 'db_replication_stopped' (critical)
   replication_lag_sec > 30 → fire 'db_replication_lag' (critical)

5. Auto-resolve: when condition clears for 2 consecutive evaluations
```

Buffer pool hit rate below threshold fires an alert — included under alert type `db_connections` with the message specifying the condition. All DB alert types are listed in the Alert model (`db_connections`, `db_replication_lag`, `db_replication_stopped`, `db_deadlock`).

---

## 10. Telegraf Config Injection

When credentials are saved, the backend re-deploys Telegraf config via SSH (steps 6–10 of the onboarding flow). The relevant injected config block:

```toml
[[inputs.mysql]]
  servers = ["opspilot_monitor:<password>@tcp(127.0.0.1:3306)/"]
  metric_version = 2
  gather_table_locks = true
  gather_slave_status = true    # true when is_replica = true
  gather_process_list = false
  gather_info_schema_auto_inc = false
```

- `<password>` is the plain-text password decrypted from `DBCredential.password_encrypted` at re-deploy time
- `gather_slave_status = true` only when `is_replica = true`; otherwise `false`
- The host:port from `DBCredential` is used, not hardcoded `127.0.0.1:3306`

The re-deploy job is the same APScheduler one-shot job used by the onboarding flow. Job ID: `redeploy_agents:{server_id}`. Only steps 6–10 run (configure and restart — no install steps).

---

## 11. Pinia Store — `useDbStore`

```ts
// State
credentialsByServer: Record<string, DBCredential | null>
                     // keyed by server_id; null = not configured
metricsLatest: Record<string, DBMetricsLatest>
                     // keyed by server_id; latest values for stat cards
isLoadingCredentials: boolean
isLoadingMetrics: boolean
error: string | null

// Getters
hasCredentials: (server_id: string) => boolean
connectionPct: (server_id: string) => number    // active/max * 100
isReplicationEnabled: (server_id: string) => boolean

// Actions
fetchCredentials(org_id: string): Promise<void>
saveCredentials(server_id: string, payload): Promise<void>
deleteCredentials(server_id: string): Promise<void>
fetchMetricsLatest(server_id: string): Promise<void>
fetchMetricsHistory(server_id: string, metric: string, range: string): Promise<ChartData>
```

`DBMetricsLatest` shape:
```ts
interface DBMetricsLatest {
  connections_active: number
  connections_max: number
  queries_per_sec: number
  slow_queries_per_min: number
  innodb_buffer_pool_hit_rate: number
  innodb_deadlocks: number
  replication_lag_sec: number | null
  replication_running: boolean | null
  table_locks_waited: number
  aborted_connections: number
  mariadb_version: string
  last_collected_at: string
}
```

---

## 12. API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/organizations/:org_id/db-credentials` | Required | List all servers with their credential status (no passwords returned) |
| POST | `/api/servers/:id/db-credentials` | Required (Admin) | Create DB credentials + trigger re-deploy |
| PATCH | `/api/servers/:id/db-credentials` | Required (Admin) | Update credentials + trigger re-deploy |
| DELETE | `/api/servers/:id/db-credentials` | Required (Admin) | Remove credentials + trigger re-deploy |

### 12.2 POST/PATCH `/api/servers/:id/db-credentials` Request Body

```json
{
  "host": "127.0.0.1",
  "port": 3306,
  "username": "opspilot_monitor",
  "password": "s3cr3t",
  "is_replica": false
}
```

`password` is optional on PATCH — omitting it preserves the existing encrypted value. `is_replica` controls whether `gather_slave_status = true` is injected into the Telegraf config and whether replication alerts are active for this server.
| GET | `/api/servers/:id/db-metrics/latest` | Required | Latest DB metric values (for stat cards) |
| GET | `/api/servers/:id/db-metrics` | Required | Time-series chart data |

### 12.1 GET `/api/organizations/:org_id/db-credentials`

Response — one entry per server in org:
```json
[
  {
    "server_id": "uuid",
    "server_name": "web-01",
    "has_credentials": true,
    "host": "127.0.0.1",
    "port": 3306,
    "username": "opspilot_monitor",
    "is_replica": false,
    "last_check_ok": true,
    "last_checked": "2026-06-01T14:00:10Z"
  },
  {
    "server_id": "uuid",
    "server_name": "app-02",
    "has_credentials": false
  }
]
```

Passwords are never returned by any endpoint.

### 12.2 GET `/api/servers/:id/db-metrics`

Query params: `?metric=connections_active&range=1h`

Supported `metric` values: `connections_active`, `queries_per_sec`, `slow_queries_per_min`, `innodb_buffer_pool_hit_rate`, `innodb_deadlocks`, `replication_lag_sec`, `table_locks_waited`, `aborted_connections`

Response:
```json
{
  "metric": "connections_active",
  "range": "1h",
  "data": [
    { "time": "2026-06-01T13:00:00Z", "value": 22 }
  ],
  "connections_max": 151
}
```

`connections_max` included only when `metric = 'connections_active'` (needed for the ceiling line).

---

## 13. Edge States

| State | Behaviour |
|---|---|
| No credentials configured | No-credentials state with SQL setup block (§3.2) |
| Credentials saved, re-deploy in progress | Server tab shows amber spinner "Deploying..."; dashboard not yet shown |
| Re-deploy failed | Server tab shows `⚠`; toast links to onboarding log |
| Telegraf connected but no DB data flowing | Likely wrong host/port or insufficient grants; show: "No DB metrics received yet — verify the monitoring user has the required grants (PROCESS, REPLICATION CLIENT, SELECT)" |
| `connections_max` = 0 or null | Connections gauge and alert evaluation disabled; show "max_connections not available" in gauge |
| `is_replica = false` but Telegraf collects replication metrics | Replication section hidden; replication alerts suppressed |
| `replication_running = false` (replica) | Red banner in replication section; alert fired immediately (no 2-consecutive rule — stop is binary) |
| `innodb_deadlocks` decreases (counter reset after MariaDB restart) | Backend detects `current < last_deadlock_count` → update `last_deadlock_count = current` without firing alert; treat as a clean slate |
| No servers in active org | "Add and onboard a server first" message with link to `/` |
| All servers configured but one in maintenance mode | DB metrics still collected and displayed; DB alerts suppressed for that server (same maintenance mode logic as other alerts) |
| Advanced Metrics panel, no data for table_locks / aborted_connections | Charts show "No data for this period" placeholder; metrics may not be emitted by all MariaDB versions |
| Password field left blank on edit | Existing encrypted password preserved; no re-deploy triggered unless other fields changed |

---

## 14. Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `←` / `→` | Navigate between server tabs |
| `1`–`5` | Switch time range (1h / 6h / 24h / 7d / 30d) |
| `e` | Open Edit Credentials modal (when server has credentials) |
| `Escape` | Close modal |
