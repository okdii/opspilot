# Module Spec 05 — Log Viewer

**Version:** 1.0  
**Date:** 2026-06-01  
**PRD Reference:** §5.7  
**Status:** Ready for Development

---

## 1. Overview

The Log Viewer provides a searchable, filterable, real-time view of all logs collected by Fluent Bit across all servers in the active organization. Logs are stored in the `server_logs` TimescaleDB hypertable (30-day retention) and accessible via REST (historical) and WebSocket (live tail).

**Screen:** `/logs`  
**Access:** All roles (data scoped to active org)

---

## 2. Log Sources

Fluent Bit collects from these sources, each stored with a `source` label in `server_logs`:

| `source` value | What it captures |
|---|---|
| `nginx_access` | HTTP requests — method, URL, status code, response time, client IP |
| `nginx_error` | Nginx errors — severity, message, upstream |
| `php_fpm` | PHP-FPM process errors — pool, PID, message |
| `php_app` | PHP application errors — type, file, line, message |
| `mariadb_error` | MariaDB error log — severity, thread ID, message |
| `mariadb_slow` | Slow queries — query time, rows examined, query text |
| `syslog` | System journal — unit, priority, message |
| `auth` | Auth/SSH events — event type, user, source IP |
| `kernel` | Kernel messages — severity, subsystem, message |

---

## 3. Page Layout

```
┌────────────────────────────────────────────────────────────────────┐
│  Logs — Acme Corp                                                  │
├──────────┬───────────┬──────────────┬──────────────────┬──────────┤
│ Server ▾ │ Source ▾  │ Severity ▾   │ 🔍 Search logs.. │ Time ▾   │
├────────────────────────────────────────────────────────────────────┤
│  [Live Tail OFF]                          Showing 247 entries      │
├────────────────────────────────────────────────────────────────────┤
│  Log Volume                                                        │
│  [stacked bar chart — 300px height]                                │
├────────────────────────────────────────────────────────────────────┤
│  Time           Server   Source        Sev   Message               │
│  ─────────────────────────────────────────────────────────────     │
│  12:04:31.221   web-01   nginx_access  —     GET /api 502 0.8s    │
│  12:04:30.118   web-01   php_app       ERR   Fatal: Undef var..    │
│  12:04:28.009   db-01    mariadb_slow  —     Query 2.3s SELECT..   │
│  12:04:27.445   web-01   auth          WARN  Failed password: root │
│  ─────────────────────────────────────────────────────────────     │
│  [Load more — 253 remaining]                                       │
└────────────────────────────────────────────────────────────────────┘
```

The page is split into three vertical zones:
1. **Filter bar** — persistent top strip
2. **Volume chart** — collapsible (toggle with `[Hide chart]`)
3. **Log table** — takes remaining viewport height, virtualised scroll

---

## 4. Filter Bar

All filters apply simultaneously. Changes trigger a new API query (debounced 300ms for search input).

### 4.1 Server Filter

| State | What it shows |
|---|---|
| All servers (default) | Logs from all servers in active org; `Server` column visible in table |
| One server selected | Logs from that server only; `Server` column hidden |
| Multiple selected | Logs from selected servers; `Server` column visible |

Dropdown: checkboxes for each server in the active org. Each server shows its name + status dot.

### 4.2 Source Filter

Multi-select dropdown. Groups by category:

```
  System
    ☑ syslog
    ☑ auth
    ☑ kernel
  Web
    ☑ nginx_access
    ☑ nginx_error
  PHP
    ☑ php_fpm
    ☑ php_app
  Database
    ☑ mariadb_error
    ☑ mariadb_slow
```

Default: all sources selected. Deselecting a group header deselects all sources in that group.

### 4.3 Severity Filter

Multi-select chips (not a dropdown — always visible):

```
[ ● debug ]  [ ● info ]  [ ● warn ]  [ ● error ]  [ ● fatal ]
```

Active chips are filled; inactive are outlined. Default: all active.

Colour per severity:
| Severity | Colour |
|---|---|
| `debug` | Grey `#6b7280` |
| `info` | Blue `#3b82f6` |
| `warn` | Amber `#f59e0b` |
| `error` | Red `#ef4444` |
| `fatal` | Dark red `#991b1b` + bold |

