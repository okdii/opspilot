# Spec 06 — Service Monitoring

**Version:** 1.0  
**Date:** 2026-06-01  
**Status:** Approved

---

## 1. Overview

Service monitoring allows the admin to define HTTP, TCP, or DB port checks per server. OpsPilot probes each service on a configurable interval from the backend (internal perspective). Results are stored in the `service_checks` TimescaleDB hypertable; incidents are tracked in the `incidents` table. The UI provides per-service uptime timelines, response time charts, and incident history.

PRD references: §5.5, §5.15, §5.16.6, §5.16.12, §9 (Service, ServiceCheck, Incident models)

---

## 2. Routes

| Route | Access | Description |
|---|---|---|
| `/services` | All roles | Service list for active org — all servers |
| `/servers/:id/services` | All roles | Service list filtered to a single server |
| `/services/:service_id` | All roles | Service detail page |
| `/status` | Public (no auth) | Public status page — services with `is_public = true` |

Route guards:
- `/services` and `/services/:service_id` require authentication and a selected active org.
- `/status` is always public — no auth check, no redirect.
- Adding, editing, or deleting services is gated to Admin only (`isAdmin` getter in auth store).

---

## 3. Service List Page (`/services`)

### 3.1 Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ Services                                           [+ Add Service]│
│                                                                    │
│ Filter: [All Servers ▼]  [All Types ▼]  [All Status ▼]  [Search] │
├──────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ ● app.example.com/health          HTTP  web-01   ↑ 99.9%   │ │
│  │   200ms avg   Last: 2s ago   Uptime: 24h 99.9% 7d 99.8%   │ │
│  │                                                  [⋮]        │ │
│  ├──────────────────────────────────────────────────────────────┤ │
│  │ ● MySQL :3306                     TCP   db-01    ↑ 100%    │ │
│  │   1ms avg    Last: 2s ago    Uptime: 24h 100%  7d 100%    │ │
│  │                                                  [⋮]        │ │
│  ├──────────────────────────────────────────────────────────────┤ │
│  │ ✕ api.example.com/ping            HTTP  web-02   ↓ DOWN     │ │
│  │   — avg      Last: 1m ago    Uptime: 24h 94.2% 7d 99.1%   │ │
│  │   ⚠ Down for 6 min  [View Incident]               [⋮]      │ │
│  └──────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 Filter Bar

| Control | Type | Behaviour |
|---|---|---|
| All Servers | Dropdown | Lists servers in active org with status dots |
| All Types | Dropdown | Options: All, HTTP, TCP, DB Port |
| All Status | Dropdown | Options: All, Up, Down, Unknown |
| Search | Text input | Filters by service name / URL / host — live, debounced 300ms |

When navigating to `/servers/:id/services`, the Server filter pre-selects that server and is locked (not changeable from this view). A breadcrumb shows "← web-01 / Services".

### 3.3 Service Row

Each service is displayed as a card-style row with:

- **Status dot**: green (up), red (down), amber (timeout), grey (unknown/not yet checked)
- **Name / URL**: full URL for HTTP services; `hostname:port` for TCP/DB services
- **Type badge**: `HTTP` (blue), `TCP` (purple), `DB` (teal)
- **Server name**: the server this service belongs to
- **Uptime badge**: `↑ 99.9%` (green) or `↓ DOWN` (red, pulsing)
- **Avg response time**: rolling 24h average in ms, or `—` if no data
- **Last checked**: relative time (e.g., "2s ago", "1m ago")
- **Uptime stats row**: 24h % and 7d % stat chips
- **Down banner**: shown only when `last_status = 'down'` — "Down for X min [View Incident →]"
- **[⋮] kebab menu**: Edit, Delete, View History

Sort order: down services always float to the top, then sorted by server name → service name.

### 3.4 Empty State

When no services exist yet for the active org:

