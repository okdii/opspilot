# Spec: Server Logs Tab + Log Intelligence Page

**Date:** 2026-06-04
**Status:** Approved

---

## Overview

Two related changes delivered in sequence:

1. **Part 1 — Server detail Logs tab**: Add a "Logs" tab to the server detail page showing raw log entries scoped to that server.
2. **Part 2 — Log Intelligence page**: Redesign `/logs` from a raw log viewer into an org-wide log intelligence summary showing what needs attention.

**Flow:** User sees something suspicious on `/logs` → clicks server → goes to Logs tab → digs into actual entries.

---

## Part 1: Server Detail Logs Tab

### Component

- New file: `frontend/src/components/servers/tabs/LogsTab.vue`
- Added to `TABS` constant in `ServerDetail.vue` after `Alerts`: `[..., 'Services', 'Alerts', 'Logs']`
- Added to `TAB_COMPONENTS` map: `Logs: LogsTab`

### Server ID

Reads `metrics.activeServerId` from `useMetricsStore` — same pattern as `AlertsTab`. No prop needed; the store already holds the active server ID when any tab mounts.

### Layout (top to bottom)

1. **Filter bar**
   - Source dropdown: all 9 sources pre-selected (syslog, auth, kernel, nginx_access, nginx_error, php_fpm, php_app, mariadb_error, mariadb_slow). Only shows sources that have entries for this server.
   - Severity chips: Debug, Info, Warn, Error, Fatal (all active by default)
   - Search input (min 2 chars, 300ms debounce)
   - Time range picker: 15m, 1h (default), 6h, 24h, 7d

2. **Sub-bar**
   - Left: Live Tail toggle button (OFF by default)
   - Right: entry count label + "Clear filters" link (shown when filters active)

3. **Log table**
   - Columns: Time, Source, Sev, Message
   - No SERVER column (scoped to one server)
   - Expandable rows (click chevron) for full message detail
   - Newest entries at top

4. **Footer**
   - Infinite scroll: load more when scrolled to 80% of list
   - "500 entries loaded — narrow your filters" warning at limit
   - "Load more" button when next cursor available

### Data

- Reuses `useLogStore` — calls existing `/api/logs` endpoint with `server_id` pre-set
- No new backend endpoints required
- Live Tail: WebSocket subscription to `server_logs:{server_id}` channel

### Behaviour

- On tab mount: initialise store with `server_id`, fetch with default filters (last 1h, all sources, all severities)
- On tab unmount: stop live tail, reset store
- Source dropdown only shows sources that have at least one entry for this server in the selected time range

---

## Part 2: Log Intelligence Page (`/logs`)

### Overview

Replace the existing raw log viewer in `LogsView.vue` with an intelligence summary. No raw log table on this page. The page answers: *"Where should I look first?"*

### Time Range Control

Single selector (1h / 6h / 24h, default 24h) in the page header. Affects all panels except Recent Fatals (always last 10 regardless of range).

### Layout (top to bottom)

**1. Header summary bar**
One row showing org-wide severity counts for the selected time range:
`● Fatal: 2  ● Error: 47  ● Warn: 203  ● Info: 12,400`
Colored dots: Fatal=#991b1b, Error=#ef4444, Warn=#f59e0b, Info=#3b82f6.

**2. Intelligence card grid (2-column, responsive to 1-column on mobile)**

| Card | Content |
|------|---------|
| **Critical Errors** | Top recurring error/fatal messages deduplicated by text similarity, ranked by count. Shows message text + count badge + source. Max 8 entries. |
| **HTTP Errors** | From `nginx_access` source. Total 5xx count, total 4xx count, top 5 failing URLs with count. Hidden if no nginx_access data. |
| **Slow Queries** | From `mariadb_slow` source. Total slow query count, slowest query duration + truncated query text + server name. Hidden if no slow query data. |
| **Auth Events** | From `auth` source. Failed login count, top 5 source IPs with attempt count. Flags IPs with >10 failures. Hidden if no auth data. |

