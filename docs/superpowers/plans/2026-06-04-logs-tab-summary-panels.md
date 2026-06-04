# Logs Tab — Severity Summary Panels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 3 always-visible summary panels (Fatal / Error / Warn) above the LogsTab filter bar, each showing an accurate count and the latest log entry for the active filter/time range.

**Architecture:** New `GET /api/logs/summary` backend endpoint returns counts + latest entry per severity in one response. Frontend store gains a `summary` ref populated in parallel with the existing `fetchLogs()` call. LogsTab renders 3 cards that drill down into the table when clicked.

**Tech Stack:** FastAPI + SQLAlchemy async (backend), Vue 3 + Pinia (frontend), existing `_build_where` / `_resolve_scope` helpers, existing `relativeTime` util from `@/utils/time`.

---

### Task 1: Backend — `/api/logs/summary` endpoint

**Files:**
- Modify: `backend/app/routers/logs.py`

- [ ] **Step 1: Add the summary route after the existing `/volume` route**

Open `backend/app/routers/logs.py`. Add this new route after the `log_volume` function (before the `/intelligence` route, around line 239):

```python
@router.get("/summary")
async def log_summary(
    user: CurrentUser,
    org_id: str | None = Query(None),
    server_ids: str | None = Query(None),
    sources: str | None = Query(None),
    search: str | None = Query(None),
    frm: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    servers = await _resolve_scope(user, db, org_id, server_ids)
    server_map = {str(s.id): s.name for s in servers}
    scope_ids = list(server_map.keys())

    now = datetime.now(timezone.utc)
    frm_dt = _parse_ts(frm, now - timedelta(hours=1))
    to_dt = _parse_ts(to, now)
    src_list = _parse_csv(sources, VALID_SOURCES)

    # Build WHERE without severity filter — we query all severities for counts
    where, params, expanding = _build_where(scope_ids, src_list, [], search, frm_dt, to_dt)

    # Accurate counts for all three severity bands in one query
    count_stmt = text(f"""
        SELECT
            COUNT(*) FILTER (WHERE l.severity = 'fatal') AS fatal_count,
            COUNT(*) FILTER (WHERE l.severity = 'error') AS error_count,
            COUNT(*) FILTER (WHERE l.severity = 'warn')  AS warn_count
        FROM server_logs l
        WHERE {where}
    """).bindparams(*expanding)
    counts_row = (await db.execute(count_stmt, params)).one()
    fatal_count = int(counts_row[0])
    error_count = int(counts_row[1])
    warn_count  = int(counts_row[2])

    # Latest entry per severity (one query per band — each is a LIMIT 1 index scan)
    async def _latest(sev: str) -> dict | None:
        stmt = text(f"""
            SELECT l.time, l.server_id, l.source, l.severity, l.message, l.raw,
                   {_ROW_ID_SQL} AS row_id
            FROM server_logs l
            WHERE {where} AND l.severity = :sev
            ORDER BY l.time DESC
            LIMIT 1
        """).bindparams(*expanding)
        row = (await db.execute(stmt, {**params, "sev": sev})).one_or_none()
        if row is None:
            return None
        t, sid, source, severity, message, raw, rid = row
        sid_str = str(sid)
        return {
            "id": rid,
            "time": t.isoformat(),
            "server_id": sid_str,
            "server_name": server_map.get(sid_str, sid_str),
            "source": source,
            "severity": severity,
            "message": message,
            "fields": raw if isinstance(raw, dict) else {},
        }

    fatal_latest = await _latest("fatal") if fatal_count > 0 else None
    error_latest = await _latest("error") if error_count > 0 else None
    warn_latest  = await _latest("warn")  if warn_count  > 0 else None

    return {
        "fatal": {"count": fatal_count, "latest": fatal_latest},
        "error": {"count": error_count, "latest": error_latest},
        "warn":  {"count": warn_count,  "latest": warn_latest},
    }
```

- [ ] **Step 2: Smoke test the endpoint**