```
┌────────────────────────────────────────┐
│                                        │
│         No services added yet          │
│                                        │
│   Add services to monitor uptime and   │
│   response times for your web apps,    │
│   APIs, and database ports.            │
│                                        │
│         [+ Add Your First Service]     │
│                                        │
└────────────────────────────────────────┘
```

Button visible to Admin only.

---

## 4. Add / Edit Service Modal

### 4.1 Trigger

- **Add**: `[+ Add Service]` button on the list page header.
- **Edit**: `[⋮] → Edit` on a service row.
- Modal is a slide-up on mobile, centered dialog (500px wide) on desktop.

### 4.2 Form Fields

#### Common Fields (all service types)

| Field | Type | Default | Validation |
|---|---|---|---|
| Server | Dropdown | Active server (if on `/servers/:id/services`) or first server | Required; lists servers in active org |
| Service Name | Text | Auto-filled (see below) | Required, 2–100 chars |
| Type | Radio group | HTTP | HTTP / TCP / DB Port |
| Check Interval | Select | 60s | 30s / 60s / 2min / 5min / 10min |
| Timeout | Select | 5s | 3s / 5s / 10s / 30s |
| Is Active | Toggle | On | Pauses checks when off |
| Public Status Page | Toggle | Off | Includes on `/status` page when on |

**Service Name auto-fill rules:**
- HTTP: populated from URL hostname once URL field loses focus (e.g., `app.example.com`)
- TCP/DB: populated as `hostname:port` once both fields are filled
- User can always override

#### HTTP-Specific Fields

| Field | Type | Default | Validation |
|---|---|---|---|
| URL | URL input | — | Required; must start with `http://` or `https://`; max 500 chars |
| Method | Select | GET | GET / POST / HEAD |
| Expected Status | Number | 200 | 100–599 |
| Ignore SSL Errors | Toggle | Off | When on, shows amber warning: "SSL cert errors will be ignored for this probe. SSL expiry is still tracked separately." |

#### TCP-Specific Fields

| Field | Type | Default | Validation |
|---|---|---|---|
| Host | Text | — | Required; hostname or IP; no protocol prefix |
| Port | Number | — | Required; 1–65535 |

#### DB Port-Specific Fields

| Field | Type | Default | Validation |
|---|---|---|---|
| Host | Text | — | Required; hostname or IP |
| Port | Number | — | Required; 1–65535 |
| DB Type | Select | MySQL | MySQL / MariaDB / PostgreSQL |

DB Port performs a TCP reachability check on the given host:port — no authentication credentials, no query execution.

### 4.3 Validation Rules

- URL must be a valid HTTP/HTTPS URL format (client-side regex, confirmed server-side).
- Port must be integer in range 1–65535.
- Duplicate check: warn (not block) if a service with the same URL + server_id already exists.
- If `is_active` is off on create, a grey info chip appears: "Service is inactive — checks will not run."

### 4.4 Submit Behaviour

- **Add**: POST `/api/services` → closes modal → newly added row inserted at top of list with a brief highlight animation → first check is triggered immediately (not waiting for interval).
- **Edit**: PATCH `/api/services/:id` → modal closes → row updates in place.
- Loading spinner on submit button while request is in flight.
- On API error: inline error banner above form footer.

### 4.5 Delete Confirmation

Triggered from `[⋮] → Delete`. Shows a modal:

```
Delete "app.example.com/health"?

This will permanently delete:
  • All check history (service_checks rows)
  • All incident records
  • Alert rules linked to this service

Type the service name to confirm:
[ app.example.com/health _____________ ]

[Cancel]  [Delete Service]
```

- Delete button disabled until typed name matches exactly (case-sensitive).
- On confirm: DELETE `/api/services/:id` → row removed from list with fade-out.

---

## 5. Service Detail Page (`/services/:service_id`)

### 5.1 Header

