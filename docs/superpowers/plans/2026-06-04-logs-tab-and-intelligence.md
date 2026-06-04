# Logs Tab + Log Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Logs tab to the server detail page (raw log viewer scoped to that server) and redesign the `/logs` page as an org-wide Log Intelligence summary.

**Architecture:** Part 1 reuses the existing `useLogStore` and `LogRow.vue` in a new `LogsTab.vue` component, wired into `ServerDetail.vue`. Part 2 adds a `/api/logs/intelligence` backend endpoint, a new `useLogIntelligenceStore`, and completely rewrites `LogsView.vue` to show intelligence panels instead of a raw table.

**Tech Stack:** Vue 3 + Pinia + Vuestic Admin (frontend), FastAPI + SQLAlchemy + TimescaleDB (backend)

---

## File Map

**Part 1 — Logs Tab (no backend changes):**
- Create: `frontend/src/components/servers/tabs/LogsTab.vue` — raw log viewer scoped to active server
- Modify: `frontend/src/views/servers/ServerDetail.vue` — add Logs to TABS + TAB_COMPONENTS + import + `?tab=` deep-link

**Part 2 — Log Intelligence (backend + frontend):**
- Modify: `backend/app/routers/logs.py` — add `GET /api/logs/intelligence` endpoint
- Modify: `frontend/src/services/api.ts` — add `getLogIntelligence()` function + `LogIntelligenceData` type
- Create: `frontend/src/stores/logIntelligence.ts` — Pinia store for intelligence data
- Modify: `frontend/src/views/logs/LogsView.vue` — complete rewrite as intelligence page

---

## Task 1: Create LogsTab.vue

**Files:**
- Create: `frontend/src/components/servers/tabs/LogsTab.vue`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/servers/tabs/LogsTab.vue` with the full content below:

```vue
<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useMetricsStore } from '@/stores/metrics'
import { useLogStore, ALL_SOURCES, ALL_SEVERITIES } from '@/stores/logs'
import { wsClient } from '@/utils/ws'
import { EmptyState } from '@/components/ui'
import LogRow from '@/components/logs/LogRow.vue'
import type { LogEntry, LogSeverity, LogSource, LogTimeRange } from '@/types'

const metrics = useMetricsStore()
const logs = useLogStore()

const serverId = computed(() => metrics.activeServerId ?? '')

const SOURCE_GROUPS: { label: string; sources: LogSource[] }[] = [
  { label: 'System', sources: ['syslog', 'auth', 'kernel'] },
  { label: 'Web', sources: ['nginx_access', 'nginx_error'] },
  { label: 'PHP', sources: ['php_fpm', 'php_app'] },
  { label: 'Database', sources: ['mariadb_error', 'mariadb_slow'] },
]

const RANGE_OPTIONS: { value: LogTimeRange; label: string }[] = [
  { value: '15m', label: 'Last 15 min' },
  { value: '1h', label: 'Last 1 hour' },
  { value: '6h', label: 'Last 6 hours' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
]

const SEV_COLORS: Record<LogSeverity, string> = {
  debug: '#6b7280', info: '#3b82f6', warn: '#f59e0b', error: '#ef4444', fatal: '#991b1b',
}

const expanded = ref<Set<string>>(new Set())
const freshIds = ref<Set<string>>(new Set())
const sourceMenuOpen = ref(false)
const scroller = ref<HTMLElement | null>(null)
const atTop = ref(true)

let unbindWs: (() => void) | null = null
let searchTimer: number | null = null
let subscribedServer = false

// Local filtersActive: excludes serverIds (that's the scope, not a user filter)
const filtersActive = computed(() => {
  const f = logs.filters
  return (
    f.sources.length !== ALL_SOURCES.length ||
    f.severities.length !== ALL_SEVERITIES.length ||
    f.search.trim().length >= 2 ||
    f.range !== '1h'
  )
})

const entryCountLabel = computed(() => {
  const n = logs.entries.length
  if (logs.limitReached) return `Showing ${n} entries (limit reached)`
  return `Showing ${n} ${n === 1 ? 'entry' : 'entries'}`
})

const sourcesSelected = (group: LogSource[]) =>
  group.every((s) => logs.filters.sources.includes(s))

function toggleSourceGroup(group: LogSource[]): void {
  const allOn = sourcesSelected(group)
  const set = new Set(logs.filters.sources)
  for (const s of group) (allOn ? set.delete(s) : set.add(s))
  logs.setFilter('sources', [...set] as LogSource[])
  reload()
}

function toggleSource(s: LogSource): void {
  const cur = logs.filters.sources
  logs.setFilter('sources', cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s])
  reload()
}

function toggleSeverity(s: LogSeverity): void {
  const cur = logs.filters.severities
  logs.setFilter('severities', cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s])
  reload()
}

function setRange(r: LogTimeRange): void {
  if (logs.liveTailActive) return
  logs.setFilter('range', r)
  reload()
}

function onSearchInput(e: Event): void {
  const v = (e.target as HTMLInputElement).value
  logs.setFilter('search', v)
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    if (v.trim().length === 0 || v.trim().length >= 2) reload()
  }, 300)
}

function clearSearch(): void {
  logs.setFilter('search', '')
  reload()
}

function clearFilters(): void {
  logs.setFilter('sources', [...ALL_SOURCES])
  logs.setFilter('severities', [...ALL_SEVERITIES])
  logs.setFilter('search', '')
  logs.setFilter('range', '1h')
  reload()
}

async function reload(): Promise<void> {
  await logs.refresh()
  expanded.value = new Set()
  await nextTick()
  if (scroller.value) scroller.value.scrollTop = 0
}

function toggleRow(id: string): void {
  const set = new Set(expanded.value)
  if (set.has(id)) set.delete(id); else set.add(id)
  expanded.value = set
}

async function onScroll(): Promise<void> {
  const el = scroller.value
  if (!el) return
  atTop.value = el.scrollTop <= 4
  if (atTop.value) logs.resetNewCount()
  if (logs.liveTailActive) return
  const pct = (el.scrollTop + el.clientHeight) / el.scrollHeight
  if (pct >= 0.8) await logs.fetchMore()
}

function scrollToTop(): void {
  scroller.value?.scrollTo({ top: 0, behavior: 'smooth' })
  logs.resetNewCount()
}

function startLiveTail(): void {
  logs.setLiveTail(true)
  if (!subscribedServer && serverId.value) {
    wsClient.send({ action: 'subscribe_logs', server_id: serverId.value })
    wsClient.send({ action: 'subscribe', server_id: serverId.value })
    subscribedServer = true
  }
}