Note: `nginx_access` entries have no severity (HTTP access is not an error/info — it is just a log). These entries are displayed with a `—` severity cell and are shown when the severity filter includes at least one active option. They cannot be filtered by severity.

### 4.4 Search Field

- Full-text search on the `message` column (PostgreSQL `tsvector` index)
- Input: text field, min 2 characters to trigger
- Search terms highlighted in yellow in matching rows
- Pressing `Escape` clears the field

### 4.5 Time Range

Dropdown with presets plus custom range:

| Option | From | To |
|---|---|---|
| Last 15 min | now - 15m | now |
| Last 1 hour (default) | now - 1h | now |
| Last 6 hours | now - 6h | now |
| Last 24 hours | now - 24h | now |
| Last 7 days | now - 7d | now |
| Custom | Date-time picker | Date-time picker |

When **Live Tail** is active: time range selector is disabled and shows `Live`.

### 4.6 Live Tail Toggle

```
[ ⏸ Live Tail ON ]   ← pulsing green dot when active
[ ▷ Live Tail OFF ]  ← grey when inactive
```

- **ON**: disables time range picker; new log entries arrive via WebSocket and are prepended to the top of the table; volume chart auto-extends right edge
- **OFF**: static query against the selected time range; no WebSocket subscription active

Live tail subscribes to `server_logs:{server_id}` for each selected server (or all org servers if no server filter).

---

## 5. Log Volume Chart

Stacked bar chart. Always shows the selected time range.

**X-axis bucket sizes:**
| Time range | Bucket size |
|---|---|
| 15m | 1 minute |
| 1h | 5 minutes |
| 6h | 15 minutes |
| 24h | 1 hour |
| 7d | 6 hours |

**Stacking layers (bottom to top):** debug → info → warn → error → fatal

Clicking a bar segment filters the table to that time bucket and that severity (sets custom time range + severity filter).

```
Count
 100 │       ██
  80 │      ███
  60 │   █  ███  █
  40 │   █  ███  █
  20 │ ███  ███  ██ █
   0 └──────────────────────────── time
       11:00  11:30  12:00  12:30
```

Chart is **collapsed by default on mobile**. On desktop, visible by default with a `[Hide chart ▲]` toggle.

---

## 6. Log Table

### 6.1 Columns

| Column | Width | Content |
|---|---|---|
| Time | 160px | `HH:MM:SS.mmm` for ranges ≤ 6h; `DD MMM HH:MM:SS` for longer ranges |
| Server | 100px | Server display name — **hidden when single server is selected** |
| Source | 120px | Coloured badge (see §6.3) |
| Severity | 70px | Coloured chip or `—` for access logs |
| Message | remaining | Truncated to 150 chars. Full text on hover (tooltip) or on row expand |

Default sort: `time DESC` (newest first). Sort is not user-changeable — logs are always chronological descending.

### 6.2 Virtualised Rendering

The table uses virtual scrolling — only the rows visible in the viewport are rendered in the DOM. This handles thousands of entries without performance issues.

- Row height: 40px (collapsed), auto (expanded)
- Viewport: full height minus header and filter bar
- Smooth scroll maintained during live tail (new rows prepended, scroll position preserved unless user is at the top)

### 6.3 Source Badges

| Source | Colour |
|---|---|
| `nginx_access` | Blue |
| `nginx_error` | Blue (darker) |
| `php_fpm` | Purple |
| `php_app` | Purple (darker) |
| `mariadb_error` | Orange |
| `mariadb_slow` | Orange (darker) |
| `syslog` | Grey |
| `auth` | Teal |
| `kernel` | Dark grey |

### 6.4 Row Expansion

Clicking a row expands it inline to show all parsed JSONB fields. Clicking again collapses it.

**Expanded row — layout:**

```
▼ 12:04:31.221   web-01   nginx_access   —   GET /api/users 502 0.823s
  ┌────────────────────────────────────────────────────────────────┐
  │  client_ip       192.168.1.100                                 │
  │  method          GET                                           │
  │  url             /api/users                                    │
  │  status_code     502                                           │
  │  response_size   1.2 KB                                        │
  │  response_time   823ms                                         │
  │  user_agent      Mozilla/5.0 (Macintosh; ...)                  │
  │  referrer        https://example.com/dashboard                 │
  │                                                                │
  │  [Copy as JSON]   [Filter to this source]   [Filter to this IP]│
  └────────────────────────────────────────────────────────────────┘
```