```
┌───────────────────────────────────────────────────────────────────┐
│ ← Services                                                        │
│                                                                   │
│  ● app.example.com/health                   HTTP  web-01         │
│  Up  |  200ms avg  |  Last checked: 3s ago  |  Active           │
│                                               [Edit]  [Pause]   │
└───────────────────────────────────────────────────────────────────┘
```

Header elements:
- Back breadcrumb → `/services`
- Status dot + service name + type badge + server name
- Status bar: `Up` / `Down` / `Unknown` — coloured to match status
- Avg response time (24h rolling)
- Last checked relative time (live-updating via WS)
- `[Edit]` → opens edit modal; `[Pause]` → toggles `is_active` (becomes `[Resume]` when inactive)

### 5.2 Uptime Summary Cards

Four stat cards in a row:

| Card | Value | Sub-label |
|---|---|---|
| Uptime 24h | e.g., 99.9% | `1 incident` or `No incidents` |
| Uptime 7d | e.g., 99.8% | `2 incidents` |
| Uptime 30d | e.g., 99.5% | `4 incidents` |
| Avg Response | e.g., 198ms | `24h average` |

Uptime % calculation: `up_count / total_count * 100` over the window. Periods with no checks (service was inactive) are excluded from denominator.

### 5.3 Uptime Status Timeline

Full-width timeline bar showing check status over the last 90 days.

```
Last 90 days
|████████████████████████████████████████████████░░█████████████|
Jan 1                                                    Today
```

- Each pixel-wide segment represents one time bucket
- Green = up, Red = down, Amber = timeout, Grey = no data
- Hover tooltip shows: date, status, uptime % for that day
- Click on a red/amber segment scrolls to the matching incident in the Incident History table

Rendered using ApexCharts timeline/rangebar chart. Data fetched via `GET /api/services/:id/uptime-timeline?days=90`.

### 5.4 Response Time History Chart

Line chart: response time (ms) on the y-axis, time on the x-axis.

- Time ranges: **1h / 6h / 24h / 7d / 30d** — toggle tabs above chart
- Range → data source (all computed on-the-fly by the backend from the `service_checks` hypertable — no pre-aggregated views needed given the small row counts at 1 check/min per service):
  - 1h / 6h: raw `service_checks` rows (time-bucketed to 1-min buckets)
  - 24h: `time_bucket('1 minute', time)` aggregates
  - 7d / 30d: `time_bucket('1 hour', time)` aggregates
- Shows two lines: **Avg** (solid) and **P95** (dashed)
- Down periods shown as red shaded background bands on the chart
- Alert threshold overlay (dashed red horizontal line) if an alert rule exists with `metric = 'response_time'`

Live updates: new check results pushed via WS update the rightmost end of the chart (1h view only).

### 5.5 Response Time Distribution (Histogram)

Bar chart — 4 buckets, displayed beneath the response time history:

| Bucket | Range |
|---|---|
| Fast | < 100ms |
| Normal | 100–300ms |
| Slow | 300–500ms |
| Very Slow | > 500ms |

Calculated over the selected time range (same tabs as response time chart). Clicking a bucket filters the Incident History table to show only checks in that range — not a hard filter, just scrolls to matching rows and highlights them.

### 5.6 Incident History Table

Below the charts. Title: "Incidents (last 90 days)"

| Column | Description |
|---|---|
| Started | Absolute datetime, formatted as `YYYY-MM-DD HH:mm:ss` |
| Resolved | Absolute datetime or `—` if still open |
| Duration | Human-readable: "6 min", "2h 14min", "Ongoing" |
| Cause | Badge: `http_error` / `timeout` / `connection_refused` / `wrong_status_code` |
| Checks | Count of failed checks within incident |

- Sorted by `started_at DESC`
- Open incidents (no `resolved_at`) shown at the top with a pulsing red "Ongoing" chip in the Resolved column
- Pagination: 20 rows per page, simple prev/next

### 5.7 Check History Table (Expandable)

Collapsed by default. Header: "Check History [Show ▼]"