function stopLiveTail(): void {
  logs.setLiveTail(false)
  if (subscribedServer && serverId.value) {
    wsClient.send({ action: 'unsubscribe_logs', server_id: serverId.value })
    subscribedServer = false
  }
}

function toggleLiveTail(): void {
  if (logs.liveTailActive) stopLiveTail(); else startLiveTail()
}

function handleWsMessage(msg: any): void {
  const channel: string | undefined = msg?.channel
  if (typeof channel !== 'string' || !channel.startsWith('server_logs:')) return
  if (msg.event !== 'log_entry' || !msg.data) return
  const entry = msg.data as LogEntry
  if (!entry.id) entry.id = `${entry.time}-${entry.source}-${Math.random().toString(36).slice(2)}`
  if (logs.appendLiveEntry(entry)) {
    freshIds.value = new Set([entry.id, ...freshIds.value])
    window.setTimeout(() => {
      const s = new Set(freshIds.value); s.delete(entry.id); freshIds.value = s
    }, 700)
    if (atTop.value) nextTick(() => { if (scroller.value) scroller.value.scrollTop = 0 })
  }
}

function onFilterSource(source: string): void {
  logs.setFilter('sources', [source as LogSource])
  reload()
}

function onFilterIp(ip: string): void {
  logs.setFilter('search', ip)
  reload()
}

onMounted(async () => {
  unbindWs = wsClient.on(handleWsMessage)
  logs.reset()
  logs.setFilter('serverIds', [serverId.value])
  await reload()
})

onUnmounted(() => {
  unbindWs?.(); unbindWs = null
  stopLiveTail()
  logs.reset()
})
</script>

<template>
  <div class="logs-tab">
    <!-- Filter bar -->
    <div class="filter-bar">
      <div class="fb-dd" @click.stop>
        <button class="fb-trigger" @click="sourceMenuOpen = !sourceMenuOpen">
          Sources
          <span class="fb-count">{{ logs.filters.sources.length }}/{{ ALL_SOURCES.length }}</span>
        </button>
        <div v-if="sourceMenuOpen" class="fb-menu">
          <div v-for="g in SOURCE_GROUPS" :key="g.label" class="fb-group">
            <label class="fb-opt fb-group-head">
              <input type="checkbox" :checked="sourcesSelected(g.sources)" @change="toggleSourceGroup(g.sources)" />
              <strong>{{ g.label }}</strong>
            </label>
            <label v-for="s in g.sources" :key="s" class="fb-opt fb-sub">
              <input type="checkbox" :checked="logs.filters.sources.includes(s)" @change="toggleSource(s)" />
              <span>{{ s }}</span>
            </label>
          </div>
        </div>
      </div>

      <div class="sev-chips">
        <button v-for="s in ALL_SEVERITIES" :key="s" class="chip"
          :class="{ active: logs.filters.severities.includes(s) }"
          :style="{ '--chip': SEV_COLORS[s] }"
          @click="toggleSeverity(s)">
          <span class="chip-dot"></span>{{ s }}
        </button>
      </div>

      <div class="fb-search">
        <input type="text" placeholder="Search logs…"
          :value="logs.filters.search" @input="onSearchInput" @keydown.escape="clearSearch" />
        <span v-if="logs.filters.search.trim().length === 1" class="search-hint">Enter at least 2 characters</span>
      </div>

      <select class="fb-range" :disabled="logs.liveTailActive"
        :value="logs.filters.range"
        @change="setRange(($event.target as HTMLSelectElement).value as LogTimeRange)">
        <template v-if="logs.liveTailActive"><option>Live</option></template>
        <template v-else>
          <option v-for="o in RANGE_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
        </template>
      </select>
    </div>

    <!-- Sub-bar -->
    <div class="sub-bar">
      <button class="live-btn" :class="{ on: logs.liveTailActive }" @click="toggleLiveTail">
        <span class="live-dot" :class="{ pulse: logs.liveTailActive }"></span>
        {{ logs.liveTailActive ? 'Live Tail ON' : 'Live Tail OFF' }}
      </button>
      <div class="sub-right">
        <span class="count">{{ entryCountLabel }}</span>
        <button v-if="filtersActive" class="link-btn" @click="clearFilters">Clear filters</button>
      </div>
    </div>

    <!-- Table -->
    <div class="table-card">
      <div class="t-head">
        <span class="th-caret"></span>
        <span class="th-time">Time</span>
        <span class="th-source">Source</span>
        <span class="th-sev">Sev</span>
        <span class="th-msg">Message</span>
      </div>

      <div v-if="logs.newEntryCount && !atTop" class="new-banner" @click="scrollToTop">
        ↑ {{ logs.newEntryCount }} new {{ logs.newEntryCount === 1 ? 'entry' : 'entries' }} — Scroll to top
      </div>

      <div ref="scroller" class="t-body" @scroll="onScroll">
        <div v-if="logs.loading" class="t-loading">Loading…</div>

        <EmptyState v-else-if="logs.error" title="Could not load logs" :message="logs.error" />

        <EmptyState v-else-if="!logs.entries.length"
          title="No logs match your filters"
          message="Try adjusting the time range or filters.">
          <template #action>
            <button v-if="filtersActive" class="es-btn" @click="clearFilters">Clear filters</button>
          </template>
        </EmptyState>

        <template v-else>
          <LogRow v-for="e in logs.entries" :key="e.id" :entry="e"
            :expanded="expanded.has(e.id)" :show-server="false"
            :fresh="freshIds.has(e.id)" :search="logs.filters.search"
            @toggle="toggleRow(e.id)"
            @filter-source="onFilterSource"
            @filter-ip="onFilterIp" />

          <div v-if="logs.loadingMore" class="t-footer">Loading…</div>
          <div v-else-if="logs.limitReached" class="t-footer warn">
            500 entries loaded — narrow your filters to see more precise results.
          </div>
          <div v-else-if="logs.nextCursor" class="t-footer">
            <button class="link-btn" @click="logs.fetchMore()">Load more</button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.logs-tab { display: flex; flex-direction: column; height: 100%; min-height: 0; }