**Fields shown per source:**

| Source | Fields displayed from `fields` JSONB |
|---|---|
| `nginx_access` | client_ip, method, url, status_code, response_size (human-formatted), response_time_ms, user_agent, referrer |
| `nginx_error` | severity, message, upstream |
| `php_fpm` | severity, pool, pid, message |
| `php_app` | type (Notice/Warning/Fatal/Parse), file, line, message |
| `mariadb_error` | severity, thread_id, message |
| `mariadb_slow` | query_time, lock_time, rows_examined, rows_sent, user, host, db, query |
| `syslog` | unit, priority, message |
| `auth` | event, user, source_ip |
| `kernel` | severity, subsystem, message |

**Quick filter actions in expanded row:**
- `[Copy as JSON]` — copies the full log entry as formatted JSON to clipboard
- `[Filter to this source]` — sets Source filter to this log's source
- `[Filter to this IP]` — adds the client_ip / source_ip value as a search filter (for nginx_access and auth entries)

### 6.5 Slow Query Row — Special Display

`mariadb_slow` entries get special formatting in the expanded view because the query text is the most important field:

```
▼ 12:04:28.009   db-01   mariadb_slow   —   SELECT * FROM orders WHERE... (2.3s)
  ┌────────────────────────────────────────────────────────────────┐
  │  query_time      2.341s                                        │
  │  lock_time       0.002s                                        │
  │  rows_examined   48,291                                        │
  │  rows_sent       1                                             │
  │  user            app_user@localhost                            │
  │  db              shopdb                                        │
  │                                                                │
  │  Query:                                                        │
  │  ┌──────────────────────────────────────────────────────────┐  │
  │  │ SELECT * FROM orders WHERE customer_id = 12345 AND      │  │
  │  │ status NOT IN ('cancelled', 'refunded') ORDER BY        │  │
  │  │ created_at DESC                                          │  │
  │  └──────────────────────────────────────────────────────────┘  │
  │  [Copy Query]                                                  │
  └────────────────────────────────────────────────────────────────┘
```

Query is shown in a monospace code block with `[Copy Query]` button.

---

## 7. Pagination

Cursor-based pagination. API returns max 500 rows per request.

**On initial load:** First 100 rows loaded (default page size). A footer row shows:
```
Showing 100 entries — [ Load more — 147 remaining ]
```

**On scroll to bottom:** Next page automatically loads (infinite scroll trigger at 80% of table height). The `[Load more]` label updates to `[Loading...]` during fetch and disappears when all rows are loaded.

**When exactly 500 rows returned (page limit hit):**
```
Showing 500 entries (limit reached) — Narrow your filters to see more precise results.
```

No "load more" — the user must filter to get a smaller result set.

**Entry count line (above chart):**
```
Showing 247 entries    [Clear filters]   ← "Clear filters" only visible when filters active
```

---

## 8. Live Tail Mode

### 8.1 Activation

Toggle the `[Live Tail]` button. On activation:
1. Time range selector disables and shows `Live`
2. Existing table entries stay visible
3. Frontend subscribes to `server_logs:{server_id}` for each active server filter
4. New entries arrive via WebSocket push and are **prepended** to the top of the table

### 8.2 Auto-Scroll Behaviour

- If user is scrolled to the **top** of the table: new entries prepend and the view stays at the top (user sees latest entries)
- If user has **scrolled down** (reading older entries): new entries prepend silently — a banner appears:

```
┌──────────────────────────────────────────────────┐
│  ↑  24 new entries — Scroll to top to see them   │
└──────────────────────────────────────────────────┘
```

Clicking the banner scrolls to top. Count increments with each new entry batch.

### 8.3 Live Tail Visual Indicators

- New entries animate in with a brief highlight (100ms yellow fade) so the eye can catch fresh data
- The `[Live Tail ON]` toggle shows a pulsing green dot while connected
- If WebSocket drops: dot turns grey, banner: `"Live tail paused — reconnecting..."` (uses same reconnect flow as spec 01 §5.3)