When expanded, shows a paginated log of raw `service_checks` rows:

| Column | Description |
|---|---|
| Time | `YYYY-MM-DD HH:mm:ss` |
| Status | Chip: `up` (green) / `down` (red) / `timeout` (amber) |
| Response Time | ms or `—` |

- 50 rows per page, cursor-based pagination
- Collapse button at bottom

---

## 6. Public Status Page (`/status`)

### 6.1 Access

No authentication required. No sidebar. Full-page standalone layout. Light or dark theme respects OS preference.

Only services with `is_public = true` are shown. If no public services are configured, the page shows: "No public services configured."

### 6.2 Layout

```
┌────────────────────────────────────────────────────────────────┐
│                    MyCompany System Status                      │
│                                                                 │
│               ✓ All Systems Operational                        │
│                  Updated 10s ago                               │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Web App       ██████████████████████████████  99.9%   ●      │
│                                                                 │
│  API           ██████████████████████████████  100%    ●      │
│                                                                 │
│  Customer Portal  █████████████████████████░░  98.1%   ●      │
│                                                                 │
├────────────────────────────────────────────────────────────────┤
│  Past Incidents                                                 │
│                                                                 │
│  2026-05-28  Web App slow response — Resolved in 12 min       │
│  2026-05-14  API timeout — Resolved in 4 min                  │
└────────────────────────────────────────────────────────────────┘
```

### 6.3 Status Banner

- **All operational**: green banner — "✓ All Systems Operational"
- **One or more down**: red banner — "⚠ Some Systems Are Down"
- **Active incident open**: same red banner, plus an inline incident block above the service list:

```
┌──────────────────────────────────────────────────────────────┐
│ ⚠ Active Incident                                            │
│ API — Connection timeout                                      │
│ Started: 2026-06-01 14:22:00 · Ongoing                      │
└──────────────────────────────────────────────────────────────┘
```

### 6.4 Service Row

Each row:
- Service name (set in the "Service Name" field on the add/edit form)
- 90-day uptime timeline (same pixel-bar format as detail page, but smaller)
- Uptime % stat (30d)
- Status dot (right-aligned)

### 6.5 Past Incidents Panel

Shows resolved incidents for public services, last 90 days, most recent first.
Format: `YYYY-MM-DD  Service Name — cause text — Resolved in X min`

Limited to 20 rows. No pagination — if more, "See all incidents" link (opens a modal with full list).

### 6.6 Refresh

Page auto-refreshes every 60 seconds (polling, no WebSocket). "Updated Xs ago" counter in the header increments every second, resets on refresh.

---

## 7. WebSocket Integration

Service monitoring pushes real-time check results so the UI stays live without polling.

### 7.1 Subscription Messages

```json
// Subscribe to a single service's check results
{ "action": "subscribe_service", "service_id": "uuid" }

// Subscribe to all services in an org (used by list page)
{ "action": "subscribe_org_services", "org_id": "uuid" }

// Unsubscribe
{ "action": "unsubscribe_service", "service_id": "uuid" }
{ "action": "unsubscribe_org_services", "org_id": "uuid" }
```

### 7.2 Push Event Shape

```json
{
  "event": "service_check",
  "data": {
    "service_id": "uuid",
    "status": "up",
    "response_time_ms": 183,
    "checked_at": "2026-06-01T14:22:10Z",
    "consecutive_failures": 0,
    "last_status": "up"
  }
}
```

### 7.3 Incident Open / Close Events

```json
{
  "event": "incident_opened",
  "data": {
    "incident_id": "uuid",
    "service_id": "uuid",
    "started_at": "2026-06-01T14:22:10Z",
    "cause": "timeout"
  }
}

{
  "event": "incident_resolved",
  "data": {
    "incident_id": "uuid",
    "service_id": "uuid",
    "resolved_at": "2026-06-01T14:28:52Z",
    "duration_sec": 402
  }
}
```

### 7.4 Frontend Handling