.filter-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
.fb-dd { position: relative; }
.fb-trigger { display: inline-flex; align-items: center; gap: 8px; background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 8px 12px; border-radius: 8px; font-size: 13px; cursor: pointer; }
.fb-trigger:hover { border-color: var(--accent); }
.fb-count { font-size: 11px; color: var(--accent-2); background: rgba(99,102,241,0.12); padding: 1px 7px; border-radius: 10px; }
.fb-menu { position: absolute; top: calc(100% + 6px); left: 0; z-index: 30; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 8px; min-width: 220px; max-height: 320px; overflow-y: auto; box-shadow: 0 10px 30px rgba(0,0,0,0.4); }
.fb-opt { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 6px; cursor: pointer; font-size: 12.5px; color: var(--text); }
.fb-opt:hover { background: var(--surface-2); }
.fb-group { margin-bottom: 4px; }
.fb-group-head strong { font-size: 12px; }
.fb-sub { padding-left: 22px; color: var(--muted); }

.sev-chips { display: flex; gap: 6px; }
.chip { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 20px; font-size: 11.5px; cursor: pointer; border: 1px solid var(--border); background: transparent; color: var(--muted); text-transform: capitalize; transition: all 0.12s; }
.chip .chip-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--chip); }
.chip.active { background: color-mix(in srgb, var(--chip) 18%, transparent); border-color: var(--chip); color: var(--text); }

.fb-search { flex: 1; min-width: 180px; position: relative; }
.fb-search input { width: 100%; box-sizing: border-box; background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 8px 12px; border-radius: 8px; font-size: 13px; }
.fb-search input:focus { outline: none; border-color: var(--accent); }
.search-hint { position: absolute; top: calc(100% + 4px); left: 4px; font-size: 11px; color: var(--amber); }
.fb-range { background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 8px 12px; border-radius: 8px; font-size: 13px; cursor: pointer; }
.fb-range:disabled { opacity: 0.6; cursor: not-allowed; }

.sub-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.live-btn { display: inline-flex; align-items: center; gap: 8px; background: var(--surface); border: 1px solid var(--border); color: var(--muted); padding: 7px 14px; border-radius: 8px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
.live-btn.on { color: var(--green); border-color: rgba(34,197,94,0.4); background: rgba(34,197,94,0.08); }
.live-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
.live-dot.pulse { background: var(--green); animation: pulse 1.4s ease-in-out infinite; }
@keyframes pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(34,197,94,0.5); } 50% { box-shadow: 0 0 0 5px rgba(34,197,94,0); } }
.sub-right { display: flex; align-items: center; gap: 16px; }
.count { color: var(--muted); font-size: 12.5px; }
.link-btn { background: none; border: none; color: var(--accent-2); font-size: 12.5px; cursor: pointer; padding: 0; }
.link-btn:hover { text-decoration: underline; }

