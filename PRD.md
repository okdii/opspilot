# OpsPilot — Product Requirements Document

**Version:** 2.5  
**Date:** 2026-05-28  
**Status:** Final — Locked for Development  

---

## 1. Overview

OpsPilot is a self-hosted server and service monitoring tool built for a single operator managing 10+ Linux servers. It provides a real-time web dashboard, historical metrics, uptime tracking, SSL certificate monitoring, log collection, database health monitoring, cron/backup job tracking, and email alerting — all configurable through the UI.

---

## 2. Goals

- Centralise visibility across all servers into one dashboard
- Detect and alert on server resource issues (CPU, RAM, disk)
- Monitor service uptime/downtime and respond immediately
- Track SSL cert and domain registration expiry before they cause outages
- Collect and search logs from Nginx, PHP, MariaDB, and system sources
- Monitor cron jobs, backups, and database health proactively
- Give operator control during maintenance with alert silencing and acknowledgement

---

## 3. Non-Goals (v1)

- Mobile app
- Auto-remediation / runbooks
- Slack / Telegram / webhook alerts (email only for now)
- Custom proprietary agent — open source agents (Telegraf + Fluent Bit) are used instead
- External uptime check — deferred to v2 (see 5.14)
- Docker container monitoring — deferred (no Docker in current environment)

---

## 4. Users

| Role | Scope | Description |
|---|---|---|
| Admin | Global | Full access to all organizations, settings, alert rules, and user management |
| Operator | Per-org | Assigned to one or more orgs — can view everything within those orgs and act on alerts (acknowledge, snooze) and toggle maintenance mode |
| Viewer | Per-org | Assigned to one or more orgs — read-only access within those orgs |

- The first account created at `/setup` is always `Admin`
- Additional accounts are created via email invite only — no self-registration
- Each invite is for a specific organization with a specific role (Operator or Viewer)
- An admin can later assign the same user to additional organizations from `Settings → Team`
- A member with no org assignments cannot see any data

---

## 5. Functional Requirements

### 5.1 Authentication

- Login page with username + password
- JWT-based session auth
- Redirect unauthenticated users to login
- JWT token stored in httpOnly cookie
- Each JWT contains a `jti` (JWT ID) claim — a unique UUID per issued token, stored in the `Session` table and checked on every authenticated request to support revocation
- JWT lifetime: **24 hours** from issue time. On expiry the frontend receives a 401 and redirects to the login page — no silent token refresh in v1.

#### First-Run Setup Page

On first visit to a fresh OpsPilot installation (no admin account exists in the database), **all routes redirect to `/setup`**. The setup page collects:

- Username
- Password (min 8 characters)
- Confirm password (must match)

On submit, the backend creates the admin account, issues a JWT cookie, and redirects the admin directly to the dashboard — no separate login step needed. Once the admin account exists, `/setup` becomes permanently inaccessible (redirects to `/login`).

No env vars required for the initial admin account. The `OPSPILOT_ADMIN_USERNAME` and `OPSPILOT_ADMIN_PASSWORD` env vars are removed.

#### Role Permissions Matrix

Operator and Viewer permissions apply **only within their assigned organizations**. Admin permissions are global across all organizations.

| Action | Admin | Operator | Viewer |
|---|---|---|---|
| View dashboards, charts, logs | ✓ (all orgs) | ✓ (assigned orgs) | ✓ (assigned orgs) |
| View alerts | ✓ | ✓ | ✓ |
| Acknowledge / snooze alerts | ✓ | ✓ | ✗ |
| Toggle maintenance mode | ✓ | ✓ | ✗ |
| Add / edit / delete servers | ✓ | ✗ | ✗ |
| Add / edit / delete services, SSL, domains | ✓ | ✗ | ✗ |
| Manage alert rules | ✓ | ✗ | ✗ |
| Manage cron jobs / backup jobs | ✓ | ✗ | ✗ |
| Create / edit / delete organizations | ✓ | ✗ | ✗ |
| View and change settings | ✓ | ✗ | ✗ |
| Invite / manage team members | ✓ | ✗ | ✗ |

Backend enforces permissions on every API request — the frontend hides buttons as a convenience only, not as security.

#### Team Invite Flow

Admin invites a new team member from `Settings → Team`:

1. Admin selects an organization, enters the invitee's email address, and selects a role (Operator or Viewer) for that organization
2. Backend creates an `Invite` record with a UUID token and 48-hour expiry, sends an invite email
3. Invite email contains a link: `{base_url}/invite/{token}`
4. Invitee clicks the link → `/invite/{token}` page — they choose a username and password
5. On submit, backend validates the token, creates the `User` record (role = `'member'`), creates a `UserOrganization` entry for the org and role specified in the invite, marks the invite as accepted, issues a JWT cookie
6. Invitee is redirected to the dashboard — logged in immediately, scoped to their assigned organization

Invite link is single-use. Expired or already-accepted tokens show an error page. Admin can resend or revoke pending invites, and can add an existing user to additional organizations from `Settings → Team`.

#### WebSocket Authentication

Browser WebSocket connections cannot use httpOnly cookies directly on the WS upgrade request. The flow is:

1. Frontend calls `GET /api/ws-ticket` (authenticated via httpOnly JWT cookie) — backend returns a one-time ticket: a UUID with a 30-second TTL, stored in an in-process dict keyed by ticket UUID
2. Frontend opens WebSocket: `wss://<host>/ws?ticket=<uuid>`
3. Backend validates the ticket on upgrade — rejects if expired, unknown, or already used
4. Ticket is single-use: deleted immediately after a successful upgrade

This prevents the JWT from appearing in WebSocket URLs (and therefore server access logs).

---

### 5.2 Organization Management

Organizations are the top-level grouping for all servers, domains, and team assignments. Every server and domain belongs to exactly one organization.

#### Organization Fields

| Field | Detail |
|---|---|
| Name | e.g. "Acme Corp", "Client B" |
| Slug | URL-safe identifier, auto-generated from name, editable — e.g. `acme-corp` |
| Description | Optional free-text note |

#### CRUD Rules

- **Create**: Admin only. At least one org must exist before a server can be added. On first login after setup, a prompt or guided step encourages creating the first org.
- **Edit**: Name and description only — slug is locked after creation to avoid breaking bookmarks/URLs.
- **Delete**: Blocked if the org has any servers or domains. Admin must remove or reassign all resources first. Error shown: *"Remove all servers and domains from this organization before deleting it."*
- **List**: Admin sees all orgs. Operators/Viewers see only their assigned orgs.

#### Organization Switcher (Navigation)

A persistent org switcher sits at the top of the sidebar:
- **Admin**: dropdown shows all orgs + `All Organizations` (aggregate view) + `+ New Organization` shortcut
- **Operator / Viewer**: dropdown shows only assigned orgs (no `All Organizations`, no create option)
- If a member is assigned to exactly one org, the dropdown still renders but has only one option (no switching possible — label shows the org name)

The **active org** is stored in the Pinia store (`activeOrg`). All API calls include the active org context. Switching org triggers a data refresh across all active views.

---

### 5.3 Server Management

Add a server via UI form with the following fields:

| Field | Detail |
|---|---|
| Organization | Pre-filled with the active org — dropdown if admin wants to assign to a different org |
| Display name | e.g. "web-01" |
| IP address / hostname | Used for SSH onboarding |
| SSH port | Default 22 |
| SSH username | e.g. "ubuntu" — **must have passwordless sudo** (`NOPASSWD` entry in sudoers — required for writing agent configs to `/etc/`, running `systemctl`, enabling MariaDB slow query log). The onboarding script runs sudo commands non-interactively over SSH; if sudo prompts for a password the script will hang silently. |
| SSH auth type | Radio: **Private Key** or **Password** |
| SSH private key | Shown when auth type = Private Key — stored AES-256 encrypted |
| SSH password | Shown when auth type = Password — stored AES-256 encrypted |
| Tags / group | Optional — e.g. "production", "staging" |

- Edit and delete servers
- View all servers in a list/grid with current status

#### Server Deletion Behaviour

When a server is deleted from the UI:

| Item | Action |
|---|---|
| Server record | Soft-deleted (marked inactive, not hard-deleted) |
| Associated Services, CronJobs, BackupJobs, AlertRules | Cascade soft-deleted |
| Historical metrics in `server_metrics` | Retained until natural 30-day retention expiry |
| Historical logs in `server_logs` | Retained until natural 30-day retention expiry |
| Active alerts for the server (any state) | Marked resolved immediately |
| Telegraf + Fluent Bit on the remote server | **Not uninstalled** — agents will stop sending data; the 2-minute metric gap detector will fire then auto-resolve after the server record is soft-deleted |
| Re-adding the same server | Creates a new server record with a new UUID |

---

### 5.4 Server Metrics Monitoring

Collected by **Telegraf agent** installed on each server during onboarding, pushing every 10 seconds.  
All metrics stored as **TimescaleDB hypertables**, auto-partitioned by time.  
**Real-time:** Streamed live to dashboard via WebSocket (in-process live bus — see §5.4.8).  
**History:** Queryable for last 1h, 6h, 24h, 7d, 30d.

---

#### 5.4.1 CPU Metrics
Collected from: `/proc/stat`, `/proc/cpuinfo`

| Field | Description |
|---|---|
| `cpu_usage_total` | Overall CPU usage % across all cores |
| `cpu_usage_per_core` | Usage % per individual core — stored as one row per core with `labels = {"core": "0"}` |
| `cpu_user` | % time spent on user-space processes |
| `cpu_system` | % time spent on kernel/system processes |
| `cpu_iowait` | % time CPU waiting for I/O — high value = disk bottleneck |
| `cpu_steal` | % time stolen by hypervisor (VPS/cloud) — high = noisy neighbour |
| `cpu_idle` | % time CPU was idle |

---

#### 5.4.2 Memory Metrics
Collected from: `/proc/meminfo`

| Field | Description |
|---|---|
| `ram_total_gb` | Total physical RAM in GB |
| `ram_used_gb` | RAM actively in use (excludes buffers/cache) |
| `ram_available_gb` | RAM available for new processes (free + reclaimable cache) |
| `ram_usage_pct` | `ram_used / ram_total * 100` |
| `ram_buffers_gb` | Kernel buffers |
| `ram_cached_gb` | Page cache — high is normal and healthy |
| `swap_total_gb` | Total swap space |
| `swap_used_gb` | Swap currently in use |
| `swap_usage_pct` | High swap = RAM pressure, risk of slowdown |

---

#### 5.4.3 Disk Metrics
Collected from: `df -h` + `/proc/diskstats`

**Per mount point (e.g. `/`, `/data`, `/var`):**

