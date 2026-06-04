# Logs Tab — Severity Summary Panels

**Date:** 2026-06-04  
**Scope:** Server detail page → Logs tab  
**Status:** Approved

---

## Problem

The LogsTab shows raw log entries but gives no at-a-glance sense of how many fatal, error, or warning events exist in the current view. Users must scroll through entries to gauge severity distribution.

---

## Goal

Add 3 always-visible summary panels above the filter bar showing accurate counts and the latest log entry for each of: Fatal, Error, Warn. Counts follow the active filter/time range.

---

## Backend

### New endpoint: `GET /api/logs/summary`

**File:** `backend/app/routers/logs.py`

**Query params** (same as `/api/logs`):
- `server_ids` (required if no `org_id`)
- `org_id` (required if no `server_ids`)
- `from` / `to` — ISO timestamps
- `sources` — CSV of log sources (optional)
- `search` — full-text search string (optional)

> `severities` param is intentionally ignored — this endpoint always returns all 3 bands.

**Response shape:**
```json
{
  "fatal": { "count": 5,  "latest": { "id": "...", "time": "...", "source": "syslog", "severity": "fatal", "message": "OOM killer invoked on pid 1234", "server_id": "...", "server_name": "web-01", "fields": {} } },
  "error": { "count": 12, "latest": { ... } },
  "warn":  { "count": 47, "latest": { ... } }
}
```

If `count` is 0 for a band, `latest` is `null`.

**Implementation:**
- Reuse `_resolve_scope` and `_build_where` helpers (excluding severities clause)
- Single SQL query:
  - `COUNT(*) FILTER (WHERE severity = 'fatal')` etc. for accurate totals
  - `DISTINCT ON (severity)` subquery ordered by `time DESC` to get latest entry per severity
- Auth: same `CurrentUser` dependency as existing log routes

---

## Frontend Types

**File:** `frontend/src/types/index.ts`

```ts
export interface LogSummaryBand {
  count: number
  latest: LogEntry | null
}

export interface LogSummary {
  fatal: LogSummaryBand
  error: LogSummaryBand
  warn:  LogSummaryBand
}
```

---

## Frontend API

**File:** `frontend/src/services/api.ts`

Add `getLogSummary(params: Record<string, string>): Promise<LogSummary>` — calls `GET /api/logs/summary`.

---

## Frontend Store

**File:** `frontend/src/stores/logs.ts`

- Add `summary = ref<LogSummary | null>(null)`
- Add `fetchSummary()` — builds params via `buildParams()` (severities excluded), calls `getLogSummary`, stores result
- Update `refresh()` to call all three in parallel:
  ```ts
  await Promise.all([fetchLogs(), fetchVolume(), fetchSummary()])
  ```
- Update `reset()` to set `summary.value = null`
- Export `summary` from the store return

---

## Frontend UI

**File:** `frontend/src/components/servers/tabs/LogsTab.vue`

### Layout

3 horizontal cards inserted **above the filter bar**:

```
┌─────────────────────┐ ┌─────────────────────┐ ┌─────────────────────┐
│ ● FATAL          5  │ │ ● ERROR         12  │ │ ● WARN          47  │
│ OOM killer invoked… │ │ Connection refused… │ │ High memory usage…  │
│ syslog · 2 min ago  │ │ mariadb · 5 min ago │ │ kernel · 8 min ago  │
└─────────────────────┘ └─────────────────────┘ └─────────────────────┘
```

### States

| State | Appearance |
|-------|-----------|
| count > 0 | Colored left border, count in severity color, latest message + source + relative time |
| count = 0 | Muted border, count shows `0`, body shows "No issues in this range" in `--muted` color |
| loading (summary null) | 3 skeleton placeholder cards |

### Colors

Reuse existing `SEV_COLORS` from LogsTab:
- fatal: `#991b1b`
- error: `#ef4444`
- warn: `#f59e0b`

### Interaction

Clicking a card **isolates that severity** in the table — calls `toggleSeverity` to deselect all others and select only the clicked one. This gives users a one-click drill-down from summary to matching rows.

### Styling

Uses existing CSS variables only: `--surface`, `--surface-2`, `--border`, `--text`, `--muted`, `--accent`. No new design tokens. Message truncated at 80 characters. Source + relative time shown on second line.

---

## Data Flow

```
onMounted / reload()
  → Promise.all([fetchLogs(), fetchVolume(), fetchSummary()])
       ↓
  fetchSummary() → GET /api/logs/summary?server_ids=...&from=...&to=...
       ↓
  summary ref updated → panels render
```

Filter changes (source, time range, search) trigger `reload()` → all 3 fetches re-run together.

---

## Out of Scope

- Summary panels on the `/logs` intelligence page (separate feature)
- Clicking "latest" entry to scroll to it in the table
- Severity counts in the tab label badge