.table-card { flex: 1; min-height: 0; display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
.t-head { display: flex; align-items: center; gap: 12px; padding: 10px 14px; border-bottom: 1px solid var(--border); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); background: var(--surface-2); }
.th-caret { width: 8px; }
.th-time { width: 110px; }
.th-source { width: 110px; }
.th-sev { width: 64px; }
.th-msg { flex: 1; }
.t-body { flex: 1; overflow-y: auto; }
.t-loading { padding: 40px; text-align: center; color: var(--muted); font-size: 13px; }
.t-footer { padding: 14px; text-align: center; color: var(--muted); font-size: 12.5px; }
.t-footer.warn { color: var(--amber); }
.new-banner { background: var(--accent); color: #fff; text-align: center; padding: 8px; font-size: 12.5px; cursor: pointer; }
.new-banner:hover { opacity: 0.9; }
.es-btn { background: var(--surface-2); border: 1px solid var(--border); color: var(--text); padding: 8px 16px; border-radius: 8px; font-size: 13px; cursor: pointer; }
.es-btn:hover { border-color: var(--accent); }
</style>
```

- [ ] **Step 2: Smoke check — no TypeScript errors**

```bash
cd /Users/pocketdata/Code/Work/opspilot/frontend
npx vue-tsc --noEmit 2>&1 | grep -i "LogsTab\|error" | head -20
```

Expected: no errors mentioning LogsTab.vue

---

## Task 2: Wire LogsTab into ServerDetail.vue

**Files:**
- Modify: `frontend/src/views/servers/ServerDetail.vue`

- [ ] **Step 1: Add import**

In `frontend/src/views/servers/ServerDetail.vue`, after line 16 (the `import InfoTab` line), add:

```typescript
import LogsTab from '@/components/servers/tabs/LogsTab.vue'
```

- [ ] **Step 2: Add Logs to TABS constant**

Find line 41:
```typescript
const TABS = ['Info', 'Overview', 'CPU', 'Memory', 'Disk', 'Network', 'System', 'Processes', 'Services', 'Alerts'] as const
```

Replace with:
```typescript
const TABS = ['Info', 'Overview', 'CPU', 'Memory', 'Disk', 'Network', 'System', 'Processes', 'Services', 'Alerts', 'Logs'] as const
```

- [ ] **Step 3: Add Logs to TAB_COMPONENTS**

Find line 44:
```typescript
  Info: InfoTab, Overview: OverviewTab, CPU: CpuTab, Memory: MemoryTab,
  Disk: DiskTab, Network: NetworkTab, System: SystemTab, Processes: ProcessesTab,
  Services: ServicesTab, Alerts: AlertsTab,
```

Replace with:
```typescript
  Info: InfoTab, Overview: OverviewTab, CPU: CpuTab, Memory: MemoryTab,
  Disk: DiskTab, Network: NetworkTab, System: SystemTab, Processes: ProcessesTab,
  Services: ServicesTab, Alerts: AlertsTab, Logs: LogsTab,
```

- [ ] **Step 4: Smoke test in browser**

Open http://localhost:9090/servers (click any server), verify a "Logs" tab appears at the end of the tab bar. Click it — logs should load for that server.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/servers/tabs/LogsTab.vue frontend/src/views/servers/ServerDetail.vue
git commit -m "feat(server-detail): add Logs tab with raw log viewer scoped to server"
```

---

## Task 3: Add ?tab= deep-link support to ServerDetail.vue

**Files:**
- Modify: `frontend/src/views/servers/ServerDetail.vue`

This allows the Log Intelligence page's per-server cards to link directly to the Logs tab.

- [ ] **Step 1: Add onMounted tab init**

In `ServerDetail.vue`, find the `onMounted` or the area near where `activeTab` is declared. Add this block right after the `activeTab` ref definition:

```typescript
import { onMounted } from 'vue'
```

(If `onMounted` is not yet imported, add it to the existing vue import.)

Then add after the `activeTab` declaration:

```typescript
onMounted(() => {
  const tab = route.query.tab as string | undefined
  if (tab && (TABS as readonly string[]).includes(tab)) {
    activeTab.value = tab as Tab
  }
})
```

- [ ] **Step 2: Verify import**

`useRoute` is already imported in `ServerDetail.vue` (line 3). `route` is declared on line 29. No additional imports needed.

- [ ] **Step 3: Smoke test**

Navigate to `http://localhost:9090/servers/<any-id>?tab=Logs` directly. Verify the Logs tab is active on load.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/servers/ServerDetail.vue
git commit -m "feat(server-detail): support ?tab= query param for deep-linking to specific tab"
```

---

## Task 4: Backend /api/logs/intelligence endpoint

**Files:**
- Modify: `backend/app/routers/logs.py`

- [ ] **Step 1: Add the endpoint at the bottom of logs.py**

Append to `backend/app/routers/logs.py`:

```python
@router.get("/intelligence")
async def log_intelligence(
    user: CurrentUser,
    org_id: str = Query(...),
    range: str = Query("24h"),
    db: AsyncSession = Depends(get_db),
):
    valid_ranges = {"1h": 1, "6h": 6, "24h": 24}
    hours = valid_ranges.get(range, 24)
    frm = datetime.now(timezone.utc) - timedelta(hours=hours)

    servers = await _resolve_scope(user, db, org_id, None)
    if not servers:
        return _empty_intelligence()
    server_ids = [str(s.id) for s in servers]
    server_map = {str(s.id): s.name for s in servers}

    # 1. Severity summary
    stmt = text("""
        SELECT COALESCE(NULLIF(severity, ''), 'info') as sev, COUNT(*) as n
        FROM server_logs
        WHERE server_id IN :sids AND time >= :frm
        GROUP BY sev
    """).bindparams(bindparam("sids", expanding=True))
    rows = (await db.execute(stmt, {"sids": server_ids, "frm": frm})).all()
    summary: dict = {"fatal": 0, "error": 0, "warn": 0, "info": 0, "debug": 0}
    for sev, n in rows:
        if sev in summary:
            summary[sev] += int(n)

    # 2. Top recurring errors (group by truncated message)
    stmt = text("""
        SELECT LEFT(message, 150) as msg, COUNT(*) as n, source, MAX(time) as last_seen
        FROM server_logs
        WHERE server_id IN :sids AND time >= :frm AND severity IN ('error', 'fatal')
        GROUP BY LEFT(message, 150), source
        ORDER BY n DESC
        LIMIT 8
    """).bindparams(bindparam("sids", expanding=True))
    rows = (await db.execute(stmt, {"sids": server_ids, "frm": frm})).all()
    top_errors = [
        {"message": r[0], "count": int(r[1]), "source": r[2], "last_seen": r[3].isoformat()}
        for r in rows
    ]

    # 3. HTTP errors from nginx_access
    http_errors = None
    stmt = text("""
        SELECT
            COUNT(*) FILTER (WHERE raw->>'status_code' ~ '^[0-9]+$' AND (raw->>'status_code')::int >= 500) AS total_5xx,
            COUNT(*) FILTER (WHERE raw->>'status_code' ~ '^[0-9]+$' AND (raw->>'status_code')::int BETWEEN 400 AND 499) AS total_4xx
        FROM server_logs
        WHERE server_id IN :sids AND time >= :frm AND source = 'nginx_access'
    """).bindparams(bindparam("sids", expanding=True))
    row = (await db.execute(stmt, {"sids": server_ids, "frm": frm})).one_or_none()
    if row and (row[0] or row[1]):
        total_5xx, total_4xx = int(row[0] or 0), int(row[1] or 0)
        stmt2 = text("""
            SELECT raw->>'url' AS url, (raw->>'status_code')::int AS status, COUNT(*) AS n
            FROM server_logs
            WHERE server_id IN :sids AND time >= :frm AND source = 'nginx_access'
              AND raw->>'status_code' ~ '^[0-9]+$'
              AND (raw->>'status_code')::int >= 400
            GROUP BY url, status
            ORDER BY n DESC
            LIMIT 5
        """).bindparams(bindparam("sids", expanding=True))
        url_rows = (await db.execute(stmt2, {"sids": server_ids, "frm": frm})).all()
        http_errors = {
            "total_5xx": total_5xx,
            "total_4xx": total_4xx,
            "top_urls": [{"url": r[0], "status": r[1], "count": int(r[2])} for r in url_rows],
        }

    # 4. Slow queries from mariadb_slow
    slow_queries = None
    stmt = text("""
        SELECT COUNT(*) AS total,
               MAX(CASE WHEN raw->>'query_time' ~ '^[0-9.]+$'
                        THEN (raw->>'query_time')::float ELSE 0 END) AS worst_s,
               server_id::text
        FROM server_logs
        WHERE server_id IN :sids AND time >= :frm AND source = 'mariadb_slow'
        GROUP BY server_id
        ORDER BY worst_s DESC
        LIMIT 1
    """).bindparams(bindparam("sids", expanding=True))
    row = (await db.execute(stmt, {"sids": server_ids, "frm": frm})).one_or_none()
    if row and row[0]:
        total_slow, worst_s, worst_sid = int(row[0]), float(row[1] or 0), str(row[2])
        stmt2 = text("""
            SELECT message
            FROM server_logs
            WHERE server_id IN :sids AND time >= :frm AND source = 'mariadb_slow'
              AND raw->>'query_time' ~ '^[0-9.]+$'
            ORDER BY (raw->>'query_time')::float DESC
            LIMIT 1
        """).bindparams(bindparam("sids", expanding=True))
        msg_row = (await db.execute(stmt2, {"sids": server_ids, "frm": frm})).one_or_none()
        slow_queries = {
            "total": total_slow,
            "worst_duration_ms": round(worst_s * 1000),
            "worst_query": msg_row[0] if msg_row else "",
            "server_name": server_map.get(worst_sid, worst_sid),
        }

    # 5. Auth failures
    auth_events = None
    stmt = text("""
        SELECT raw->>'source_ip' AS ip, COUNT(*) AS n
        FROM server_logs
        WHERE server_id IN :sids AND time >= :frm AND source = 'auth'
          AND (message ILIKE '%failed password%'
               OR message ILIKE '%authentication failure%'
               OR message ILIKE '%invalid user%')
        GROUP BY raw->>'source_ip'
        ORDER BY n DESC
        LIMIT 5
    """).bindparams(bindparam("sids", expanding=True))
    rows = (await db.execute(stmt, {"sids": server_ids, "frm": frm})).all()
    if rows:
        failed_logins = sum(int(r[1]) for r in rows)
        auth_events = {
            "failed_logins": failed_logins,
            "top_ips": [{"ip": r[0] or "unknown", "count": int(r[1])} for r in rows],
        }

    # 6. Per-server breakdown + sparkline
    stmt = text("""
        SELECT server_id::text,
               COUNT(*) FILTER (WHERE severity = 'fatal') AS fatal,
               COUNT(*) FILTER (WHERE severity = 'error') AS error,
               COUNT(*) FILTER (WHERE severity = 'warn')  AS warn
        FROM server_logs
        WHERE server_id IN :sids AND time >= :frm
        GROUP BY server_id
    """).bindparams(bindparam("sids", expanding=True))
    rows = (await db.execute(stmt, {"sids": server_ids, "frm": frm})).all()
    counts_by_server = {r[0]: (int(r[1]), int(r[2]), int(r[3])) for r in rows}

    bucket_secs = max(600, (hours * 3600) // 6)
    stmt2 = text("""
        SELECT server_id::text,
               time_bucket(make_interval(secs => :bsec), time) AS bucket,
               COUNT(*) FILTER (WHERE severity IN ('error', 'fatal')) AS n
        FROM server_logs
        WHERE server_id IN :sids AND time >= :frm
        GROUP BY server_id, bucket
        ORDER BY bucket ASC
    """).bindparams(bindparam("sids", expanding=True))
    spark_rows = (await db.execute(stmt2, {"sids": server_ids, "frm": frm, "bsec": bucket_secs})).all()
    sparklines: dict[str, list[int]] = {sid: [] for sid in server_ids}
    for sid, _bucket, n in spark_rows:
        sparklines[str(sid)].append(int(n))

    per_server = []
    for s in servers:
        sid = str(s.id)
        fatal, error, warn = counts_by_server.get(sid, (0, 0, 0))
        per_server.append({
            "server_id": sid,
            "server_name": s.name,
            "fatal": fatal,
            "error": error,
            "warn": warn,
            "sparkline": sparklines.get(sid, []),
        })
    per_server.sort(key=lambda x: x["fatal"] * 100 + x["error"], reverse=True)

    # 7. Recent fatals (last 10, regardless of range)
    stmt = text("""
        SELECT l.time, l.server_id::text, l.source, l.message,
               md5(l.time::text || '|' || l.server_id::text || '|' || l.source || '|' || l.message) AS id
        FROM server_logs l
        WHERE l.server_id IN :sids AND l.severity = 'fatal'
        ORDER BY l.time DESC
        LIMIT 10
    """).bindparams(bindparam("sids", expanding=True))
    rows = (await db.execute(stmt, {"sids": server_ids, "frm": frm})).all()
    recent_fatals = [
        {
            "id": r[4],
            "time": r[0].isoformat(),
            "server_name": server_map.get(str(r[1]), str(r[1])),
            "source": r[2],
            "message": r[3],
        }
        for r in rows
    ]

    return {
        "summary": summary,
        "top_errors": top_errors,
        "http_errors": http_errors,
        "slow_queries": slow_queries,
        "auth_events": auth_events,
        "per_server": per_server,
        "recent_fatals": recent_fatals,
    }


def _empty_intelligence() -> dict:
    return {
        "summary": {"fatal": 0, "error": 0, "warn": 0, "info": 0, "debug": 0},
        "top_errors": [],
        "http_errors": None,
        "slow_queries": None,
        "auth_events": None,
        "per_server": [],
        "recent_fatals": [],
    }
```

- [ ] **Step 2: Smoke test endpoint with curl**

```bash
# Get a valid org_id first
curl -s -b "$(docker compose exec -T backend cat /tmp/test_cookie 2>/dev/null || echo '')" \
  http://localhost:8000/api/orgs 2>/dev/null | python3 -m json.tool | head -20

# Login and hit the endpoint (replace ORG_ID with actual value)
curl -s -c /tmp/ops_cookie -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python3 -m json.tool

curl -s -b /tmp/ops_cookie \
  "http://localhost:8000/api/logs/intelligence?org_id=ORG_ID&range=24h" \
  | python3 -m json.tool | head -50
```

Expected: JSON with keys `summary`, `top_errors`, `http_errors`, `slow_queries`, `auth_events`, `per_server`, `recent_fatals`

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/logs.py
git commit -m "feat(logs): add /api/logs/intelligence endpoint for org-wide log summary"
```

---

## Task 5: Frontend service function + intelligence store

**Files:**
- Modify: `frontend/src/services/api.ts`
- Create: `frontend/src/stores/logIntelligence.ts`

- [ ] **Step 1: Add type + API function to api.ts**

In `frontend/src/services/api.ts`, find the `getLogs` function (around line 141). Add the following directly before it:

```typescript
export interface LogIntelligenceData {
  summary: { fatal: number; error: number; warn: number; info: number; debug: number }
  top_errors: { message: string; count: number; source: string; last_seen: string }[]
  http_errors: {
    total_5xx: number
    total_4xx: number
    top_urls: { url: string; count: number; status: number }[]
  } | null
  slow_queries: {
    total: number
    worst_duration_ms: number
    worst_query: string
    server_name: string
  } | null
  auth_events: {
    failed_logins: number
    top_ips: { ip: string; count: number }[]
  } | null
  per_server: {
    server_id: string
    server_name: string
    fatal: number
    error: number
    warn: number
    sparkline: number[]
  }[]
  recent_fatals: {
    id: string
    time: string
    server_name: string
    source: string
    message: string
  }[]
}

export async function getLogIntelligence(orgId: string, range: string): Promise<LogIntelligenceData> {
  const { data } = await api.get<LogIntelligenceData>('/api/logs/intelligence', {
    params: { org_id: orgId, range },
  })
  return data
}
```

- [ ] **Step 2: Create logIntelligence store**

Create `frontend/src/stores/logIntelligence.ts`:

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getLogIntelligence, type LogIntelligenceData } from '@/services/api'

export const useLogIntelligenceStore = defineStore('logIntelligence', () => {
  const data = ref<LogIntelligenceData | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const range = ref('24h')

  async function fetch(orgId: string, r: string): Promise<void> {
    range.value = r
    loading.value = true
    error.value = null
    try {
      data.value = await getLogIntelligence(orgId, r)
    } catch {
      error.value = 'Could not load log intelligence.'
      data.value = null
    } finally {
      loading.value = false
    }
  }

  function reset(): void {
    data.value = null
    loading.value = false
    error.value = null
    range.value = '24h'
  }

  return { data, loading, error, range, fetch, reset }
})
```

- [ ] **Step 3: Verify no TypeScript errors**

```bash
cd /Users/pocketdata/Code/Work/opspilot/frontend
npx vue-tsc --noEmit 2>&1 | grep -i "error" | head -10
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/services/api.ts frontend/src/stores/logIntelligence.ts
git commit -m "feat(logs): add LogIntelligenceData type, API function, and Pinia store"
```

---

## Task 6: Redesign LogsView.vue as Log Intelligence page

**Files:**
- Modify: `frontend/src/views/logs/LogsView.vue`

- [ ] **Step 1: Replace LogsView.vue entirely**

Replace the full content of `frontend/src/views/logs/LogsView.vue` with:

```vue
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useOrgStore } from '@/stores/org'
import { useLogIntelligenceStore } from '@/stores/logIntelligence'
import { useLogStore, ALL_SOURCES, ALL_SEVERITIES } from '@/stores/logs'
import { PageHeader, EmptyState } from '@/components/ui'
import MetricChart from '@/components/charts/MetricChart.vue'
import type { LogSeverity, LogTimeRange, VolumeBucket } from '@/types'