| Field | Description |
|---|---|
| `disk_usage_pct` | Used % — stored with `labels = {"mount": "/data"}` |
| `disk_total_gb` | Total capacity — stored with mount label |
| `disk_used_gb` | Used space — stored with mount label |
| `disk_free_gb` | Free space — stored with mount label |
| `disk_inode_usage_pct` | Inode usage % — can hit 100% before disk is full |

**Per block device (e.g. `sda`, `nvme0n1`):**

| Field | Description |
|---|---|
| `disk_read_bytes_sec` | Read throughput — stored with `labels = {"device": "sda"}` |
| `disk_write_bytes_sec` | Write throughput |
| `disk_read_ops_sec` | Read IOPS |
| `disk_write_ops_sec` | Write IOPS |
| `disk_io_util_pct` | % time device was busy — near 100% = I/O saturation |
| `disk_avg_read_latency_ms` | Average read latency in milliseconds |
| `disk_avg_write_latency_ms` | Average write latency in milliseconds |

---

#### 5.4.4 Network Metrics
Collected from: `/proc/net/dev` — per active network interface (e.g. `eth0`, `ens3`).

| Field | Description |
|---|---|
| `net_bytes_recv_sec` | Inbound throughput — stored with `labels = {"interface": "eth0"}` |
| `net_bytes_sent_sec` | Outbound throughput |
| `net_packets_recv_sec` | Inbound packets/sec |
| `net_packets_sent_sec` | Outbound packets/sec |
| `net_errors_in` | Inbound error count (cumulative) |
| `net_errors_out` | Outbound error count (cumulative) |
| `net_drops_in` | Inbound dropped packets — NIC or buffer pressure |
| `net_drops_out` | Outbound dropped packets |

> **Cumulative counters:** `net_errors_in`, `net_errors_out`, `net_drops_in`, `net_drops_out` are raw cumulative counters from `/proc/net/dev`. The dashboard charts display the **delta per collection interval** (rate), not the raw counter. Telegraf's `inputs.net` plugin automatically computes rate from cumulative values — no extra transform required.

---

#### 5.4.5 System Metrics
Collected from: `/proc/uptime`, `/proc/loadavg`, `ps`

| Field | Description |
|---|---|
| `load_avg_1m` | Load average last 1 minute |
| `load_avg_5m` | Load average last 5 minutes |
| `load_avg_15m` | Load average last 15 minutes |
| `uptime_seconds` | Seconds since last reboot |
| `process_total` | Total running processes |
| `process_zombie` | Zombie process count — should always be 0 |
| `logged_in_users` | Number of active login sessions |

> **Note:** `os_distro` (e.g. "Ubuntu 22.04") and `kernel_version` (e.g. "5.15.0-91-generic") are **not** stored in `server_metrics`. They are string values collected once during onboarding via `uname` and stored directly on the `Server` model — see section 9.

---

#### 5.4.6 Top Processes (Snapshot)
Collected via `ps aux` every collection interval. Stored in `server_metrics` as a JSON snapshot:

- `metric_name = 'top_processes'`
- `value = NULL`
- `labels = {"top_cpu": [...], "top_mem": [...]}` — JSONB containing top 10 processes by CPU and top 10 by RAM

Each process entry: `{"pid": 1234, "name": "nginx", "cpu_pct": 12.3, "mem_pct": 2.1}`

The UI reads the most recent `top_processes` row to display the live process table, updated every 10s.

---

#### 5.4.7 TimescaleDB Storage Design

All metric rows written to a single hypertable:

```sql
server_metrics (
  time        TIMESTAMPTZ      NOT NULL,   -- TimescaleDB partition key
  server_id   UUID             NOT NULL,
  metric_name TEXT             NOT NULL,   -- e.g. "cpu_usage_total", "top_processes"
  value       DOUBLE PRECISION,            -- NULL for JSON-only rows (top_processes)
  labels      JSONB                        -- e.g. {"core": "2"} or {"mount": "/data"}
                                           -- or {"top_cpu": [...], "top_mem": [...]}
)
```

- Hypertable partitioned by `time` (chunk interval: 1 day)
- **Index:** `CREATE INDEX ON server_metrics (server_id, metric_name, time DESC)` — required for rolling average queries
- Continuous aggregate views:
  - `server_metrics_hourly` — 1h averages (retained 1 year)
  - `server_metrics_daily` — 24h averages (retained 1 year)
  - Both aggregate policies must include `WHERE metric_name != 'top_processes'` — those rows have `value = NULL` and represent JSON snapshots, not numeric time-series; including them adds processing overhead with no useful output
- Retention policy: raw data 30 days, aggregates 1 year

---

#### 5.4.8 WebSocket / Live Fan-out Architecture

New metric (and log) rows are pushed to connected browser clients without polling. The backend and the ingest endpoint run in the **same process** (single backend container), so fan-out is done **in-process** rather than through PostgreSQL `LISTEN/NOTIFY`.

> **Design note (v2.5 → implementation):** Earlier drafts specified PostgreSQL `LISTEN/NOTIFY` as the transport. That was changed during Phase 2 to an in-process bus for two reasons: (1) `NOTIFY` payloads are capped at 8 KB, which a `top_processes` metric batch can exceed; (2) with a single backend process, `NOTIFY`'s only real benefit — cross-process delivery — is unused. Phase 1 onboarding progress already uses this in-process pattern (`ws_manager.broadcast_onboarding`). `LISTEN/NOTIFY` remains the documented upgrade path if the backend is ever scaled to multiple worker processes (see "Future: multi-process").

**Live bus:** When `write_metrics()` persists rows, it also hands the parsed rows to an in-process `LiveBus` keyed by `server_id`. A single background task flushes each server's buffer every **500ms** (see Batching) and fans the batch out via the WebSocket manager.

**Channel naming:** One logical channel per server — `server_metrics:{server_id}` (e.g. `server_metrics:550e8400-e29b-41d4-a716-446655440000`). The flushed batch carries this `channel` field so the client can route it.

**Backend fan-out:** A flushed batch for a server is delivered to every WebSocket connection that is subscribed to **that server** (`{"action":"subscribe"}`) **or to that server's org** (`{"action":"subscribe_org"}` — the global dashboard). Connections viewing a different server/org receive nothing.

**Frontend subscription:** A single WebSocket connection handles all subscriptions for the session. The server detail page sends `{"action":"subscribe","server_id":"..."}` on mount and `{"action":"unsubscribe",...}` on unmount; the global dashboard sends `{"action":"subscribe_org","org_id":"..."}`. Every subscribe is **authorized** server-side against the user's role/org membership before it takes effect.

**Batching:** The backend buffers new rows for up to **500ms** before flushing to WebSocket clients — this collapses bursts (e.g. ~30 metric rows arriving at once after a 10s interval) into a single push, reducing frontend render churn.

**Log live tail** uses the same in-process pattern on channel `server_logs:{server_id}`.

**Future: multi-process.** If the backend is scaled to multiple worker processes, the `LiveBus` is the single seam to change: replace the in-process buffer with a PostgreSQL `LISTEN/NOTIFY` transport (NOTIFY a lightweight `server_id` signal; the listening worker re-queries recent rows and fans out), keeping the same WebSocket-facing API.

---

### 5.5 Service Monitoring

Each server can have multiple services added via UI form. Checks run from the OpsPilot backend (internal perspective — v1 only).

#### HTTP / Web App / API
- URL to probe (e.g. `https://app.example.com/health`)
- Method: GET (default)
- Expected HTTP status code (default: 200)
- Timeout (default: 5s, configurable per service)
- Check interval (default: 60s, configurable per service)
- **Ignore SSL errors** (boolean, default false) — when enabled, SSL certificate validation is skipped for this probe. Useful for internal services with self-signed certs. SSL expiry is still tracked separately via section 5.5 — this flag only affects the HTTP probe outcome.
- Records: status, response time (ms), last checked timestamp

#### Database Port Check (MySQL / MariaDB / PostgreSQL)
- Host + port TCP reachability check
- Records: port open/closed, latency (ms)

#### Custom TCP Port
- Host + port check
- Records: open/closed, latency (ms)

**Uptime history:** Stored and displayed as uptime % over 24h / 7d / 30d.

**Incident grouping:** An `Incident` record is created when a service transitions from up to down (on the **second** consecutive failed check, coinciding with the alert fire). The incident is closed when the next check succeeds. Fields: `started_at`, `resolved_at`, `duration_sec`, `cause` (populated from the failure reason: `http_error`, `timeout`, `connection_refused`, `wrong_status_code`).

**Service down detection:** A service is marked down after **2 consecutive failed check intervals** (not retries within the same interval). Each check runs once per configured interval. No within-interval retries.

**Consecutive failure tracking:** The `Service` model has a `consecutive_failures INTEGER` column (default 0). The evaluator increments it on each failed check and resets it to 0 on success. The alert fires when `consecutive_failures` reaches 2. This value is written to the DB in the same transaction as the `ServiceCheck` row — state survives backend restarts without needing in-memory counters.

#### ServiceCheck Retention
`service_checks` records are stored in a **TimescaleDB hypertable** (not a regular PostgreSQL table). At 1 check/min × 3 services × 50 servers = 216,000 rows/day. Retention: 90 days.

```sql
service_checks (
  time            TIMESTAMPTZ  NOT NULL,
  service_id      UUID         NOT NULL,
  status          TEXT         NOT NULL,  -- 'up' | 'down' | 'timeout'
  response_time_ms INTEGER
)
```

---

### 5.6 SSL Certificate Monitoring

SSL certs are linked to the `Domain` table (a domain must exist before an SSL cert can be added). This ensures SSL and domain expiry data are always co-located.

| Field | Detail |
|---|---|
| Domain (FK) | Links to `Domain.id` |
| Port | Default 443 |
| Check interval | Daily |
| Warn threshold | Days before expiry to send warning alert (default: 30, configurable per cert) |
| Critical threshold | Days before expiry to send critical alert (default: 7, configurable per cert) |

Displays:
- Certificate issuer
- Expiry date
- Days remaining
- Status: `valid` / `expiring_soon` / `critical` / `expired` / `unreachable` (port 443 refused or timed out — treated as unknown, not as an expiry alert)

> SSL check interval is **hardcoded to daily** in v1 and is not configurable per-cert.

---

### 5.7 Log Collection

Logs collected by **Fluent Bit agent** installed on each server during onboarding (Phase 1). Fluent Bit ships structured logs into a TimescaleDB hypertable as JSONB. The Log Viewer UI is built in Phase 3.

---

#### 5.7.1 Agent: Fluent Bit

| Property | Detail |
|---|---|
| Language | C — very low memory footprint (~1–3 MB RAM) |
| Runs as | systemd service alongside Telegraf |
| Output | PostgreSQL (TimescaleDB `server_logs` hypertable) via native plugin |
| Log format | Structured JSONB — parsed before storage |
| Config | Deployed per server by OpsPilot onboarding SSH script |

---