### 8.4 Filters During Live Tail

All filters remain active during live tail — incoming entries are filtered client-side before being displayed. If an incoming log entry does not match the active server/source/severity/search filters, it is silently discarded.

---

## 9. Error Rate Trend Chart

Appears **below the log table** — only rendered when `error` or `fatal` severity is included in the filter and at least one error/fatal entry exists in the result set.

```
Errors/min
  8 │         █
  6 │         █    █
  4 │    █    █    █
  2 │    █    █    █   █
  0 └──────────────────────────────── time
      11:30  11:45  12:00  12:15
  ─ ─ ─ ─ threshold: 5/min (from LogAlertRule)
```

- Line chart: errors + fatals per minute on y-axis
- Dashed red threshold line from the most relevant `LogAlertRule` for the active server/source combination
- Hovering a data point shows: timestamp, error count, list of first 3 matching messages

---

## 10. PHP Log Path Override

Each server can have a custom PHP application error log path (default: `/var/log/php_errors.log`).

A subtle link appears above the log table when `php_app` source is selected and the active server has no PHP app logs:

```
⚠  No PHP app logs from web-01.
   The default path is /var/log/php_errors.log.
   [ Override log path → ]   ← opens server config panel
```

Clicking opens a small inline form:
```
PHP App Log Path
┌────────────────────────────────────────────────┐
│  /var/www/myapp/storage/logs/laravel.log       │
└────────────────────────────────────────────────┘
  [Save]  [Cancel]
```

On save: backend updates the Fluent Bit config on the server via SSH re-deploy (same as Re-deploy Agents in spec 03, steps 7–10).

---

## 11. API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/logs` | Required | Fetch log entries with filters |
| `GET` | `/api/logs/volume` | Required | Log volume per time bucket for chart |
| `PATCH` | `/api/servers/:id/php-log-path` | Admin | Update PHP app log path + re-deploy |

### GET /api/logs

**Query parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `org_id` | UUID | — | Required unless `server_id` provided |
| `server_ids` | UUID[] | all in org | Comma-separated server IDs |
| `sources` | string[] | all | Comma-separated source values |
| `severities` | string[] | all | Comma-separated severity values |
| `search` | string | — | Full-text search on `message` |
| `from` | ISO timestamp | now-1h | Start of time range |
| `to` | ISO timestamp | now | End of time range |
| `cursor` | string | — | Pagination cursor from previous response |
| `limit` | int | 100 | Max rows, capped at 500 |

**Response (200):**
```json
{
  "entries": [
    {
      "id": "uuid",
      "time": "2026-06-01T12:04:31.221Z",
      "server_id": "uuid",
      "server_name": "web-01",
      "source": "nginx_access",
      "severity": null,
      "message": "GET /api/users 502 0.823s",
      "fields": {
        "client_ip": "192.168.1.100",
        "method": "GET",
        "url": "/api/users",
        "status_code": 502,
        "response_size": 1234,
        "response_time_ms": 823,
        "user_agent": "Mozilla/5.0...",
        "referrer": "https://example.com"
      }
    }
  ],
  "next_cursor": "eyJ0aW1lIjoiMjAyNi0wNi0wMVQxMjowNDozMC4wMDBaIn0=",
  "count": 100,
  "limit_reached": false
}
```

`next_cursor` is `null` when no more entries exist. `limit_reached: true` when the 500-row cap was hit.

The cursor encodes the last returned row's `time` + `id` to allow stable pagination even as new entries arrive.

### GET /api/logs/volume

**Query parameters:** same filters as `GET /api/logs`, plus `bucket_seconds` (optional — auto-determined if omitted).

**Response (200):**
```json
{
  "buckets": [
    {
      "time": "2026-06-01T11:00:00Z",
      "debug": 0,
      "info": 45,
      "warn": 12,
      "error": 3,
      "fatal": 0
    }
  ],
  "bucket_seconds": 300
}
```

### PATCH /api/servers/:id/php-log-path

**Request body:**
```json
{ "php_log_path": "/var/www/myapp/storage/logs/laravel.log" }
```
**Response `200`:** `{ "ok": true }` — re-deploy is queued asynchronously.