const orgStore = useOrgStore()
const intel = useLogIntelligenceStore()
const logs = useLogStore()
const router = useRouter()

const RANGE_OPTIONS = [
  { value: '1h', label: 'Last 1 hour' },
  { value: '6h', label: 'Last 6 hours' },
  { value: '24h', label: 'Last 24 hours' },
]

const SEV_COLORS: Record<LogSeverity, string> = {
  debug: '#6b7280', info: '#3b82f6', warn: '#f59e0b', error: '#ef4444', fatal: '#991b1b',
}

let refreshTimer: number | null = null

const volumeSeries = computed(() =>
  ALL_SEVERITIES.map((sev) => ({
    name: sev,
    data: logs.volumeData.map((b: VolumeBucket) => b[sev as keyof VolumeBucket] as number),
  })).filter((s) => s.data.some((n) => n > 0)),
)
const volumeCategories = computed(() =>
  logs.volumeData.map((b: VolumeBucket) => new Date(b.time).getTime()),
)
const volumeColors = computed(() =>
  volumeSeries.value.map((s) => SEV_COLORS[s.name as LogSeverity]),
)
const hasVolume = computed(() => volumeSeries.value.length > 0 && logs.volumeData.length > 0)

function formatTime(iso: string): string {
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function goToServerLogs(serverId: string): void {
  router.push({ name: 'server-detail', params: { id: serverId }, query: { tab: 'Logs' } })
}

async function load(orgId: string, range: string): Promise<void> {
  logs.reset()
  logs.setOrg(orgId)
  logs.setFilter('range', range as LogTimeRange)
  await Promise.all([
    intel.fetch(orgId, range),
    logs.fetchVolume(),
  ])
}

async function setRange(r: string): Promise<void> {
  const orgId = orgStore.activeOrgId
  if (!orgId) return
  await load(orgId, r)
}

onMounted(async () => {
  const orgId = orgStore.activeOrgId
  if (orgId) await load(orgId, intel.range)
  refreshTimer = window.setInterval(async () => {
    const oid = orgStore.activeOrgId
    if (oid) await load(oid, intel.range)
  }, 60_000)
})

watch(() => orgStore.activeOrgId, async (orgId) => {
  intel.reset()
  logs.reset()
  if (orgId) await load(orgId, intel.range)
})

onUnmounted(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
  intel.reset()
  logs.reset()
})
</script>