**List page (`subscribe_org_services`):**
- `service_check` event → find the matching service row → update status dot, avg response time, last-checked time, uptime stats
- `incident_opened` → show down banner on matching row; float row to top
- `incident_resolved` → hide down banner; re-sort row back to normal position

**Detail page (`subscribe_service`):**
- `service_check` → append to response time history chart (1h view), update header stats
- `incident_opened` → show "Ongoing" row at top of incident table; update uptime summary cards
- `incident_resolved` → update "Ongoing" row to show resolved_at and duration

---

## 8. Backend — Probe Evaluator

### 8.1 Scheduler Job

One APScheduler job per active service, stored in the SQLAlchemy job store. Job ID: `service_probe:{service_id}`.

On startup: load all active services from DB, schedule their jobs. When a service is created, added immediately. When a service is paused (`is_active = false`), job is removed. When interval changes, job is rescheduled.

### 8.2 HTTP Probe Logic

```
1. Send HTTP request with configured method, URL, timeout
   - If ignore_ssl_errors = true: disable SSL verification
2. Record response_time_ms = wall time of request
3. Determine status:
   - status_code == expected_status → 'up'
   - status_code != expected_status → 'down', cause = 'wrong_status_code'
   - Timeout → 'timeout', cause = 'timeout'
   - Connection refused → 'down', cause = 'connection_refused'
   - Other HTTP error → 'down', cause = 'http_error'
4. Write ServiceCheck row + update Service.last_checked + Service.last_status
   in one transaction
5. Update Service.consecutive_failures:
   - If 'up': reset to 0
   - If 'down'/'timeout': increment by 1
6. If consecutive_failures == 2 AND no open incident:
   - Create Incident row (started_at = now, cause = determined above)
   - Fire alert (if alert rule exists)
7. If 'up' AND open incident exists:
   - Close incident (resolved_at = now, duration_sec = now - started_at)
   - Resolve linked alert
8. NOTIFY pg channel `service_checks:{service_id}` (backend fan-out to WS)
```

### 8.3 TCP Probe Logic

```
1. Open TCP socket to host:port with configured timeout
2. Record latency = time to connect
3. Success → 'up', response_time_ms = latency
4. Connection refused → 'down', cause = 'connection_refused'
5. Timeout → 'timeout', cause = 'timeout'
6. Same consecutive_failures + incident logic as HTTP probe
```

DB Port check uses identical TCP logic — the "DB Type" field is only used for display purposes (type badge) in v1. No query execution.

### 8.4 Concurrency

Probes run in asyncio tasks. Max 50 concurrent probe tasks (asyncio `Semaphore(50)`). This handles 50 servers × 3 services = 150 services comfortably within a 60s default interval. OpsPilot is a single-instance deployment — the semaphore is in-process and sufficient; horizontal scaling is out of scope for v1.

---

## 9. Pinia Store — `useServiceStore`

```ts
// State
services: Service[]          // all services for active org
activeService: Service | null
incidents: Incident[]        // for active service detail page
checkHistory: ServiceCheck[] // for check history table
uptimeTimeline: TimelineEntry[] // for the 90-day timeline

isLoadingList: boolean
isLoadingDetail: boolean
error: string | null

// Getters
servicesByServer: (server_id: string) => Service[]
downServices: Service[]         // services where last_status === 'down'
uptimePct: (service_id, window: '24h'|'7d'|'30d') => number

// Actions
fetchServices(org_id: string): Promise<void>
fetchServiceDetail(service_id: string): Promise<void>
fetchUptimeTimeline(service_id: string, days: 90): Promise<void>
fetchIncidents(service_id: string): Promise<void>
fetchCheckHistory(service_id: string, cursor?: string): Promise<void>
createService(payload): Promise<Service>
updateService(id: string, payload): Promise<Service>
deleteService(id: string): Promise<void>
toggleActive(id: string): Promise<void>
handleCheckEvent(event: ServiceCheckEvent): void   // WS handler
handleIncidentOpened(event: IncidentOpenedEvent): void
handleIncidentResolved(event: IncidentResolvedEvent): void
```

