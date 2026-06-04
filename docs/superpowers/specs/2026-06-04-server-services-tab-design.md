# Server Services Tab — Design Spec
**Date:** 2026-06-04
**Status:** Approved

## Overview

Add a **Services** tab to the server detail page. The OpsPilot agent auto-discovers a curated list of well-known services on each server, collects status + resource metrics per heartbeat, and stores them as time-series in TimescaleDB for both live display and future analysis/reporting.

This is distinct from the existing sidebar "Services" feature, which is manual HTTP/TCP uptime monitoring. This feature collects real process-level data from the server.

---

## Data Model

New TimescaleDB hypertable: `server_service_metrics`

| Column | Type | Notes |
|---|---|---|
| `time` | TIMESTAMPTZ | partition key |
| `server_id` | UUID | FK → servers |
| `service_name` | TEXT | canonical name, e.g. `nginx` |
| `status` | TEXT | `running` / `stopped` / `not_installed` |
| `cpu_pct` | FLOAT | % CPU used by the process (null if not running) |
| `mem_mb` | FLOAT | RSS memory in MB (null if not running) |
| `uptime_seconds` | INTEGER | seconds since process started (null if not running) |

Snapshot query: `DISTINCT ON (service_name) ORDER BY service_name, time DESC` — no extra table needed.

Future analysis enabled by this schema:
- CPU/mem spike detection and time-window queries
- Status uptime % calculations
- Correlation with server-level metrics and logs for root-cause analysis
- Weekly/monthly service health reports via TimescaleDB `time_bucket()`

---

## Curated Service List

| Canonical Name | Systemd Unit Aliases |
|---|---|
| apache | `apache2`, `httpd` |
| nginx | `nginx` |
| mysql | `mysql`, `mysqld`, `mariadb` |
| php-fpm | `php-fpm`, `php8.1-fpm`, `php8.2-fpm`, `php7.4-fpm` |
| postgresql | `postgresql`, `postgres` |
| redis | `redis`, `redis-server` |
| mongodb | `mongod` |
| nodejs | `node`, `nodejs` |
| docker | `docker` |

---

## Agent Changes

- New `collect_services()` function runs on every heartbeat cycle
- For each canonical service, try each alias with `systemctl is-active <name>`
  - First alias that returns `active` → status = `running`
  - Unit found but inactive → status = `stopped`
  - No alias found → status = `not_installed`
- If `running`: find process via `psutil.process_iter()`, collect `cpu_percent()`, `memory_info().rss`, and uptime from `create_time`
- Append `services: [...]` array to existing heartbeat payload — no new HTTP call
- Old agents without the field are backwards compatible (field is optional)

---

## Backend Changes

### Ingest (`POST /api/ingest/heartbeat`)
- Accept optional `services` array in existing payload schema (Pydantic model extension)
- Bulk insert into `server_service_metrics` on each heartbeat
- Silently skip if field absent (backwards compatibility)

### New Endpoint
`GET /api/servers/{id}/services`
- Auth: existing server auth (org membership check)
- Returns latest snapshot per service using `DISTINCT ON`
- Response shape:
```json
[
  { "name": "nginx", "status": "running", "cpu_pct": 1.2, "mem_mb": 48.3, "uptime_seconds": 432000 },
  { "name": "mysql", "status": "stopped", "cpu_pct": null, "mem_mb": null, "uptime_seconds": null }
]
```
- Accepts optional `?include_not_installed=true` query param
- By default filters out `not_installed` rows; toggle passes the param to show all 9 checked services

### Migration
- One Alembic migration: create `server_service_metrics` table + `create_hypertable()` call
- Index on `(server_id, service_name, time DESC)` for snapshot query performance

---

## Frontend Changes

### ServerDetail.vue
- Add `Services` to `TABS` array
- Add `ServicesTab` to `TAB_COMPONENTS` map

### ServicesTab.vue (new)
- Location: `frontend/src/components/servers/tabs/ServicesTab.vue`
- Fetches on mount via `GET /api/servers/{id}/services`
- Refreshes when server `last_seen` updates (existing WS push)
- No new Pinia store — `ref([])` + fetch inside component (same pattern as ProcessesTab)

**Table columns:**
| Column | Content |
|---|---|
| Service | Canonical name |
| Status | `StatusBadge` — green `running`, red `stopped`, grey `not installed` |
| CPU | `1.2%` or `—` if stopped |
| Memory | `48 MB` or `—` if stopped |
| Uptime | `3d 2h` formatted or `—` if stopped |

**States:**
- Loading skeleton while fetching
- Toggle to show/hide `not_installed` services (hidden by default)
- Empty state: "No service data — make sure your agent is up to date" if no rows returned

---

## Out of Scope (Future)
- Service-specific deep metrics (MySQL connections, PostgreSQL pg_stat_activity, Redis ops/sec)
- Status change alerts triggered from service status
- Historical trend charts per service (data is stored, UI deferred)