---

## 12. WebSocket Events

Live tail uses the same WS connection as metric streaming. Channel: `server_logs:{server_id}`.

**Subscribe for live tail:**
```json
{ "action": "subscribe_logs", "server_id": "uuid" }
```

**Unsubscribe:**
```json
{ "action": "unsubscribe_logs", "server_id": "uuid" }
```

**Incoming push event:**
```json
{
  "channel": "server_logs:550e8400-...",
  "event": "log_entry",
  "data": {
    "time": "2026-06-01T12:05:00.123Z",
    "server_id": "uuid",
    "server_name": "web-01",
    "source": "php_app",
    "severity": "error",
    "message": "Fatal error: Call to undefined function foo()",
    "fields": {
      "type": "Fatal",
      "file": "/var/www/html/app.php",
      "line": 42,
      "message": "Call to undefined function foo()"
    }
  }
}
```

---

## 13. Pinia Store — `useLogStore`

| State | Type | Description |
|---|---|---|
| `entries` | `LogEntry[]` | Loaded log entries — prepended during live tail |
| `nextCursor` | `string \| null` | Pagination cursor |
| `limitReached` | `boolean` | True when 500-row cap was hit |
| `loading` | `boolean` | Initial load / pagination load |
| `loadingMore` | `boolean` | True during cursor-based page fetch |
| `liveTailActive` | `boolean` | Live tail on/off toggle |
| `newEntryCount` | `number` | Count of new entries arrived while user scrolled away |
| `filters` | `LogFilters` | Active server/source/severity/search/range state |
| `volumeData` | `VolumeBucket[]` | Chart data |

| Action | Description |
|---|---|
| `fetchLogs()` | GET `/api/logs` with active filters — replaces `entries` |
| `fetchMore()` | GET `/api/logs` with `cursor` — appends to `entries` |
| `fetchVolume()` | GET `/api/logs/volume` |
| `startLiveTail(serverIds)` | Subscribes to WS log channels |
| `stopLiveTail()` | Unsubscribes from all log channels |
| `appendLiveEntry(entry)` | Prepend to `entries` if matches active filters |
| `setFilter(key, value)` | Update a filter + re-fetch |
| `clearFilters()` | Reset all filters to defaults + re-fetch |

---

## 14. Keyboard Shortcuts

| Key | Action |
|---|---|
| `Ctrl+F` / `Cmd+F` | Focus the search input |
| `Escape` | Clear search input (if focused) |
| `l` | Toggle live tail on/off |
| `c` | Collapse/expand the volume chart |
| `j` / `↓` | Move selection to next row |
| `k` / `↑` | Move selection to previous row |
| `Enter` / `Space` | Expand / collapse selected row |

---

## 15. Empty & Edge States Summary

| Scenario | Behaviour |
|---|---|
| No logs found for active filters | Empty state: "No logs match your filters. Try adjusting the time range or filters." + `[Clear filters]` button |
| Server has never had Fluent Bit running | Empty state: "No logs from web-01 yet. Logs are collected from day one — check if the server is online." |
| Live tail — server goes offline | Entries stop arriving; no error shown (server offline is visible on the server status badge); existing entries remain |
| Live tail — WebSocket reconnecting | Pulsing dot turns grey; banner: "Live tail paused — reconnecting..."; entries may be missed during the gap |
| `limit_reached: true` | Footer shows warning instead of load more: "500 entries loaded — narrow your filters" |
| Search query too short (< 2 chars) | No API call; inline hint: "Enter at least 2 characters to search" |
| PHP app log path override — re-deploy fails | Toast error: "Failed to update log path — re-deploy failed. Check server connectivity." |
| mariadb_slow source selected — no slow queries | Source badge shown but no entries; hint: "No slow queries found. MariaDB slow query log threshold is 1 second." |
| Volume chart has zero entries in a bucket | Bar not rendered (not a zero-height bar) — gap in chart is acceptable |
| 7-day range selected — data older than 30 days | API returns what exists; no special UI; oldest data is naturally capped at 30 days by retention policy |
| Org switched while live tail is active | Live tail auto-stops; server filter reset; new org's logs loaded |