<template>
  <div class="page">
    <PageHeader title="Log Intelligence" :subtitle="orgStore.activeOrg?.name ?? undefined" />

    <div v-if="!orgStore.activeOrgId" class="hint">Select an organization to view log intelligence.</div>

    <template v-else>
      <!-- Header bar: summary counts + range selector -->
      <div class="header-bar">
        <div class="summary-counts">
          <template v-if="intel.loading">
            <span class="count-item muted">Loading…</span>
          </template>
          <template v-else-if="intel.data">
            <span v-for="sev in (['fatal','error','warn','info'] as LogSeverity[])" :key="sev"
              class="count-item" :style="{ '--dot': SEV_COLORS[sev] }">
              <span class="count-dot"></span>
              <span class="count-label">{{ sev.charAt(0).toUpperCase() + sev.slice(1) }}:</span>
              <span class="count-val">{{ intel.data.summary[sev].toLocaleString() }}</span>
            </span>
          </template>
        </div>
        <select class="range-sel" :value="intel.range" @change="setRange(($event.target as HTMLSelectElement).value)">
          <option v-for="o in RANGE_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
      </div>

      <!-- Error state -->
      <EmptyState v-if="intel.error" title="Could not load intelligence" :message="intel.error" />

      <template v-else-if="intel.data">
        <!-- Intelligence card grid -->
        <div class="card-grid">
          <!-- Critical Errors -->
          <div class="intel-card">
            <div class="card-header">
              <span class="card-icon error-icon">!</span>
              <h3>Critical Errors</h3>
            </div>
            <div v-if="!intel.data.top_errors.length" class="card-empty">No errors in this range</div>
            <div v-else class="error-list">
              <div v-for="(e, i) in intel.data.top_errors" :key="i" class="error-row">
                <span class="error-count">×{{ e.count }}</span>
                <span class="error-source src-badge" :class="`src-${e.source}`">{{ e.source }}</span>
                <span class="error-msg" :title="e.message">{{ e.message }}</span>
              </div>
            </div>
          </div>

          <!-- HTTP Errors -->
          <div class="intel-card" :class="{ dimmed: !intel.data.http_errors }">
            <div class="card-header">
              <span class="card-icon http-icon">HTTP</span>
              <h3>HTTP Errors</h3>
            </div>
            <div v-if="!intel.data.http_errors" class="card-empty">No nginx_access data</div>
            <template v-else>
              <div class="http-summary">
                <span class="http-5xx">{{ intel.data.http_errors.total_5xx }} <small>5xx</small></span>
                <span class="http-4xx">{{ intel.data.http_errors.total_4xx }} <small>4xx</small></span>
              </div>
              <div class="url-list">
                <div v-for="(u, i) in intel.data.http_errors.top_urls" :key="i" class="url-row">
                  <span class="url-status" :class="u.status >= 500 ? 'err' : 'warn'">{{ u.status }}</span>
                  <span class="url-path" :title="u.url">{{ u.url }}</span>
                  <span class="url-count">×{{ u.count }}</span>
                </div>
              </div>
            </template>
          </div>

          <!-- Slow Queries -->
          <div class="intel-card" :class="{ dimmed: !intel.data.slow_queries }">
            <div class="card-header">
              <span class="card-icon slow-icon">⏱</span>
              <h3>Slow Queries</h3>
            </div>
            <div v-if="!intel.data.slow_queries" class="card-empty">No slow query data</div>
            <template v-else>
              <div class="slow-stats">
                <div class="slow-stat">
                  <span class="stat-val">{{ intel.data.slow_queries.total }}</span>
                  <span class="stat-label">slow queries</span>
                </div>
                <div class="slow-stat">
                  <span class="stat-val warn-text">{{ (intel.data.slow_queries.worst_duration_ms / 1000).toFixed(2) }}s</span>
                  <span class="stat-label">worst duration</span>
                </div>
              </div>
              <div class="slow-server">on {{ intel.data.slow_queries.server_name }}</div>
              <pre class="slow-query">{{ intel.data.slow_queries.worst_query }}</pre>
            </template>
          </div>

          <!-- Auth Events -->
          <div class="intel-card" :class="{ dimmed: !intel.data.auth_events }">
            <div class="card-header">
              <span class="card-icon auth-icon">🔒</span>
              <h3>Auth Events</h3>
            </div>
            <div v-if="!intel.data.auth_events" class="card-empty">No auth failure data</div>
            <template v-else>
              <div class="auth-total">
                <span class="stat-val warn-text">{{ intel.data.auth_events.failed_logins }}</span>
                <span class="stat-label"> failed logins</span>
              </div>
              <div class="ip-list">
                <div v-for="(ip, i) in intel.data.auth_events.top_ips" :key="i" class="ip-row"
                  :class="{ flagged: ip.count > 10 }">
                  <span class="ip-addr">{{ ip.ip }}</span>
                  <span class="ip-count">×{{ ip.count }}</span>
                  <span v-if="ip.count > 10" class="ip-flag">⚠</span>
                </div>
              </div>
            </template>
          </div>
        </div>

        <!-- Per-server health -->
        <section class="section">
          <h3 class="section-title">Server Health</h3>
          <div v-if="!intel.data.per_server.length" class="hint">No servers with log data.</div>
          <div v-else class="server-row">
            <div v-for="s in intel.data.per_server" :key="s.server_id"
              class="server-card" @click="goToServerLogs(s.server_id)">
              <div class="sc-name">{{ s.server_name }}</div>
              <div class="sc-counts">
                <span v-if="s.fatal" class="sc-count fatal">F:{{ s.fatal }}</span>
                <span class="sc-count error">E:{{ s.error }}</span>
                <span class="sc-count warn">W:{{ s.warn }}</span>
              </div>
              <div v-if="s.sparkline.length" class="sc-spark">
                <span v-for="(v, i) in s.sparkline" :key="i"
                  class="spark-bar"
                  :style="{ height: `${Math.max(2, Math.min(24, v))}px` }">
                </span>
              </div>
              <div class="sc-link">View logs →</div>
            </div>
          </div>
        </section>

        <!-- Recent fatals -->
        <section class="section">
          <h3 class="section-title">Recent Fatals</h3>
          <div v-if="!intel.data.recent_fatals.length" class="no-fatals">No fatal events — system clean.</div>
          <div v-else class="fatals-list">
            <div v-for="f in intel.data.recent_fatals" :key="f.id" class="fatal-row">
              <span class="fatal-time">{{ formatTime(f.time) }}</span>
              <span class="fatal-server">{{ f.server_name }}</span>
              <span class="fatal-source src-badge" :class="`src-${f.source}`">{{ f.source }}</span>
              <span class="fatal-msg" :title="f.message">{{ f.message }}</span>
            </div>
          </div>
        </section>

        <!-- Log volume chart -->
        <section class="section chart-section">
          <h3 class="section-title">Log Volume</h3>
          <MetricChart v-if="hasVolume" type="bar" unit="count" stacked
            :series="volumeSeries" :categories="volumeCategories"
            :colors="volumeColors" :height="200" />
          <div v-else class="chart-empty">No log volume data for this range.</div>
        </section>
      </template>
    </template>
  </div>