Restart the backend, then run:
```bash
# Replace <SERVER_ID> with a real server UUID from your DB
# Replace <TOKEN> with a valid JWT (log in via the UI and copy from browser devtools)
curl -s "http://localhost:8000/api/logs/summary?server_ids=<SERVER_ID>&from=$(date -u -v-1H +%Y-%m-%dT%H:%M:%SZ)&to=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -H "Authorization: Bearer <TOKEN>" | python3 -m json.tool
```

Expected: JSON with shape `{ "fatal": {"count": N, "latest": {...}|null}, "error": {...}, "warn": {...} }`. No 500 errors.

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/logs.py
git commit -m "feat(logs): add /api/logs/summary endpoint for severity band counts and latest entries"
```

---

### Task 2: Frontend — Types

**Files:**
- Modify: `frontend/src/types/index.ts` (after line 283, before the Alerting section)

- [ ] **Step 1: Add `LogSummaryBand` and `LogSummary` types**

In `frontend/src/types/index.ts`, insert after the `LogFilters` interface (after line 283) and before the `// --- Alerting` comment:

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

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx vue-tsc --noEmit 2>&1 | head -20
```

Expected: no errors related to `LogSummaryBand` or `LogSummary`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/index.ts
git commit -m "feat(logs): add LogSummaryBand and LogSummary types"
```

---

### Task 3: Frontend — API function

**Files:**
- Modify: `frontend/src/services/api.ts` (after line 191, after `getLogVolume`)

- [ ] **Step 1: Add `getLogSummary` import and function**

First add `LogSummary` to the import line at the top of `api.ts`. Find the existing log-related import line (it imports `LogsResponse`, `VolumeResponse`, etc.) and add `LogSummary` to it.

Then add the function after `getLogVolume` (after line 191):

```ts
export async function getLogSummary(params: Record<string, string>): Promise<LogSummary> {
  const { data } = await api.get<LogSummary>('/api/logs/summary', { params })
  return data
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx vue-tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/services/api.ts
git commit -m "feat(logs): add getLogSummary API function"
```

---

### Task 4: Frontend — Store

**Files:**
- Modify: `frontend/src/stores/logs.ts`

- [ ] **Step 1: Add summary state and fetchSummary function**

Add `LogSummary` to the import from `@/types` at the top of the file. The existing import line looks like:
```ts
import type {
  LogEntry, LogFilters, LogSeverity, LogSource, LogTimeRange, VolumeBucket,
} from '@/types'
```
Change it to:
```ts
import type {
  LogEntry, LogFilters, LogSeverity, LogSource, LogSummary, LogTimeRange, VolumeBucket,
} from '@/types'
```

Add `getLogSummary` to the import from `@/services/api`:
```ts
import { getLogs, getLogVolume, getLogSummary } from '@/services/api'
```

- [ ] **Step 2: Add `summary` ref inside the store (after `volumeData` ref, around line 47)**

```ts
const summary = ref<LogSummary | null>(null)
```

- [ ] **Step 3: Add `fetchSummary` function (after `fetchVolume`, around line 138)**

```ts
async function fetchSummary(): Promise<void> {
  if (!orgId.value && !filters.value.serverIds.length) return
  try {
    const params = buildParams()
    delete params.severities  // summary always covers all severities
    const res = await getLogSummary(params)
    summary.value = res
  } catch {
    summary.value = null
  }
}
```

- [ ] **Step 4: Update `refresh()` to call `fetchSummary` in parallel**

The current `refresh` function (line 140-142) is:
```ts
async function refresh(): Promise<void> {
  await Promise.all([fetchLogs(), fetchVolume()])
}
```

Change it to:
```ts
async function refresh(): Promise<void> {
  await Promise.all([fetchLogs(), fetchVolume(), fetchSummary()])
}
```

- [ ] **Step 5: Update `reset()` to clear summary**

Find the `reset()` function. Add `summary.value = null` alongside the other resets.

- [ ] **Step 6: Export `summary` and `fetchSummary` from the store return**

Find the `return { ... }` at the bottom of the store. Add `summary` and `fetchSummary` to it.

- [ ] **Step 7: Verify TypeScript compiles**

```bash
cd frontend && npx vue-tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/stores/logs.ts
git commit -m "feat(logs): add summary state and fetchSummary to log store"
```

---