---

## 10. API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/organizations/:org_id/services` | Required | List all services for org |
| POST | `/api/services` | Required (Admin) | Create service |
| GET | `/api/services/:id` | Required | Get service detail |
| PATCH | `/api/services/:id` | Required (Admin) | Update service |
| DELETE | `/api/services/:id` | Required (Admin) | Delete service |
| GET | `/api/services/:id/incidents` | Required | List incidents (paginated) |
| GET | `/api/services/:id/checks` | Required | Check history (cursor-paginated) |
| GET | `/api/services/:id/uptime-timeline` | Required | 90-day timeline data |
| GET | `/api/services/:id/response-time` | Required | Response time chart data |
| GET | `/api/public/services` | Public | Services with `is_public=true` (for `/status` page) |
| GET | `/api/public/incidents` | Public | Recent resolved incidents for public services |

### 10.1 GET `/api/organizations/:org_id/services`

Response:
```json
[
  {
    "id": "uuid",
    "server_id": "uuid",
    "server_name": "web-01",
    "name": "app.example.com/health",
    "type": "http",
    "url": "https://app.example.com/health",
    "expected_status": 200,
    "interval_sec": 60,
    "timeout_sec": 5,
    "is_active": true,
    "is_public": false,
    "ignore_ssl_errors": false,
    "last_status": "up",
    "last_checked": "2026-06-01T14:22:10Z",
    "consecutive_failures": 0,
    "uptime_24h": 99.9,
    "uptime_7d": 99.8,
    "avg_response_ms_24h": 183,
    "open_incident_id": null
  }
]
```

### 10.2 GET `/api/services/:id/uptime-timeline`

Query params: `?days=90` (default 90, max 90)

Response: array of daily buckets:
```json
[
  { "date": "2026-03-03", "uptime_pct": 100.0, "down_minutes": 0 },
  { "date": "2026-03-04", "uptime_pct": 96.5, "down_minutes": 50 }
]
```

### 10.3 GET `/api/services/:id/response-time`

Query params: `?range=1h|6h|24h|7d|30d`

Response:
```json
{
  "range": "24h",
  "data": [
    { "time": "2026-06-01T13:00:00Z", "avg_ms": 183, "p95_ms": 421 }
  ]
}
```

---

## 11. Edge States

| State | Behaviour |
|---|---|
| Service never checked | `last_status = null` → grey dot, `—` for all stats |
| Service paused (`is_active = false`) | Amber "Paused" badge on row; no checks running; stats still visible |
| All services paused | List page shows amber info banner: "All services are paused — no checks running" |
| Check interval shorter than timeout | Validation: warn if interval ≤ timeout; allow but show advisory |
| Service down, no alert rule | Down banner still shows; no email sent; incident is still created |
| Org has no servers | "Add a server first before adding services." empty state with link |
| Backend probe fails with DNS error | Recorded as `down`, cause = `connection_refused`; hostname shown in incident detail |
| `/status` page, no public services | Full-page message: "No public services have been configured." — no crash |
| Response time chart, all data is null | Shows "No response time data for this period" placeholder in chart area |
| Incident has no `resolved_at` (server restart scenario) | Displayed as "Ongoing"; auto-resolved if next check returns up |
| 50+ services in list | List virtualised; all rows rendered but DOM recycled on scroll |
| WS disconnected during live check | List page stops updating; grey "Reconnecting…" chip in top-right; retries per auth spec reconnect logic |

---

## 12. Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `n` | Open Add Service modal (list page) |
| `Escape` | Close modal / slide-over |
| `r` | Refresh service list |
| `1`–`3` | Switch response time range tab (1h / 6h / 24h) on detail page |
| `/` | Focus search bar (list page) |