#### 5.7.2 System Logs

| Source | Path / Input | Fields Extracted |
|---|---|---|
| Syslog / journald | `systemd journal` (Fluent Bit `systemd` input) | timestamp, hostname, unit, priority, message |
| Auth & SSH | `/var/log/auth.log` (Debian) or `/var/log/secure` (RHEL) | timestamp, event (login/logout/fail/sudo), user, source IP |
| Kernel messages | `/var/log/kern.log` | timestamp, severity, subsystem, message |

---

#### 5.7.3 Nginx Logs

| Source | Path | Fields Extracted |
|---|---|---|
| Access log | `/var/log/nginx/access.log` | timestamp, client IP, method, URL, status code, response size, response time (ms), user agent, referrer |
| Error log | `/var/log/nginx/error.log` | timestamp, severity (warn/error/crit/alert), message, upstream |

Nginx access log must be in combined log format (default).

---

#### 5.7.4 PHP Logs

| Source | Path | Fields Extracted |
|---|---|---|
| PHP-FPM error log | `/var/log/php*-fpm.log` | timestamp, severity, pool name, PID, message |
| PHP application errors | `php.ini error_log` path (default: `/var/log/php_errors.log`) | timestamp, type (Notice/Warning/Fatal/Parse), file, line, message |

The PHP app error log path defaults to `/var/log/php_errors.log`. If the admin has a non-standard path, they can override it per server via the server settings UI after onboarding.

---

#### 5.7.5 MariaDB Logs

| Source | Path | Fields Extracted |
|---|---|---|
| Error log | `/var/log/mysql/error.log` | timestamp, severity, thread ID, message |
| Slow query log | `/var/log/mysql/slow.log` | timestamp, query time, lock time, rows examined, rows sent, user, host, query text |

Slow query log enabled automatically by onboarding script when MariaDB is detected (`slow_query_log=1`, `long_query_time=1`).

---

#### 5.7.6 TimescaleDB Log Storage Design

```sql
server_logs (
  time        TIMESTAMPTZ   NOT NULL,   -- TimescaleDB partition key
  server_id   UUID          NOT NULL,
  source      TEXT          NOT NULL,   -- 'nginx_access' | 'nginx_error' | 'php_fpm'
                                        -- | 'php_app' | 'mariadb_error' | 'mariadb_slow'
                                        -- | 'syslog' | 'auth' | 'kernel'
  severity    TEXT,                     -- 'debug' | 'info' | 'warn' | 'error' | 'fatal'
  message     TEXT,
  fields      JSONB                     -- source-specific parsed fields
)
```

- Hypertable partitioned by `time` (1-day chunks)
- Indexed on `(server_id, source, time DESC)` and `(server_id, severity, time DESC)`
- Retention: 30 days
- Full-text search via PostgreSQL `tsvector` index on `message`

---

#### 5.7.7 Log Viewer (Dashboard Page)

| Feature | Detail |
|---|---|
| Filter by server | Select one or all servers |
| Filter by source | nginx_access, php_app, mariadb_slow, syslog, auth, etc. |
| Filter by severity | info / warn / error / fatal |
| Full-text search | Search within `message` field |
| Time range picker | Last 15m / 1h / 6h / 24h / 7d / custom |
| Live tail mode | Real-time push via WebSocket (in-process live bus on `server_logs:{server_id}` — see §5.4.8) — no polling |
| Expandable rows | Click a row to see all parsed JSONB fields |
| Pagination | Cursor-based — API returns max **500 rows** per request with a `next_cursor` token; frontend loads the next page on scroll. Prevents unbounded result sets on broad time-range queries. |

---

#### 5.7.8 Log-Based Alert Conditions

| Condition | Trigger |
|---|---|
| PHP Fatal / Parse error | Any occurrence → immediate email |
| Nginx 5xx spike | > 10 errors/min → email |
| SSH brute force | > 5 failed auth attempts/min from same IP → email |
| MariaDB `[ERROR]` | Any occurrence → immediate email |
| Slow query spike | > 20 slow queries/min → email |

Log alert evaluation: backend scheduler queries `server_logs` for matching patterns on a 60-second interval using SQL `LIKE` or regex match on `message` and `severity` fields, as defined in each `LogAlertRule`.

**Default LogAlertRule rows** (auto-created at server onboarding — one row per condition below):

| Rule name | `source` | `pattern` (SQL LIKE) | `threshold` | `window_sec` | `severity` |
|---|---|---|---|---|---|
| PHP Fatal | `php` | `%Fatal error%` OR `%Parse error%` | 1 | 60 | `critical` |
| Nginx 5xx | `nginx` | `% 5__ %` (HTTP 5xx) | 10 | 60 | `critical` |
| SSH brute force | `auth` | `%Failed password%` | 5 | 60 | `critical` |
| MariaDB ERROR | `mariadb` | `%[ERROR]%` | 1 | 60 | `critical` |
| Slow query spike | `mariadb_slow` | `%` (all slow query entries) | 20 | 60 | `warning` |

- `threshold`: minimum count of matching log entries within `window_sec` to trigger the alert
- `window_sec`: look-back window in seconds (default 60 for all rules)
- A `threshold` of 1 means any single matching entry triggers the alert immediately
- SSH brute force threshold is per-source-IP: the evaluator groups by the source IP parsed from the log entry; alert fires when any single IP has ≥ 5 failed attempts within the window

---

### 5.8 Database Deep Monitoring

Real MariaDB health metrics collected via **Telegraf `inputs.mysql` plugin** using a read-only monitoring user.

#### Setup
The admin must **manually create** the MariaDB monitoring user on the target server before entering credentials in OpsPilot. OpsPilot does not create this user automatically — it has no privileged MariaDB connection to do so. Minimum required grants:

```sql
CREATE USER 'opspilot_monitor'@'%' IDENTIFIED BY '<password>';
GRANT PROCESS, REPLICATION CLIENT, SELECT ON *.* TO 'opspilot_monitor'@'%';
FLUSH PRIVILEGES;
```

Once the user exists, the admin provides credentials via UI:
- Host, port, monitoring username, password (stored AES-256 encrypted in `DBCredential`)
- On save, OpsPilot automatically re-deploys the Telegraf config via SSH (same mechanism as the manual "Re-deploy agents" button) to inject `inputs.mysql` and restart Telegraf — no manual SSH step required
- Telegraf then pushes DB metrics to TimescaleDB alongside other server metrics

#### Metrics Collected

| Metric | Description | Alert Condition |
|---|---|---|
| `connections_active` | Current open connections | > 80% of `max_connections` (rolling 5-min avg) |
| `connections_max` | `max_connections` setting | — |
| `queries_per_sec` | Query throughput | Trend only |
| `slow_queries_per_min` | Slow queries per minute | > threshold (configurable) |
| `innodb_buffer_pool_hit_rate` | Cache hit ratio % | Rolling 5-min average < 90% |
| `innodb_deadlocks` | Deadlock count (cumulative) | Any increase vs `DBCredential.last_deadlock_count` since last evaluation → alert; `last_deadlock_count` updated after each evaluation |
| `replication_lag_sec` | Seconds behind master (replica only) | > 30s → alert |
| `replication_running` | Is replication thread running | false → immediate alert |
| `table_locks_waited` | Lock contention count (cumulative) | Rate > **10 new lock waits/min** (rolling 5-min avg) — configurable per-server via AlertRule |
| `aborted_connections` | Failed connection attempts (cumulative) | Rate > **5 new aborted connections/min** (rolling 5-min avg) — configurable per-server via AlertRule |

> **Replication metrics** are only meaningful on replica servers. The admin designates a server as a replica by enabling the replication section in the DB credential form. If replication is not enabled, replication metrics are collected but replication alerts are suppressed.

---

### 5.9 Domain Expiry Monitoring

Domain registration expiry is separate from SSL cert expiry. An expired domain kills everything regardless of server health.

- Admin adds domains via UI
- OpsPilot performs WHOIS lookup once daily
- WHOIS checks are staggered across the day (one per domain, 30-second delay between lookups) to avoid rate-limiting by registrar WHOIS servers
- Alert thresholds configurable per domain

#### Fields Tracked

| Field | Description |
|---|---|
| `domain` | e.g. `example.com` |
| `registrar` | Domain registrar name |
| `expiry_date` | Registration expiry date |
| `days_remaining` | Computed daily |
| `warn_days` | Days before expiry to send warning (default: 60) |
| `critical_days` | Days before expiry to send critical alert (default: 30) |
| `status` | `valid` / `expiring_soon` / `critical` / `expired` |

`Domain` is the parent record. `SSLCert` records link to `Domain` via `domain_id` foreign key — ensuring SSL and domain expiry are always co-located in the UI.

---

### 5.10 Cron Job Monitoring

**Approach: Heartbeat / Dead Man's Switch**

#### How It Works
1. Admin registers a cron job in UI: name, server, cron schedule, grace period
2. OpsPilot generates a unique ping URL: `{base_url}/ping/{uuid}`
3. Admin appends to end of cron script:
   ```bash
   curl -s {base_url}/ping/abc123 > /dev/null
   ```
4. OpsPilot tracks last ping vs expected schedule (cron expression parsed via Python `croniter` library)
5. If overdue beyond grace period → email alert

Ping URL is unauthenticated by design — the UUID is the only secret. This is acceptable for a single-admin internal tool.

#### Two-Ping Mode (Optional Duration Tracking)

To track how long a cron job takes, the admin can send a start ping and an end ping using a `?event=` query parameter:

```bash
# At the top of the cron script (optional):
curl -s "{base_url}/ping/abc123?event=start" > /dev/null

# ... script body ...

# At the end (required):
curl -s "{base_url}/ping/abc123?event=end" > /dev/null
```

- `?event=start` — records `start_ping_at` timestamp on `CronJob`; does **not** update `last_ping_at` or trigger watchdog evaluation
- `?event=end` — records `last_ping_at`, computes `last_duration_sec = last_ping_at - start_ping_at` if `start_ping_at` is set, then clears `start_ping_at`
- No `?event=` param (single-ping mode) — treated as `?event=end`; `last_duration_sec` remains NULL

#### Fields Tracked

| Field | Description |
|---|---|
| `last_ping_at` | Timestamp of last end/single ping — used by watchdog to evaluate `next_expected_at` |
| `start_ping_at` | Timestamp of last start ping (NULL if two-ping mode not used; cleared after end ping) |
| `last_duration_sec` | Computed: `last_ping_at - start_ping_at` (NULL in single-ping mode) |
| `status` | `healthy` / `late` / `missing` |
| `next_expected_at` | Computed from cron expression + last ping using `croniter` (not stored) |

#### Status Transition Timing