### Task 5: Frontend — LogsTab UI Panels

**Files:**
- Modify: `frontend/src/components/servers/tabs/LogsTab.vue`

- [ ] **Step 1: Add imports**

At the top of the `<script setup>` block, add `relativeTime` to imports:
```ts
import { relativeTime } from '@/utils/time'
```

Also add `LogSummary` is already available via the store — no direct type import needed in the template.

- [ ] **Step 2: Add `clickBand` handler**

Add this function to the script section (near the other filter handler functions):

```ts
function clickBand(sev: 'fatal' | 'error' | 'warn'): void {
  logs.setFilter('severities', [sev])
  reload()
}
```

- [ ] **Step 3: Add the summary panels to the template**

In the `<template>`, insert the summary panels **before** the `<!-- Filter bar -->` comment (before the `<div class="filter-bar">` element):

```html
<!-- Severity summary panels -->
<div class="summary-panels">
  <div
    v-for="band in (['fatal', 'error', 'warn'] as const)"
    :key="band"
    class="summary-card"
    :class="band"
    @click="clickBand(band)"
  >
    <div class="sc-header">
      <span class="sc-dot"></span>
      <span class="sc-label">{{ band.toUpperCase() }}</span>
      <span class="sc-count">{{ logs.summary?.[band]?.count ?? '—' }}</span>
    </div>
    <template v-if="logs.summary?.[band]?.count">
      <div class="sc-msg">{{ (logs.summary[band].latest?.message ?? '').slice(0, 80) }}</div>
      <div class="sc-meta">{{ logs.summary[band].latest?.source }} · {{ relativeTime(logs.summary[band].latest?.time ?? null) }}</div>
    </template>
    <div v-else-if="logs.summary" class="sc-empty">No issues in this range</div>
    <div v-else class="sc-empty">—</div>
  </div>
</div>
```

- [ ] **Step 4: Add CSS for the summary panels**

Add to the `<style scoped>` section:

```css
.summary-panels {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-bottom: 14px;
}

.summary-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid var(--sc-color);
  border-radius: 10px;
  padding: 12px 14px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.summary-card:hover {
  background: var(--surface-2);
  border-color: var(--sc-color);
}
.summary-card.fatal { --sc-color: #991b1b; }
.summary-card.error { --sc-color: #ef4444; }
.summary-card.warn  { --sc-color: #f59e0b; }

.sc-header {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 6px;
}
.sc-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--sc-color);
  flex-shrink: 0;
}
.sc-label {
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--sc-color);
}
.sc-count {
  margin-left: auto;
  font-size: 18px;
  font-weight: 700;
  color: var(--sc-color);
  line-height: 1;
}
.sc-msg {
  font-size: 12px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}
.sc-meta {
  font-size: 11px;
  color: var(--muted);
}
.sc-empty {
  font-size: 12px;
  color: var(--muted);
}
```

- [ ] **Step 5: Smoke test in the browser**

1. Open the app at `http://localhost:9090`
2. Navigate to a server detail page → Logs tab
3. Verify 3 cards appear above the filter bar (Fatal / Error / Warn)
4. Verify each card shows a count number
5. If count > 0: verify the latest message text and `source · Xm ago` appear
6. If count = 0: verify "No issues in this range" appears in muted text
7. Click a card — verify the severity chips in the filter bar update to show only that severity, and the table reloads with matching entries
8. Change the time range (e.g. from 1h to 24h) — verify counts update to reflect the new range

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/servers/tabs/LogsTab.vue
git commit -m "feat(logs): add severity summary panels to LogsTab with drill-down click"
```

---

### Task 6: Update Progress Dashboard

**Files:**
- Modify: `pm/PROGRESS.md`
- Modify: `pm/DASHBOARD.html`

- [ ] **Step 1: Update PROGRESS.md and DASHBOARD.html**

Mark the logs tab summary panels feature as done in both files. Update `LAST_UPDATED` in DASHBOARD.html to `2026-06-04`.

- [ ] **Step 2: Commit and push**

```bash
git add pm/PROGRESS.md pm/DASHBOARD.html
git commit -m "chore: mark logs tab severity summary panels as done"
git push origin main
```