</template>

<style scoped>
.page { padding: 28px; display: flex; flex-direction: column; gap: 20px; }
.hint { color: var(--muted); font-size: 13px; padding: 40px; text-align: center; }

/* Header bar */
.header-bar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
.summary-counts { display: flex; gap: 20px; flex-wrap: wrap; }
.count-item { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }
.count-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--dot); flex-shrink: 0; }
.count-label { color: var(--muted); }
.count-val { color: var(--text); font-weight: 600; font-variant-numeric: tabular-nums; }
.count-item.muted { color: var(--muted); }
.range-sel { background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 8px 12px; border-radius: 8px; font-size: 13px; cursor: pointer; }

/* Card grid */
.card-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
@media (max-width: 800px) { .card-grid { grid-template-columns: 1fr; } }

.intel-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px; display: flex; flex-direction: column; gap: 10px; transition: opacity 0.2s; }
.intel-card.dimmed { opacity: 0.6; }
.card-header { display: flex; align-items: center; gap: 10px; }
.card-header h3 { font-size: 13px; font-weight: 600; color: var(--text); margin: 0; }
.card-icon { font-size: 11px; font-weight: 700; padding: 3px 7px; border-radius: 6px; }
.error-icon { background: rgba(239,68,68,0.18); color: #f87171; }
.http-icon { background: rgba(59,130,246,0.18); color: #60a5fa; font-size: 10px; }
.slow-icon { background: rgba(245,158,11,0.18); color: #fbbf24; }
.auth-icon { background: rgba(20,184,166,0.18); color: #2dd4bf; }
.card-empty { color: var(--muted); font-size: 12px; padding: 8px 0; }

/* Error list */
.error-list { display: flex; flex-direction: column; gap: 6px; }
.error-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.error-count { font-size: 11px; font-weight: 700; color: #f87171; width: 32px; flex-shrink: 0; text-align: right; }
.error-msg { flex: 1; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-family: ui-monospace, monospace; font-size: 11.5px; }

/* HTTP errors */
.http-summary { display: flex; gap: 24px; }
.http-5xx { font-size: 22px; font-weight: 700; color: #f87171; }
.http-5xx small, .http-4xx small { font-size: 11px; color: var(--muted); margin-left: 4px; font-weight: 400; }
.http-4xx { font-size: 22px; font-weight: 700; color: #fbbf24; }
.url-list { display: flex; flex-direction: column; gap: 4px; }
.url-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.url-status { font-size: 10px; font-weight: 700; padding: 2px 5px; border-radius: 4px; flex-shrink: 0; }
.url-status.err { background: rgba(239,68,68,0.18); color: #f87171; }
.url-status.warn { background: rgba(245,158,11,0.18); color: #fbbf24; }
.url-path { flex: 1; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-family: ui-monospace, monospace; }
.url-count { color: var(--muted); font-size: 11px; }

/* Slow queries */
.slow-stats { display: flex; gap: 24px; }
.slow-stat { display: flex; flex-direction: column; }
.stat-val { font-size: 22px; font-weight: 700; color: var(--text); }
.stat-label { font-size: 11px; color: var(--muted); }
.warn-text { color: #fbbf24 !important; }
.slow-server { font-size: 11.5px; color: var(--muted); }
.slow-query { background: #0f1117; border: 1px solid var(--border); border-radius: 6px; padding: 8px 10px; color: #e2e8f0; font-family: ui-monospace, monospace; font-size: 11px; white-space: pre-wrap; word-break: break-all; margin: 0; max-height: 80px; overflow: hidden; }

/* Auth events */
.auth-total { font-size: 13px; }
.ip-list { display: flex; flex-direction: column; gap: 4px; }
.ip-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.ip-addr { flex: 1; font-family: ui-monospace, monospace; color: var(--text); }
.ip-count { color: var(--muted); font-size: 11px; }
.ip-flag { color: #fbbf24; }
.ip-row.flagged .ip-addr { color: #fbbf24; }

/* Source badge */
.src-badge { font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 4px; flex-shrink: 0; text-transform: lowercase; }
.src-syslog { background: rgba(148,163,184,0.16); color: #cbd5e1; }
.src-auth { background: rgba(20,184,166,0.18); color: #2dd4bf; }
.src-kernel { background: rgba(100,116,139,0.22); color: #94a3b8; }
.src-nginx_access { background: rgba(59,130,246,0.18); color: #60a5fa; }
.src-nginx_error { background: rgba(37,99,235,0.22); color: #3b82f6; }
.src-php_fpm { background: rgba(168,85,247,0.18); color: #c084fc; }
.src-php_app { background: rgba(147,51,234,0.22); color: #a855f7; }
.src-mariadb_error { background: rgba(245,158,11,0.18); color: #fbbf24; }
.src-mariadb_slow { background: rgba(217,119,6,0.22); color: #f59e0b; }

/* Sections */
.section { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; }
.section-title { font-size: 13px; font-weight: 600; color: var(--text); margin: 0 0 12px; }

/* Per-server health */
.server-row { display: flex; gap: 12px; flex-wrap: wrap; }
.server-card { background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; cursor: pointer; transition: border-color 0.15s; min-width: 160px; display: flex; flex-direction: column; gap: 6px; }
.server-card:hover { border-color: var(--accent); }
.sc-name { font-size: 13px; font-weight: 600; color: var(--text); }
.sc-counts { display: flex; gap: 8px; }
.sc-count { font-size: 11.5px; font-weight: 600; font-variant-numeric: tabular-nums; }
.sc-count.fatal { color: #fca5a5; }
.sc-count.error { color: #f87171; }
.sc-count.warn { color: #fbbf24; }
.sc-spark { display: flex; align-items: flex-end; gap: 2px; height: 24px; }
.spark-bar { width: 6px; background: rgba(239,68,68,0.5); border-radius: 2px; }
.sc-link { font-size: 11px; color: var(--accent-2); }

/* Recent fatals */
.no-fatals { color: #4ade80; font-size: 13px; }
.fatals-list { display: flex; flex-direction: column; gap: 6px; }
.fatal-row { display: flex; align-items: center; gap: 10px; font-size: 12px; padding: 6px 0; border-bottom: 1px solid rgba(148,163,184,0.08); }
.fatal-row:last-child { border-bottom: none; }
.fatal-time { width: 40px; flex-shrink: 0; color: var(--muted); font-variant-numeric: tabular-nums; font-family: ui-monospace, monospace; }
.fatal-server { width: 100px; flex-shrink: 0; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fatal-msg { flex: 1; color: #fca5a5; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-family: ui-monospace, monospace; }

/* Volume chart */
.chart-section { }
.chart-empty { color: var(--muted); font-size: 12.5px; padding: 24px; text-align: center; }
</style>
```

- [ ] **Step 2: Restart frontend dev server if needed**

```bash
cd /Users/pocketdata/Code/Work/opspilot/frontend
# If already running hot-reload, changes auto-apply. If not:
npm run dev &
```

- [ ] **Step 3: Smoke test in browser**

Navigate to http://localhost:9090/logs. Verify:
1. Page title shows "Log Intelligence"
2. Header bar shows Fatal/Error/Warn/Info counts
3. Four intelligence cards render (Critical Errors, HTTP Errors, Slow Queries, Auth Events)
4. Per-server Health section shows server cards
5. Recent Fatals section shows (or shows "No fatal events" clean state)
6. Log Volume chart renders
7. Range selector (1h / 6h / 24h) reloads all panels when changed
8. Clicking a server card navigates to server detail with Logs tab active

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/logs/LogsView.vue
git commit -m "feat(logs): redesign /logs as Log Intelligence summary page"
```

---

## Task 7: Update PROGRESS.md + DASHBOARD.html and final push

- [ ] **Step 1: Update PROGRESS.md**

Mark both completed items in PROGRESS.md (server Logs tab + Log Intelligence page).

- [ ] **Step 2: Update DASHBOARD.html**

Update status for both tasks to `'done'` and update `LAST_UPDATED`.

- [ ] **Step 3: Commit and push**

```bash
git add PROGRESS.md DASHBOARD.html
git commit -m "chore: mark server Logs tab and Log Intelligence page as complete"
git push origin main
```
