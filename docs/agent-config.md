# OpsPilot Agent Configuration Templates

OpsPilot auto-deploys two agents to every monitored server during onboarding:

| Agent | Role | Config rendered from |
|---|---|---|
| **Telegraf** | Metrics collection → TimescaleDB | `telegraf.conf.j2` |
| **Fluent Bit** | Log collection → TimescaleDB | `fluent-bit.conf.j2` + `fluent-bit-parsers.conf.j2` |

Templates live in `backend/app/services/templates/` and are rendered by `backend/app/services/onboarding.py` using Jinja2. The rendered configs are written to the target server and the agents are restarted — no manual SSH step required.

---

## Template Variables

### Common (both agents)

| Variable | Source | Description |
|---|---|---|
| `server_id` | `Server.id` | UUID of the monitored server — tagged on every metric and log record |
| `server_name` | `Server.name` | Human-readable name tagged on metrics |
| `ingestion_token` | `Server.ingestion_token` | Bearer token for `/api/ingest/metrics` and `/api/ingest/logs` |
| `ingest_url` | `Settings.base_url` or request host | Full URL of the OpsPilot backend, e.g. `https://monitor.example.com` |

### Fluent Bit only

| Variable | Source | Description |
|---|---|---|
| `ingest_host` | Parsed from `ingest_url` | Hostname passed to Fluent Bit HTTP output |
| `ingest_port` | Parsed from `ingest_url` | Port (443 for HTTPS) |
| `ingest_tls` | Derived from scheme | `On` if HTTPS, `Off` if HTTP |
| `syslog_path` | Auto-detected on server | Path to syslog (`/var/log/syslog` or `/var/log/messages`) |
| `auth_log_path` | Auto-detected on server | Path to auth log (`/var/log/auth.log` or `/var/log/secure`) |
| `mariadb_error_path` | Auto-detected on server | Path to MariaDB error log |
| `mariadb_slow_path` | Auto-detected on server | Path to MariaDB slow query log |

### Telegraf DB instances (optional)

`db_instances` is a list of objects, one per configured database credential:

| Field | Description |
|---|---|
| `label` | Human-readable name shown in dashboards |
| `dsn` | Connection string for the `inputs.mysql` or `inputs.postgresql` plugin |
| `db_type` | `mysql` or `postgres` |

When `db_instances` is empty, no database input blocks are rendered. The Telegraf config is **automatically re-deployed** whenever DB credentials are saved or updated — the backend SSHes in, re-renders the config, and restarts Telegraf.

---

## Telegraf — What It Collects

| Plugin | Metrics | Interval |
|---|---|---|
| `inputs.cpu` | Total CPU (user, system, iowait, idle) | 10s |
| `inputs.cpu` (per-core) | `usage_active` per core | 10s |
| `inputs.mem` | Used %, available %, swap | 10s |
| `inputs.disk` | Used % per filesystem (tmpfs excluded) | 10s |
| `inputs.diskio` | Read/write bytes and ops per device | 10s |
| `inputs.net` | Bytes/packets in+out per interface | 10s |
| `inputs.system` | Load average (1m, 5m, 15m), uptime | 10s |
| `inputs.processes` | Total, running, sleeping, zombie counts | 10s |
| `inputs.swap` | Swap used % | 10s |
| `inputs.kernel` | Kernel boot time | 10s |
| `inputs.linux_sysctl_fs` | File descriptor counts | 10s |
| `inputs.systemd_units` | Health of `telegraf.service` and `fluent-bit.service` | 10s |
| `inputs.exec` (proctop) | Top 10 processes by CPU + top 10 by memory | 30s |
| `inputs.mysql` | Connections, queries/sec, slow queries, replication lag, deadlocks | 10s |
| `inputs.postgresql` | Connections, transactions, buffer hit ratio | 10s |

All metrics are pushed to `/api/ingest/metrics` using InfluxDB Line Protocol over HTTPS, compressed with gzip.

---

## Fluent Bit — What It Collects

| Tag | Source file | Description |
|---|---|---|
| `syslog` | `/var/log/syslog` or `/var/log/messages` | System log |
| `auth` | `/var/log/auth.log` or `/var/log/secure` | SSH logins, sudo, PAM events |
| `nginx_access` | `/var/log/nginx/access.log` | HTTP access log |
| `nginx_error` | `/var/log/nginx/error.log` | Nginx errors |
| `php_fpm` | `/var/log/php-fpm/*.log` | PHP-FPM pool logs |
| `php_app` | `/var/log/php_errors.log` | PHP application errors |
| `mariadb_error` | MariaDB error log | Database errors and warnings |
| `mariadb_slow` | MariaDB slow query log | Slow queries (multiline, grouped per query) |

Every record is tagged with `server_id` and `source` (the input tag) before being sent to `/api/ingest/logs` as JSON over HTTPS.

### Multiline handling

MariaDB slow query log entries span multiple lines (each query has a header line, query stats, and the SQL statement). The `mariadb_slow` multiline parser in `fluent-bit-parsers.conf.j2` groups them into a single Fluent Bit record so the Log Viewer shows one entry per slow query.

---

## Re-deploying Agents Manually

From the server detail page → **⋮ menu → Re-deploy agents**. This re-renders both configs and restarts both agents over SSH. Use this after changing the base URL, rotating the writer password, or troubleshooting a broken config.