| Status | Condition |
|---|---|
| `healthy` | `now() < next_expected_at` (or ping received before next expected run) |
| `late` | `now() >= next_expected_at` AND `now() < next_expected_at + grace_period_min` |
| `missing` | `now() >= next_expected_at + grace_period_min` → watchdog fires alert and writes a `CronJobRun` with `outcome = 'missed'` |

The watchdog evaluator runs every 60 seconds and computes `next_expected_at` on each tick using `croniter` from the cron expression and `last_ping_at`. No `next_expected_at` value is persisted — it is always recomputed.

**Run history:** Each successful end-ping and each detected miss creates a `CronJobRun` row (see section 9). The 30-day calendar heatmap chart (section 5.16.10) reads from this table — green = success, red = missed, grey = no data for that day.

---

### 5.11 Backup Monitoring

Same heartbeat mechanism as cron job monitoring but with backup-specific payload.

#### Ping Payload
```bash
curl -s -X POST {base_url}/ping/abc123 \
  -d "status=success&size_bytes=1048576&exit_code=0"
```

#### Alert Conditions

| Condition | Trigger |
|---|---|
| No backup received | Beyond schedule + grace period |
| Backup reported failure | exit_code != 0 |
| Backup size dropped > 20% | Compared to `previous_size_bytes` (the last successful run's size) |
| Backup size is zero | Immediate alert |

**First run handling:** The 20% size-drop check and the "size is zero" check are skipped when `previous_size_bytes` is NULL (i.e. on the very first successful backup ping). After each successful run, the backend sets `previous_size_bytes = last_size_bytes` before updating `last_size_bytes` — making the previous value available from the second run onward.

**`status` vs `exit_code` precedence:** `exit_code` is authoritative. `exit_code != 0` always triggers a failure alert regardless of the `status` field value. The `status` field is informational only — it is stored in `BackupJob.last_status_text` but not evaluated. If `exit_code` is absent from the payload, it defaults to `0` (success).

**Run history:** Each ping (success or failure) and each detected miss creates a `BackupRun` row (see section 9). The 30-day calendar heatmap chart (section 5.16.10) reads from this table — green = success, red = failed/missed, grey = no data for that day.

---

### 5.12 Maintenance Mode

Silences all alerts for a server during planned maintenance without stopping metric/log collection.

#### How It Works
- Toggle maintenance mode per server from the dashboard
- Set optional: start time, end time, reason/note
- During window: alerts suppressed, server shows maintenance badge in UI, data collection continues
- When window ends (scheduled `ends_at` passes): alerting automatically resumes — checked by the APScheduler maintenance-expiry job (runs every 60s)
- Maintenance start/end events written to `Alert` table with `type = 'maintenance'` for audit trail

#### Fields

| Field | Description |
|---|---|
| `server_id` | Which server |
| `started_at` | When maintenance began |
| `ends_at` | Scheduled end (optional — can be open-ended) |
| `reason` | Free text note (e.g. "OS kernel upgrade") |
| `is_active` | Boolean — set false automatically when `ends_at` passes |

---

### 5.13 Alerting

#### 5.13.1 Alert Conditions

The `Alert.severity` field is set at fire time based on which threshold was crossed:

| Condition | Default Threshold | Severity |
|---|---|---|
| CPU usage high | Rolling 5-min average > 85% | `critical` |
| RAM usage high | Rolling 5-min average > 90% | `critical` |
| Disk usage high | Rolling 5-min average > 85% on any mount | `critical` |
| Disk inode usage high | Rolling 5-min average > 90% | `critical` |
| Server agent offline | No metrics in TimescaleDB for > 2 minutes | `critical` |
| Service down | 2 consecutive failed check intervals | `critical` |
| SSL cert expiring (warn) | days_remaining ≤ warn_days (default 30d) | `warning` |
| SSL cert expiring (critical) | days_remaining ≤ critical_days (default 7d) | `critical` |
| Domain expiring (warn) | days_remaining ≤ warn_days (default 60d) | `warning` |
| Domain expiring (critical) | days_remaining ≤ critical_days (default 30d) | `critical` |
| Cron job / backup missing | No ping beyond schedule + grace period | `critical` |
| Backup size anomaly | Size dropped > 20% vs previous run, or size is zero | `critical` |
| MariaDB connections high | > 80% of `max_connections` (rolling 5-min avg) | `critical` |
| MariaDB replication lag | > 30 seconds behind master | `critical` |
| MariaDB deadlock | Any increase in `innodb_deadlocks` count since last evaluation | `critical` |
| PHP Fatal / Parse error | Any log occurrence | `critical` |
| Nginx 5xx spike | > 10 errors/min | `warning` |
| SSH brute force | > 5 failed auth attempts/min from same IP | `critical` |
| MariaDB `[ERROR]` in log | Any log occurrence | `critical` |
| Slow query spike | > 20 slow queries/min | `warning` |

---

#### 5.13.2 Alert Threshold Evaluation

**Rolling average rule (metric alerts):**  
The scheduler queries the rolling N-minute average of the metric from TimescaleDB. An alert fires when the rolling average exceeds the threshold — not individual spikes. This prevents transient CPU spikes from generating false alerts.

- CPU / RAM / Disk rolling window: **5 minutes**
- MariaDB connections rolling window: **5 minutes**
- Evaluation frequency: every **30 seconds**

**Event-based rule (log alerts, service checks):**  
Evaluated on each scheduler tick. Log pattern queries run against `server_logs` on a 60-second interval using SQL pattern matching on `message` and `severity`.

---

#### 5.13.3 Alert Rules

- All thresholds configured **per server** — no global defaults
- **Auto-creation on server add**: When a server is successfully onboarded, the backend automatically creates one `AlertRule` row per metric using the default thresholds from section 5.13.1 (CPU > 85%, RAM > 90%, Disk > 85%, Disk inode > 90%). It also creates one `LogAlertRule` row for each of the 5 log alert conditions from section 5.7.8 (PHP Fatal, Nginx 5xx, SSH brute force, MariaDB ERROR, slow query), using the default thresholds. All rules are enabled by default. The admin can edit or delete any rule from the Alerts → Rules page at any time. No manual rule creation is needed for basic alerting from day one.
- **Alert cooldown**: do not re-send the same alert within 1 hour (stored in `AlertRule.cooldown_min`)
- For service down / SSL / domain / cron / backup alerts (which have no `AlertRule` entry), cooldown is hardcoded to 1 hour in the alert evaluator
- **Maintenance mode**: all alerts suppressed during active maintenance window (section 5.11)
- **Acknowledgement/Snooze**: see section 5.13
- Email includes: server name, metric, current value, threshold, timestamp, link to dashboard

---

#### 5.13.4 Alert Auto-Resolve

The scheduler continuously re-evaluates every alert in `firing`, `acknowledged`, or `snoozed` state:

- **Metric alerts**: re-evaluated every 30 seconds
- **Service check alerts**: re-evaluated on next check interval
- **Auto-resolve trigger**: condition no longer met for **2 consecutive evaluations**
- On resolve: alert state → `resolved`, cooldown lifted, re-firing allowed if condition returns
- Email sent on resolve: "Alert resolved — [server] [metric] returned to normal"

**Snoozed alert behavior:** The condition is still checked on every evaluation tick during the snooze period — no email is sent while snoozed. If the condition clears before the snooze expires, the alert moves to `resolved` (the `snoozed → resolved` path in the state machine). If the snooze expires and the condition is still present, the alert returns to `firing` and a new email is sent.

---

### 5.14 Alert Acknowledgement & Snooze

#### Acknowledge
- Click "Acknowledge" on any active alert in the dashboard
- Stops repeat emails for that alert
- Alert remains visible in UI marked as `acknowledged`
- Auto-resolve continues to evaluate — if condition clears, alert moves to `resolved`

#### Snooze
- Snooze for: 15 min / 30 min / 1h / 4h / custom
- Alert re-fires after snooze period **only if condition is still present**
- If condition clears during snooze: alert moves to `resolved` (does not return to `firing`)

#### Alert State Machine

```
firing → acknowledged → resolved        (auto, when condition clears for 2 consecutive checks)
firing → acknowledged → snoozed         (admin snoozes an already-acknowledged alert)
firing → snoozed → firing               (condition still present after snooze expires)
firing → snoozed → resolved             (condition clears before snooze expires)
firing → resolved                       (auto, when condition clears for 2 consecutive checks)
```

#### Dashboard Changes
- Active alerts panel: Firing / Acknowledged / Snoozed state badges
- Acknowledge and Snooze buttons on each alert row
- Alert history shows full lifecycle: fired → ack → resolved

---

### 5.15 External Uptime Check *(Deferred to v2)*

**Scope decision: out of v1.**

All HTTP/TCP service checks in v1 run from OpsPilot's own server (internal perspective only).

**v2 plan:** Deploy a lightweight external prober on a separate VPS/region. Service cards will show two indicators — internal + external — to distinguish "OpsPilot can't reach it" from "public internet can't reach it".

---

### 5.16 UI & Frontend Design

---

#### 5.16.0 Component Reuse Principle (Always Follow)

> **All UI/UX work must reference an existing component and reuse it before building anything new.**

Before designing or coding any screen, element, or layout:

1. **Look first.** Check `frontend/src/components/` (Charts, StatusBadge, MetricCard, LogViewer, AlertRow, …) and the Vuestic UI library for a component that already does the job.
2. **Reuse, don't recreate.** If a matching component exists, use it as-is. Do not build a parallel/duplicate component.
3. **Extend, don't fork.** If an existing component is close but not exact, extend it via props/slots/variants so every caller benefits. Never copy-paste a component to tweak it.
4. **Promote on the second use.** The moment a pattern (badge, card, chart wrapper, table row, empty/loading/error state) is needed in a second place, extract it into a shared component in `frontend/src/components/` and reference it everywhere.
5. **Single source of truth.** Status colors, spacing, typography, and chart config come from the shared component + Vuestic/Tailwind theme tokens (§5.16.2) — never hardcoded per page.

This keeps the dark dashboard visually consistent and is enforced via the **UI/UX Pro Max skill** (see Development Rules). When the skill is invoked for any screen, it must first identify the reusable component(s) involved and reference them by name.

---

#### 5.16.1 Template & Framework

| Property | Choice |
|---|---|
| Base template | **Vuestic Admin** (open source, 10k+ GitHub stars) |
| Framework | Vue 3 + Vite + Pinia |
| UI component library | Vuestic UI (bundled with template) |
| CSS | Tailwind CSS + Vuestic theme tokens |
| Charts | **ApexCharts** (via Vuestic's built-in `VaChart` wrapper) |
| State management | Pinia stores (servers, metrics, logs, alerts, ws) |
| Theme | Dark mode default |

---

#### 5.16.2 Color Language (Status Badges)

| State | Color | Usage |
|---|---|---|
| Online / Healthy / Up | Green `#22c55e` | Server online, service up, cert valid |
| Warning / Expiring | Amber `#f59e0b` | High metric, cert expiring soon |
| Critical / Down / Error | Red `#ef4444` | Server down, service down, cert expired |
| Maintenance | Blue `#3b82f6` | Server in maintenance window |
| Unknown / No data | Grey `#6b7280` | Never checked, agent offline |

---

#### 5.16.3 Navigation Layout

```
┌─────────────────────────────────────────────────────┐
│  OpsPilot                              🔔  Admin     │  ← Top bar
├──────────────┬──────────────────────────────────────┤
│  Overview    │                                       │
│  Servers     │   Main content area                   │
│  Services    │                                       │
│  Logs        │                                       │
│  SSL/Domains │                                       │
│  Database    │                                       │
│  Cron/Backup │                                       │
│  Alerts      │                                       │
│  Settings    │                                       │
│              │                                       │
│  Status Page │                                       │
└──────────────┴──────────────────────────────────────┘
```

---

#### 5.16.4 Overview Page

```
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ Servers  │ │ Services │ │  Alerts  │ │SSL/Domain│
│ 12 total │ │ 48 up    │ │  3 firing│ │ 2 expiring│
│ 11 ✓ 1✗ │ │  2 down  │ │          │ │          │
└──────────┘ └──────────┘ └──────────┘ └──────────┘

Server Cards Grid (responsive 3–4 col):
┌─────────────────────┐  ┌─────────────────────┐
│ ● web-01  [prod]    │  │ ● db-01   [prod]    │
│ CPU  ████░░ 72%     │  │ CPU  ██░░░░ 38%     │
│ RAM  █████░ 84%     │  │ RAM  ████░░ 61%     │
│ Disk ████░░ 67%     │  │ Disk ███░░░ 52%     │
│ 3 services ✓        │  │ 2 services ✓        │
└─────────────────────┘  └─────────────────────┘

Recent Alerts (last 10):
┌────────────────────────────────────────────────────┐
│ 🔴 web-02  CPU > 85%          2 min ago  [Ack]    │
│ 🟡 web-03  SSL expiring 14d   1 hr ago   [Ack]    │
│ 🔴 api-01  Service down       3 hr ago   [Snoozed]│
└────────────────────────────────────────────────────┘
```

---

#### 5.16.5 Server Detail Page — Chart Types

**CPU**
| View | Chart Type | Config |
|---|---|---|
| Current usage | Radial gauge | 0–100%, green→amber→red |
| Per-core usage | Horizontal bar chart | One bar per core |
| History (1h/6h/24h/7d) | Area line chart | Gradient fill, time on x-axis |
| iowait + steal | Stacked area chart | Two layers on same axis |

**Memory (RAM + Swap)**
| View | Chart Type | Config |
|---|---|---|
| Current RAM | Radial gauge | used % |
| RAM breakdown | Stacked horizontal bar | used / cached / free |
| History | Area line chart | Two lines: used + available |
| Swap usage | Area line chart | Shown only if swap > 0 |

**Disk**
| View | Chart Type | Config |
|---|---|---|
| Space per mount | Donut chart | One segment per mount |
| Space history | Area line chart | One line per mount |
| I/O throughput | Line chart (dual) | Read + write bytes/sec |
| IOPS | Line chart (dual) | Read + write IOPS |
| I/O utilisation % | Area line chart | Fills red near 100% |
| Read/Write latency | Line chart (dual) | ms — threshold line overlay |

**Network**
| View | Chart Type | Config |
|---|---|---|
| Throughput | Line chart (dual) | in (green) + out (blue) per interface |
| Packets/sec | Line chart (dual) | in + out |
| Errors + drops | Bar chart | Grouped per interface |

**System**
| View | Chart Type | Config |
|---|---|---|
| Load average | Line chart (3 lines) | 1m / 5m / 15m — reference line at core count |
| Process count | Line chart | Total over time |
| Zombie processes | Bar chart | Should be near 0 |

**Top Processes**
| View | Chart Type | Config |
|---|---|---|
| By CPU | Horizontal bar chart | Top 10, live-updated via WebSocket on each new `top_processes` row |
| By RAM | Horizontal bar chart | Top 10, live-updated via WebSocket |

---

#### 5.16.6 Service Monitoring — Chart Types

| View | Chart Type | Config |
|---|---|---|
| Uptime status timeline | Timeline bar | Green = up, Red = down — last 90 days |
| Uptime % summary | Stat card with badge | 24h / 7d / 30d |
| Response time history | Line chart | ms on y-axis — threshold overlay |
| Response time distribution | Histogram | <100ms / 100–300ms / 300–500ms / >500ms |
| Incident list | Table | started_at, resolved_at, duration, cause |

---

#### 5.16.7 SSL & Domain — Chart Types

| View | Chart Type | Config |
|---|---|---|
| Days remaining | Horizontal progress bar | Green → amber (<30d) → red (<7d) |
| Combined certs + domains table | Data table | Sortable by expiry, colour-coded rows |
| Expiry timeline | Scatter / milestone chart | Dots on timeline, click for detail |

---

#### 5.16.8 Log Viewer — Chart Types

| View | Chart Type | Config |
|---|---|---|
| Log volume over time | Stacked bar chart | Bars per hour, stacked by severity |
| Log entries | Virtualised data table | Colour-coded by severity, expandable JSONB |
| Error rate trend | Line chart | Errors/min — alert threshold overlay |

---

#### 5.16.9 Database Health — Chart Types

| View | Chart Type | Config |
|---|---|---|
| Active connections | Line chart | With max_connections as dotted red ceiling |
| Connections gauge | Radial gauge | % of max_connections |
| Queries per second | Area line chart | Smooth fill |
| Slow queries | Bar chart | Per-minute — threshold overlay |
| InnoDB buffer pool hit rate | Radial gauge | Target > 95%, red below 90% |
| Deadlocks | Bar chart | Per-hour — any bar = alert event |
| Replication lag | Line chart | Seconds behind master |

---

#### 5.16.10 Cron & Backup Jobs — Chart Types

| View | Chart Type | Config |
|---|---|---|
| Run history | Calendar heatmap | Green/red/grey per day — 30 days |
| Job duration trend | Line chart | Seconds per run — spike = slow |
| Backup size trend | Line chart | Bytes per run — sudden drop = alert |
| Job status list | Data table | Status badge, last run, next expected, ping URL |

---

#### 5.16.11 Alerts Page

| View | Chart Type | Config |
|---|---|---|
| Alert frequency | Bar chart | Alerts per day, 30 days — grouped by severity |
| Active alerts list | Data table | Sortable, state badge, Ack/Snooze buttons |
| Alert history | Data table with filters | Server, type, state, date range |

---

#### 5.16.12 Public Status Page (Unauthenticated `/status`)

Minimal public-facing design — no sidebar, light or dark theme.

```
┌─────────────────────────────────────────────────────┐
│           MyCompany System Status                    │
│         All systems operational ✓                    │
├─────────────────────────────────────────────────────┤
│  Web App          ████████████████████  99.9%  ✓    │
│  API              ████████████████████  100%   ✓    │
│  Dashboard        ██████████████████░░  98.1%  ✓    │
├─────────────────────────────────────────────────────┤
│  Past Incidents                                      │
│  2026-05-20  API slow response  — Resolved (12 min) │
└─────────────────────────────────────────────────────┘
```

- 90-day uptime timeline bar per service
- Uptime % stat card
- Active incident banner (if any)
- Past incident list
- No login required — shareable URL
- Admin controls which services appear via the `is_public` toggle on each service record

---

### 5.17 Server Onboarding Flow (Auto-Deploy via SSH)

#### Pre-condition: Hypertables Must Exist Before Agents Connect

Telegraf's PostgreSQL output plugin auto-creates tables if they don't exist — but as regular PostgreSQL tables, not TimescaleDB hypertables. To prevent this, Alembic migrations must complete and create all hypertables before any Telegraf agent can reach port 5432.

**How this is enforced in Docker Compose:**

1. A dedicated `migrate` service runs `alembic upgrade head` and exits (not a long-running container)
2. `opspilot-backend` has `depends_on: migrate: condition: service_completed_successfully`
3. Port 5432 is exposed on the host **only after migrations succeed** — enforced in the deployment runbook (`docker-compose run --rm migrate && docker-compose up -d`)
4. Firewall rules (ufw/iptables) restricting port 5432 to monitored server IPs are applied at the OS level before the compose stack starts

This ensures the hypertables always exist before the first Telegraf connection.

---

#### Step-by-Step Flow

```
Admin fills server form (name, IP, SSH auth type + credentials, tags)
        ↓
OpsPilot validates SSH connection (SSH user must have sudo)
        ↓
OpsPilot SSHes in and runs setup sequence:
  1. Detects OS distro + version (Ubuntu/Debian vs RHEL/CentOS)
  1b. Adds vendor package repositories (not in default OS repos):
       - InfluxData repo (Telegraf):
           Debian/Ubuntu: wget+gpg key, add apt source
           RHEL/CentOS: wget+rpm key, add yum repo
       - Fluent Bit repo (Chronosphere/Calyptia):
           Debian/Ubuntu: curl+gpg key, add apt source
           RHEL/CentOS: curl+rpm key, add yum repo
       Step fails fast with a clear error if wget/curl is unavailable.
  2. Installs Telegraf via package manager (apt/yum)
  3. Installs Fluent Bit via package manager
  4. Generates telegraf.conf from Jinja2 template:
       - server_id UUID
       - TimescaleDB connection string (opspilot_writer user)
       - Plugins: cpu, mem, disk, diskio, net, system,
         processes, procstat, systemd_units
       - inputs.mysql plugin if MariaDB creds already provided
  5. Generates fluent-bit.conf from Jinja2 template:
       - server_id UUID
       - TimescaleDB connection string
       - Log paths set per distro:
           auth.log → /var/log/auth.log (Debian) | /var/log/secure (RHEL)
       - Nginx, PHP-FPM, MariaDB log paths configured
  5b. If MariaDB detected:
       - Enables slow_query_log=1, long_query_time=1
       - Restarts MariaDB to apply
  6. Writes configs to /etc/telegraf/ and /etc/fluent-bit/
  7. Enables and starts both services via systemctl
  8. Waits up to 30s for first metric row to appear in TimescaleDB
        ↓
OpsPilot marks server active — appears on dashboard
        ↓
Admin sees live metrics within ~15 seconds
```

**Phase 1:** Agents installed and pushing data (metrics + logs both flow from day one).  
**Phase 3:** Backend reads `server_logs` hypertable and exposes Log Viewer UI — logs are buffered in TimescaleDB from Phase 1 onward.

---

#### Security — Agent DB Credentials

- Telegraf and Fluent Bit use dedicated write-only PostgreSQL user `opspilot_writer`
- `opspilot_writer` has INSERT-only access to `server_metrics` and `server_logs` — no READ, UPDATE, DELETE
- FastAPI backend uses `opspilot_app` with full access
- Connection string embedded in agent config files on the remote server (standard practice)

---

#### Re-deploy / Update Config

- Admin can trigger "Re-deploy agents" from the server detail page
- OpsPilot re-SSHes and overwrites configs + restarts services
- This is also triggered automatically when MariaDB credentials are saved for a server post-onboarding

---

#### Onboarding Status UI

- Progress shown in real time: Connecting → Installing Telegraf → Installing Fluent Bit → Configuring → Verifying → Done
- If any step fails: error message + SSH log output shown to admin

---

### 5.18 OpsPilot Deployment

OpsPilot runs on a **dedicated separate server** — isolated from all monitored servers.

#### Server Requirements

| Component | Minimum |
|---|---|
| OS | Ubuntu 22.04 LTS |
| CPU | 2 vCPU |
| RAM | 4 GB |
| Disk | 50 GB SSD (30 days × 50 servers ≈ 20–30 GB) |
| Network | Public IP or VPN reachable by all monitored servers |

#### Network Access

| Direction | Port | Purpose |
|---|---|---|
| OpsPilot → monitored servers | 22 | SSH — onboarding only |
| Monitored servers → OpsPilot | 5432 | Telegraf + Fluent Bit push to TimescaleDB. **Firewall must restrict to monitored server IPs only — never open to public internet.** |
| OpsPilot → internet | 443 | WHOIS checks, SMTP |
| Admin browser → OpsPilot | 443 | HTTPS — via Nginx reverse proxy + Let's Encrypt |

#### Docker Compose Stack

```
docker-compose.yml
├── migrate            (one-shot: runs alembic upgrade head, then exits)
├── opspilot-backend   (FastAPI — depends on migrate completing)
├── opspilot-frontend  (Vue.js static files served via Nginx — ports 80/443)
├── postgres           (PostgreSQL + TimescaleDB — port 5432)
└── nginx              (reverse proxy: routes /api → backend, / → frontend, TLS termination)
```

The frontend container runs Nginx to serve static Vue.js files. The outer `nginx` container reverse-proxies all traffic and handles TLS. This is standard two-Nginx architecture for containerised Vue + FastAPI.

#### Required Environment Variables

| Variable | Description |
|---|---|
| `OPSPILOT_ENCRYPTION_KEY` | Master AES-256 key used to encrypt SSH credentials, DB passwords, and sensitive settings values. Must be a 32-byte (256-bit) value encoded as a base64 string. **If lost, all encrypted secrets are permanently unrecoverable.** Generate once (`openssl rand -base64 32`) and store in a password manager or secret manager before first run. Never rotate this key without first decrypting and re-encrypting all stored secrets. |
| `OPSPILOT_JWT_SECRET` | Secret key used to sign and verify JWTs. Must be a long random string (min 32 characters). Generate once (`openssl rand -hex 32`). If changed, all existing sessions are instantly invalidated. |
| `DATABASE_URL` | PostgreSQL connection string for the `opspilot_app` user |
| `OPSPILOT_WRITER_PASSWORD` | Password for the `opspilot_writer` INSERT-only PostgreSQL user. Alembic migrations use this to `CREATE USER opspilot_writer` on first run. At onboarding time the backend embeds this password into the Telegraf and Fluent Bit configs it deploys to each server so agents can push metrics/logs directly to TimescaleDB. Must be set before the first migration. |

Startup aborts with a clear error if any of these are absent.

---

### 5.19 Settings Page

Authenticated admin only.

#### SMTP / Email

| Setting | Description |
|---|---|
| SMTP host | e.g. `smtp.gmail.com` |
| SMTP port | e.g. `587` (TLS) |
| Username | SMTP login |
| Password | Stored AES-256 encrypted |
| From address | e.g. `opspilot@yourdomain.com` |
| Alert recipient email(s) | Comma-separated |
| Test button | Sends a test email |

#### OpsPilot Identity

| Setting | Description |
|---|---|
| Instance name | Shown in emails and status page |
| Base URL | e.g. `https://monitor.yourdomain.com` — used in alert email links and heartbeat ping URLs |

#### Data Retention

| Setting | Default |
|---|---|
| Raw metrics retention | 30 days |
| Log retention | 30 days |
| Alert history retention | 90 days |

Changing a retention setting updates the TimescaleDB retention policy via `SELECT add_retention_policy(...)` on the relevant hypertable — applied immediately.

#### Security

| Setting | Description |
|---|---|
| Change admin password | Current + new + confirm |
| Active sessions | View and revoke JWT sessions — the UI reads the `Session` table and shows each active session (issued_at, ip_address, user_agent). Revoking a session sets `Session.revoked = true`; the backend rejects that `jti` on the next request. |

#### Agent Database User

| Setting | Description |
|---|---|
| Rotate writer password | Changes `opspilot_writer` PostgreSQL password. OpsPilot then iterates over all active servers, re-deploys the Telegraf + Fluent Bit configs via SSH with the new password, and restarts agents. Servers where SSH re-deploy fails are flagged with an error — admin must re-deploy manually. There is a brief data gap (~5–30s) per server during agent restart. |

---

## 6. Non-Functional Requirements

| Requirement | Target |
|---|---|
| Real-time latency | Metric updates visible within 2s — in-process live bus triggers WebSocket push on new TimescaleDB rows (see §5.4.8) |
| Check reliability | Service checks run once per configured interval. A service is marked down after **2 consecutive failed intervals** — no within-interval retries. |
| Alert evaluation | Rolling 5-min average for metric alerts, evaluated every 30s. Auto-resolve after 2 consecutive clean evaluations. |
| Data retention | Metrics: 30 days raw / 1 year aggregated. Logs: 30 days. ServiceChecks: 90 days. Alerts: 90 days. |
| Concurrent servers | Support 10–50 servers without degradation |
| Security | AES-256 encryption for SSH keys + DB credentials. Write-only agent DB user. JWT httpOnly cookies. HTTPS enforced. |

---

## 7. Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Backend | Python 3.11 + FastAPI | Async support, rich libs for SSH/SSL/HTTP/SMTP |
| Real-time | WebSockets (FastAPI native) | Live metric push to browser |
| Scheduler | APScheduler (SQLAlchemy job store) | Background jobs: service checks, SSL, domain, cron watchdog, alert evaluator, auto-resolver, maintenance-expiry. SQLAlchemy job store persists scheduled jobs to PostgreSQL — jobs survive backend restarts without re-registration. |
| SSH | Paramiko | Agent onboarding only — installs and configures Telegraf + Fluent Bit on new servers |
| Database | PostgreSQL + TimescaleDB extension | Relational data + time-series hypertables |
| ORM | SQLAlchemy + Alembic | Migrations, models |
| Cron parser | `croniter` (Python) | Parse cron expressions for next-expected-at calculation |
| Frontend | Vue 3 + Vite + Pinia | Reactive UI, state management |
| UI Template | Vuestic Admin (open source) | Dark dashboard, 150+ components |
| UI Components | Vuestic UI | Buttons, tables, badges, modals, forms |
| CSS | Tailwind CSS + Vuestic theme | Design tokens |
| Charts | ApexCharts (via VaChart) | Area, line, bar, gauge, donut, heatmap |
| Email | SMTP (configurable) | Alert delivery |
| Auth | Custom JWT (httpOnly cookie) | Session management |
| Metrics agent | Telegraf | Pushes server metrics to TimescaleDB every 10s |
| Log agent | Fluent Bit | Ships structured logs to TimescaleDB (JSONB) |
| WHOIS | `python-whois` | Domain registration expiry lookups — covers common TLDs; lookup result is cached per domain until next daily check |
| SSL check | Python `ssl` module + `cryptography` | Retrieve and parse SSL certificate metadata (expiry date, issuer) via direct socket connection to the target host |
| Deployment | Docker + Docker Compose | Self-hosted |

---

## 8. Project Structure

```
opspilot/
├── backend/
│   ├── app/
│   │   ├── api/             # REST + WebSocket routes (incl. /ping/{uuid} heartbeat endpoint)
│   │   ├── collectors/      # http_probe, ssl_checker, tcp_probe, domain_whois
│   │   ├── onboarding/      # SSH deploy: install Telegraf + Fluent Bit, push configs
│   │   ├── scheduler/       # APScheduler: service checks, SSL, domain, cron watchdog,
│   │   │                    #              agent-offline detector, alert evaluator,
│   │   │                    #              auto-resolver, maintenance-expiry
│   │   ├── alerting/        # Email alert engine (metric + log + heartbeat alerts)
│   │   ├── models/          # SQLAlchemy models
│   │   ├── schemas/         # Pydantic schemas
│   │   └── core/            # Config, auth, DB session, encryption
│   ├── alembic/             # DB migrations (creates hypertables, runs before port 5432 exposed)
│   └── main.py
├── frontend/
│   ├── src/
│   │   ├── views/           # Overview, Server, Service, Logs, SSL, Domain,
│   │   │                    # Database, CronBackup, Alerts, Settings, Status
│   │   ├── components/      # Charts, StatusBadge, MetricCard, LogViewer, AlertRow
│   │   └── stores/          # Pinia: servers, metrics, logs, alerts, ws
│   └── vite.config.js
├── agents/
│   ├── telegraf/
│   │   └── telegraf.conf.tmpl    # Jinja2 template — filled at onboarding time
│   └── fluent-bit/
│       ├── fluent-bit.conf.tmpl  # Jinja2 template — filled at onboarding time
│       └── parsers.conf          # Grok parsers for nginx, php, mariadb
├── docker-compose.yml
└── PRD.md
```

---

## 9. Data Models (High Level)

**Relational (PostgreSQL):**

- **Organization**: id (UUID), name, slug (TEXT, unique — URL-safe identifier, locked after creation), description (nullable TEXT), created_at
- **User**: id (UUID), username, password_hash, role (TEXT: `'admin'`|`'member'`), email (nullable TEXT), invited_by (nullable FK → User), created_at
- **UserOrganization**: user_id (FK → User), org_id (FK → Organization), role (TEXT: `'operator'`|`'viewer'`), assigned_at, assigned_by (FK → User) — composite PK (user_id, org_id); Admin users have no entries here (global access); member users must have at least one entry to see any data
- **Invite**: id (UUID), email, org_id (FK → Organization), role (TEXT: `'operator'`|`'viewer'`), token (UUID — single-use, sent in invite link), invited_by (FK → User), created_at, expires_at (48h from created_at), accepted_at (nullable TIMESTAMPTZ — set when invite is used; NULL = pending)
- **Server**: id (UUID), org_id (FK → Organization), name, host, ssh_port, ssh_user, ssh_auth_type (TEXT: `'key'`|`'password'`), ssh_key_encrypted (nullable), ssh_password_encrypted (nullable), os_distro (TEXT, set at onboarding), kernel_version (TEXT, set at onboarding), tags, is_active, created_at
- **Service**: id, server_id, name, type (TEXT: `'http'`|`'tcp'`|`'db'`), url, port, expected_status, interval_sec, timeout_sec, is_active, is_public (BOOLEAN), consecutive_failures (INTEGER default 0 — incremented on each failed check, reset to 0 on success; alert fires at 2), ignore_ssl_errors (BOOLEAN default false — skips SSL validation on HTTPS probes), last_checked (nullable TIMESTAMPTZ — updated on every check result), last_status (nullable TEXT: `'up'`|`'down'`|`'timeout'` — denormalised from latest ServiceCheck for fast status display without querying the hypertable)
- **ServiceCheck** *(TimescaleDB hypertable, 90-day retention)*: time, service_id, status (TEXT: `'up'`|`'down'`|`'timeout'`), response_time_ms
- **Incident**: id, service_id, started_at, resolved_at, duration_sec, cause (TEXT: `'http_error'`|`'timeout'`|`'connection_refused'`|`'wrong_status_code'`)
- **Domain**: id, org_id (FK → Organization), domain, registrar, expiry_date, days_remaining (INTEGER — updated by the daily WHOIS job; computed as `expiry_date - today` and stored for alert evaluation speed; stale by at most 1 day), warn_days (default 60), critical_days (default 30), last_checked, status
- **SSLCert**: id, domain_id (FK → Domain), port, issuer, expiry_date, days_remaining (INTEGER — updated by daily SSL checker; computed as `expiry_date - today`; NULL when status is `unreachable`), warn_days (default 30), critical_days (default 7), last_checked, status (TEXT: `'valid'`|`'expiring_soon'`|`'critical'`|`'expired'`|`'unreachable'`)
- **Alert**: id, server_id (nullable FK → Server), service_id (nullable FK → Service), domain_id (nullable FK → Domain), ssl_cert_id (nullable FK → SSLCert), cron_job_id (nullable FK → CronJob), backup_job_id (nullable FK → BackupJob), type (TEXT: `'cpu'`|`'ram'`|`'disk'`|`'disk_inode'`|`'agent_offline'`|`'service_down'`|`'ssl_expiry'`|`'domain_expiry'`|`'cron_missing'`|`'backup_missing'`|`'backup_failure'`|`'backup_size_drop'`|`'db_connections'`|`'db_replication_lag'`|`'db_replication_stopped'`|`'db_deadlock'`|`'php_fatal'`|`'nginx_5xx'`|`'ssh_brute_force'`|`'mariadb_error'`|`'slow_query_spike'`|`'maintenance'`), severity (TEXT: `'warning'`|`'critical'` — set at fire time, see §5.13.1), message, sent_at, resolved_at, acknowledged_at, snoozed_until, state (TEXT: `'firing'`|`'acknowledged'`|`'snoozed'`|`'resolved'`), consecutive_clear_count (INTEGER DEFAULT 0 — incremented each time the evaluator finds the condition clear; alert auto-resolves when this reaches 2; persisted so backend restarts do not reset the count)
- **AlertRule**: id, server_id, metric, threshold, rolling_window_min, cooldown_min, last_fired_at (nullable TIMESTAMPTZ — updated when alert fires; evaluator checks `now() < last_fired_at + cooldown_min` to suppress repeat sends)
- **LogAlertRule**: id, server_id, source, pattern, severity, threshold (INTEGER — minimum matching log entries within window_sec to trigger alert), window_sec (INTEGER — look-back window for pattern matching), cooldown_min, last_fired_at (nullable TIMESTAMPTZ — same cooldown enforcement as AlertRule)
- **CronJob**: id, server_id, name, schedule (cron expression), grace_period_min, ping_token (UUID), last_ping_at, start_ping_at (nullable TIMESTAMPTZ — set on `?event=start`, cleared after end ping), last_duration_sec (nullable INTEGER — computed from start/end ping), status
- **CronJobRun**: id, cron_job_id (FK → CronJob), ran_at (TIMESTAMPTZ), duration_sec (nullable INTEGER), outcome (TEXT: `'success'`|`'missed'`) — one row written per completed end-ping (success) and per watchdog detection of an overdue job (missed); source data for the 30-day calendar heatmap chart
- **BackupJob**: id, server_id, name, schedule (cron expression), grace_period_min, ping_token (UUID), last_ping_at, last_size_bytes, previous_size_bytes (for 20% drop comparison), last_exit_code, last_status_text (TEXT — informational only, not evaluated), status (TEXT: `'healthy'`|`'late'`|`'missing'` — `healthy` = last ping received within schedule + grace period; `late` = past expected time but within grace period; `missing` = past grace period, alert fires)
- **BackupRun**: id, backup_job_id (FK → BackupJob), ran_at (TIMESTAMPTZ), size_bytes (nullable BIGINT), exit_code (nullable INTEGER), outcome (TEXT: `'success'`|`'missed'`|`'failed'`) — one row written per ping received and per watchdog-detected miss; source data for the 30-day calendar heatmap chart
- **MaintenanceWindow**: id, server_id, started_at, ends_at, reason, is_active
- **DBCredential**: id, server_id, host, port, username, password_encrypted, is_replica (BOOLEAN), last_deadlock_count (nullable INTEGER — stores the `innodb_deadlocks` value from the last evaluation; alert fires when current value > this; updated after each evaluation)
- **Settings**: key (PK), value (TEXT) — sensitive values (SMTP password, encryption key) stored AES-256 encrypted; non-sensitive values (instance name, base URL) stored as plain text. Backend identifies sensitive keys by name.
- **Session**: id (UUID), jti (UUID — matches JWT `jti` claim, unique), issued_at, expires_at, revoked (BOOLEAN default false), ip_address (TEXT), user_agent (TEXT) — backend checks `jti` against this table and rejects revoked or expired entries on every authenticated request. An APScheduler nightly cleanup job deletes rows where `expires_at < now()` to prevent unbounded growth.
- **OnboardingLog**: id, server_id, step, status, message, timestamp

**Time-Series (TimescaleDB hypertables):**

- **server_metrics**: time, server_id, metric_name, value (DOUBLE PRECISION, nullable), labels (JSONB) — 30-day raw / 1-year aggregate  
  *Index:* `(server_id, metric_name, time DESC)`  
  *Process snapshots:* stored with `metric_name = 'top_processes'`, `value = NULL`, `labels = {"top_cpu": [...], "top_mem": [...]}`
- **server_metrics_hourly** *(continuous aggregate)*: 1h averages — retained 1 year
- **server_metrics_daily** *(continuous aggregate)*: 24h averages — retained 1 year
- **server_logs**: time, server_id, source, severity, message, fields (JSONB) — 30-day retention  
  *Indexes:* `(server_id, source, time DESC)`, `(server_id, severity, time DESC)`, tsvector on `message`
- **service_checks** *(hypertable)*: time, service_id, status (TEXT: `'up'`|`'down'`|`'timeout'`), response_time_ms — 90-day retention

---

## 10. Milestones

| Phase | Scope |
|---|---|
| Phase 1 | Project setup, Docker Compose (with migrate service), PostgreSQL + TimescaleDB schema (Alembic), auth (with env-var bootstrap), server CRUD, auto-onboarding SSH flow (installs Telegraf + Fluent Bit — both agents running and pushing data from day one) |
| Phase 2 | WebSocket live dashboard, historical metric charts (ApexCharts), server overview page |
| Phase 3 | Backend reads `server_logs` hypertable, Log Viewer UI (search, filter by source/severity, WebSocket live tail, expandable JSONB rows) |
| Phase 4 | Service monitoring (HTTP/TCP probes, ServiceCheck hypertable, Incident model, uptime timeline chart) |
| Phase 5 | SSL cert monitoring + Domain expiry monitoring (WHOIS with staggered checks), combined SSL/Domain table UI |
| Phase 6 | Database deep monitoring (Telegraf inputs.mysql, DB health charts, replication status, auto-re-deploy on credential save) |
| Phase 7 | Cron job monitoring + Backup monitoring (heartbeat ping endpoint, calendar heatmap UI) |
| Phase 8 | Full alerting engine: metric rolling-average evaluator, log pattern evaluator, auto-resolve logic, email delivery, alert ack/snooze, maintenance mode |
| Phase 9 | Public status page (`/status` — unauthenticated, `is_public` per service) |
| Phase 10 | Settings page (SMTP, identity, retention + TimescaleDB policy update, password, agent DB password rotation) |
| Phase 11 | Docker packaging, deployment runbook (migrate-first pattern, firewall setup), Telegraf + Fluent Bit config template documentation |

---

## 11. Decisions Log

| Decision | Choice |
|---|---|
| Alert threshold scope | Per-server only — no global defaults |
| SSH key storage | AES-256 encrypted in PostgreSQL |
| SSH auth type | Key or password — both supported; Server model has `ssh_auth_type` + two nullable encrypted fields |
| SSH user requirement | Must have sudo — stated in server form and docs |
| Metrics storage | TimescaleDB hypertable — 30-day raw, 1-year aggregates (hourly + daily) |
| server_metrics index | `(server_id, metric_name, time DESC)` — required for rolling average query performance |
| Metric alert evaluation | Rolling 5-min average — not instantaneous value |
| Alert auto-resolve | 2 consecutive clean evaluations → state = resolved, email sent |
| Server offline detection | 2-min metric gap in TimescaleDB (not SSH ping) |
| Server deletion | Soft delete — data retained until natural expiry, agents not uninstalled |
| os_distro / kernel_version | Stored on Server model (not server_metrics) — string values, collected once at onboarding |
| Top Processes storage | `metric_name = 'top_processes'`, `value = NULL`, JSON in `labels` JSONB |
| ServiceCheck storage | TimescaleDB hypertable (90-day retention) — prevents unbounded table growth |
| ServiceCheck status type | TEXT enum: `'up'` / `'down'` / `'timeout'` |
| Service down definition | 2 consecutive failed check intervals (not within-interval retries) |
| Incident creation trigger | Created on 2nd consecutive failed check (same evaluation that fires the alert) |
| Incident cause field | Populated from failure reason: `http_error`, `timeout`, `connection_refused`, `wrong_status_code` |
| SSLCert ↔ Domain link | SSLCert.domain_id FK → Domain — always co-located, no orphaned records |
| SSL/Domain alert thresholds | Per-record configurable — `warn_days` + `critical_days` fields on SSLCert and Domain models |
| Service public visibility | `is_public` boolean on Service model — controls public status page |
| Alert model FKs | Alert has nullable `server_id`, `service_id`, `domain_id`, `cron_job_id`, `backup_job_id` — at most one non-null per alert |
| Alert state machine | Added `snoozed → resolved` path: condition clearing during snooze resolves alert, not re-fires |
| Alert cooldown for non-metric alerts | Hardcoded 1h in evaluator for service/SSL/domain/cron/backup alerts (no AlertRule entry needed) |
| Log collection agent | Fluent Bit — lightweight C agent, native PostgreSQL/JSONB output |
| Log sources | System, auth, Nginx, PHP-FPM, PHP app, MariaDB error + slow query |
| Log storage | TimescaleDB hypertable `server_logs` — 30-day, tsvector full-text search |
| Log alert evaluation | SQL pattern match on `server_logs` every 60s |
| Log live tail | WebSocket (in-process live bus) — not polling |
| PHP app log path | Defaults to `/var/log/php_errors.log`; overridable per server via UI post-onboarding |
| MariaDB slow query log | Auto-enabled by onboarding script — no manual step |
| Log path distro differences | Onboarding detects OS — sets correct paths per distro |
| DB deep monitoring | Telegraf inputs.mysql with read-only monitoring user |
| DB credentials re-deploy | Saving DB credentials triggers automatic Telegraf re-deploy via SSH |
| Replication monitoring | Opt-in via `is_replica` flag on DBCredential — replication alerts suppressed if not replica |
| Cron/backup monitoring | Heartbeat ping (UUID token) — unauthenticated by design |
| Cron expression parser | Python `croniter` library |
| Backup previous size | `BackupJob.previous_size_bytes` — stored explicitly for 20% drop comparison |
| Domain expiry | WHOIS daily — staggered (30s between checks) to avoid rate-limiting |
| Maintenance mode | Per-server — suppresses alerts, collection continues; auto-expiry via APScheduler (60s tick) |
| Maintenance audit trail | Start/end events written to Alert table with `type = 'maintenance'` |
| Alert ack/snooze | Ack stops repeat emails; snooze pauses then re-fires (or resolves if condition clears) |
| WebSocket push | In-process live bus, 500ms batched — no polling, <2s latency (see §5.4.8) |
| Alembic migration ordering | `migrate` one-shot service runs before backend; port 5432 firewall + deploy runbook ensures no agent connects before migrations complete |
| Agent DB user | `opspilot_writer` — INSERT-only on hypertables |
| Settings encryption | `value TEXT` column — backend encrypts sensitive values (SMTP password, keys) before storage; non-sensitive values stored plain |
| Retention setting update | Changing retention in Settings updates TimescaleDB retention policy immediately |
| Admin bootstrap | Web-based `/setup` page on first install — admin registers username + password via UI; no env vars required; `/setup` becomes inaccessible once account exists |
| Multi-user access | Supported in v1 — Admin / Operator / Viewer roles; additional accounts via email invite only; no self-registration |
| Role enforcement | Backend enforces on every API request; frontend hides controls as convenience only |
| Invite flow | UUID token, 48h expiry, single-use; invitee sets own username + password; auto-logged in after accepting |
| Invite roles | Admin can only invite Operator or Viewer — cannot create another Admin via invite |
| Organization model | Top-level namespace for servers and domains; slug locked after creation; delete blocked if resources exist |
| Per-org team scoping | Operator/Viewer roles are per-org via UserOrganization junction table; Admin is global with no junction entries |
| Domain org scope | Domain belongs to Organization directly (not via server) — a domain may span multiple servers or none |
| Org delete rule | Blocked if org has servers or domains — admin must remove resources first |
| User.role values | `'admin'` (global) or `'member'` (per-org role in UserOrganization) |
| Org switcher | Persistent in sidebar; Admin sees all orgs + aggregate view; Members see assigned orgs only |
| Phase 1 vs Phase 3 agents | Phase 1: agents installed + pushing. Phase 3: Log Viewer UI reads buffered data |
| External uptime check | Deferred to v2 |
| Docker monitoring | Deferred — no Docker in current environment |
| OpsPilot hosting | Dedicated separate server |
| Server onboarding | Auto-deploy via SSH |
| Port 5432 firewall | Restricted to monitored server IPs only |
| UI template | Vuestic Admin — Vue 3 + Pinia + ApexCharts |
| Chart library | ApexCharts via VaChart wrapper |
| Default theme | Dark mode |
| Public status page | `/status` — unauthenticated, `is_public` per service |
| Settings page | SMTP, identity, retention, password change, agent DB password rotation (with SSH error flagging) |
| Docker Compose Nginx | Two-Nginx architecture: frontend container serves static files, outer nginx handles TLS + reverse proxy |
| AES-256 encryption key | Provided via `OPSPILOT_ENCRYPTION_KEY` env var (base64-encoded 32 bytes). Never stored in DB. Startup aborts if absent. Loss = permanent data unrecoverable. |
| WebSocket authentication | Short-lived one-time ticket from `GET /api/ws-ticket` (JWT-authenticated REST call) passed as query param on WS upgrade — avoids JWT in server logs, invalidated immediately after use |
| APScheduler job store | SQLAlchemy job store (PostgreSQL) — persists jobs across backend restarts; in-memory store would drop all scheduled checks on restart |
| MariaDB monitoring user | Admin creates manually before entering credentials in OpsPilot — OpsPilot has no privileged MariaDB connection to do it automatically |
| Session revocation | `Session` table with `jti` + `revoked` flag — checked on every authenticated request. JWTs alone are stateless and cannot be revoked without this. |
| JWT expiry | 24 hours — no silent refresh; frontend redirects to login on 401 |
| OPSPILOT_JWT_SECRET | Required env var for JWT signing — startup aborts if absent; changing it invalidates all active sessions |
| Session table cleanup | Nightly APScheduler job deletes rows where `expires_at < now()` |
| Consecutive failure tracking | `Service.consecutive_failures` INTEGER column — written to DB in same transaction as ServiceCheck row; restart-safe |
| AlertRule auto-creation | Backend auto-creates AlertRule rows with default thresholds when a server is successfully onboarded |
| Alert.type values | 22 defined TEXT values — see data models section 9 |
| LogAlertRule cooldown | `last_fired_at` TIMESTAMPTZ on both `AlertRule` and `LogAlertRule` — evaluator checks `now() < last_fired_at + cooldown_min` before sending |
| Two-ping mode | `?event=start` sets `start_ping_at`; `?event=end` or no param sets `last_ping_at` and computes `last_duration_sec`; start ping does not trigger watchdog |
| Backup ping precedence | `exit_code` is authoritative; `status` field is informational only (stored as `last_status_text`, not evaluated) |
| acknowledged → snoozed | State machine allows snoozing an already-acknowledged alert |
| HTTP SSL validation | Enabled by default; per-service `ignore_ssl_errors` boolean disables for self-signed cert use cases |
| Continuous aggregates filter | Aggregate policies must exclude `metric_name = 'top_processes'` (NULL value rows with no numeric meaning) |
| Live fan-out channels | Per-server channels `server_metrics:{server_id}` and `server_logs:{server_id}` via the in-process live bus; backend buffers events 500ms before WebSocket push; frontend subscribes/unsubscribes per viewed server or org (see §5.4.8) |
| WHOIS library | `python-whois` |
| SSL check library | Python `ssl` module + `cryptography` |
| SSH sudo requirement | NOPASSWD required — onboarding runs sudo non-interactively; password-prompted sudo hangs silently |
| net_errors display | Cumulative counters displayed as delta-per-interval (rate); Telegraf `inputs.net` computes this automatically |
| SSL check interval | Hardcoded daily in v1 — not per-cert configurable |
| SSLCert.status values | `valid` / `expiring_soon` / `critical` / `expired` / `unreachable` — unreachable = port 443 refused/timeout, not an expiry alert |
| Alert.severity | `warning` or `critical` set at fire time — SSL/domain warn threshold = warning, critical threshold = critical; all others = critical |
| LogAlertRule auto-creation | 5 default LogAlertRule rows created at server onboarding (same event as AlertRule auto-creation) |
| Onboarding vendor repos | Step 1b adds InfluxData (Telegraf) and Chronosphere (Fluent Bit) repos before apt/yum install |
| CronJobRun history | Separate `CronJobRun` table — one row per success or missed run; source for calendar heatmap |
| innodb_deadlocks tracking | `DBCredential.last_deadlock_count` stores previous cumulative value; evaluator compares on each tick |
| table_locks_waited threshold | Rate > 10 new lock waits/min (rolling 5-min avg), configurable via AlertRule |
| aborted_connections threshold | Rate > 5 new aborted connections/min (rolling 5-min avg), configurable via AlertRule |
| innodb_buffer_pool_hit_rate | Rolling 5-min average < 90% (not "sustained" — same evaluation window as other metric alerts) |
| Service.last_checked / last_status | Denormalised cache fields on Service — updated per check; avoids hypertable query on every page load |
| Log query pagination | Cursor-based, max 500 rows per request |
| Backup first run | Size-drop check skipped when `previous_size_bytes` is NULL (first run); `previous_size_bytes` updated after each successful run |
| Domain.days_remaining | Stored INTEGER, updated by daily WHOIS job — stale by at most 1 day, acceptable for alert evaluation |
| Snoozed alert evaluation | Evaluator checks `firing`, `acknowledged`, AND `snoozed` states — condition still evaluated during snooze; no email sent while snoozed; resolves if condition clears; re-fires if snooze expires with condition still present |
| BackupRun history table | Separate `BackupRun` table (mirrors `CronJobRun` pattern) — one row per ping and per watchdog miss; source for backup calendar heatmap |
| BackupJob.status enum | `'healthy'`|`'late'`|`'missing'` — mirrors CronJob status semantics; `late` = within grace period, `missing` = grace period exceeded (alert fires) |
| LogAlertRule defaults | 5 default rules created at onboarding with explicit `threshold` + `window_sec` fields; SSH brute-force evaluated per source IP |
| LogAlertRule.threshold / window_sec | Added to LogAlertRule model — `threshold INT` = count of matching entries required; `window_sec INT` = look-back window; evaluator uses these instead of hardcoded values |
| OPSPILOT_WRITER_PASSWORD env var | Added to required env vars — password for `opspilot_writer` INSERT-only user; used by Alembic to create the user and by backend to embed in Telegraf/Fluent Bit configs at onboarding |
| SSLCert.days_remaining | Stored INTEGER, updated by daily SSL checker — NULL when unreachable; mirrors Domain.days_remaining pattern |
| Alert.ssl_cert_id | Nullable FK → SSLCert added to Alert — required for `ssl_expiry` alert type linkage; at most one of server_id / service_id / domain_id / ssl_cert_id / cron_job_id / backup_job_id is non-null per alert |
| CronJob status timing | `healthy` = before next_expected_at; `late` = after next_expected_at but within grace period; `missing` = after grace period (alert fires); next_expected_at computed fresh each tick via croniter, not persisted |