Cards that have no data for the selected range show a "No activity" empty state and are visually dimmed — not hidden, so the user knows they're being monitored.

**3. Per-server log health row**
One card per server in the org:
- Server name + status badge
- Error / Warn / Fatal counts for the selected range (colored)
- Mini bar sparkline (last 6 buckets, stacked by severity)
- Click → navigates to `/servers/{id}` with Logs tab active (via query param `?tab=Logs`)

**4. Recent Fatals**
Last 10 fatal-level entries across all servers, always visible regardless of time range.
Columns: Time, Server, Source, Message (truncated to 120 chars, expandable inline).
"No fatal events" empty state when clean.

**5. Log volume chart**
Stacked bar chart: severity × time buckets, org-wide. Uses existing `/api/logs/volume` endpoint. Collapsed by default on mobile.

### Backend: New Intelligence Endpoint

`GET /api/logs/intelligence`

Query params: `org_id` (required), `range` (15m / 1h / 6h / 24h, default 24h)

Response shape:
```json
{
  "summary": { "fatal": 2, "error": 47, "warn": 203, "info": 12400, "debug": 0 },
  "top_errors": [
    { "message": "Connection refused", "count": 23, "source": "syslog", "last_seen": "..." }
  ],
  "http_errors": {
    "total_5xx": 12, "total_4xx": 88,
    "top_urls": [{ "url": "/api/checkout", "count": 12, "status": 500 }]
  },
  "slow_queries": {
    "total": 5, "worst_duration_ms": 8420, "worst_query": "SELECT * FROM orders ...", "server_name": "lima-ubuntu"
  },
  "auth_events": {
    "failed_logins": 34,
    "top_ips": [{ "ip": "1.2.3.4", "count": 28 }]
  },
  "per_server": [
    { "server_id": "...", "server_name": "lima-ubuntu", "fatal": 1, "error": 12, "warn": 45, "sparkline": [0,2,5,1,3,1] }
  ],
  "recent_fatals": [
    { "id": "...", "time": "...", "server_name": "...", "source": "syslog", "message": "..." }
  ]
}
```

Implementation notes:
- All aggregations run as SQL queries against the `log_entries` TimescaleDB table
- `top_errors`: filter `severity IN ('error','fatal')`, group by normalized message (strip timestamps/IDs), ORDER BY count DESC LIMIT 8
- `http_errors`: filter `source = 'nginx_access'`, parse status code from message
- `slow_queries`: filter `source = 'mariadb_slow'`, parse duration from message
- `auth_events`: filter `source = 'auth'`, pattern match on "Failed password" / "authentication failure"
- `per_server`: GROUP BY server_id, COUNT per severity
- `recent_fatals`: filter `severity = 'fatal'` ORDER BY time DESC LIMIT 10

### Frontend Store

New `useLogIntelligenceStore` (Pinia):
- `fetch(orgId, range)` — calls `/api/logs/intelligence`
- State: `data`, `loading`, `error`
- Auto-refresh every 60 seconds when page is visible

### Navigation Deep-link

Per-server card click navigates to `/servers/{id}?tab=Logs`. `ServerDetail.vue` reads `?tab` query param on mount and sets `activeTab` accordingly.

---

## Shared Considerations

- **No raw log table on `/logs`** — users who need raw logs go to the server detail Logs tab
- **Component reuse**: `LogsTab.vue` reuses `useLogStore`, `LogRow.vue`, `MetricChart.vue` — no new primitives needed
- **Empty org state**: both pages show "Select an organization" when no org is active
- **Mobile**: card grid collapses to 1-column, chart hidden by default

---

## Delivery Order

1. `LogsTab.vue` + wire into `ServerDetail.vue` (no backend changes)
2. Deep-link `?tab=Logs` support in `ServerDetail.vue`
3. `GET /api/logs/intelligence` backend endpoint
4. `useLogIntelligenceStore` + redesigned `LogsView.vue`
