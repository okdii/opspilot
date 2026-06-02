# Global Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the global dashboard — summary stat cards + a live server-card grid (CPU/RAM/Disk bars fed by the WS bus) — backed by two read endpoints.

**Architecture:** A new backend `dashboard.py` router returns summary counts + per-server latest metrics. The frontend `DashboardView` fetches it, renders reused `StatCard`s + new `ServerCard`/`MetricBar` components, subscribes via `subscribe_org`, and applies live `server_metrics` batches in place through a `dashboard` Pinia store.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy async / TimescaleDB; Vue 3 + Vite + Pinia + TypeScript + axios.

**Verification convention:** No pytest/vitest in this project — verify via **smoke tests** (CLAUDE.md Rule 1): backend via curl against the live stack (`127.0.0.1:8765`, the `lima-ubuntu` VM emitting real metrics), frontend via `vue-tsc --noEmit` typecheck + a Playwright browser check at `http://localhost:5173`. Each task is implement → smoke-verify → commit. Do NOT add a test framework.

**Frontend styling:** Every `.vue` task MUST invoke the **UI/UX Pro Max skill** (`/ui-ux-pro-max`) for visual design (CLAUDE.md Rule 2) and reuse existing dark-theme tokens (`var(--surface)`, `--surface-2`, `--border`, `--muted`, `--text`, `--accent`, `--accent-2`). The plan gives complete script/logic + template structure + the exact threshold/color rules; the skill handles visual polish to match the existing `StatCard`/`ServersView` look. Reuse existing components (`StatCard`, `StatusBadge`, `EmptyState`) — do not recreate them (CLAUDE.md Rule 3).

**Spec:** `docs/superpowers/specs/2026-06-02-global-dashboard-design.md`

---

## File structure

| File | Responsibility | Action |
|---|---|---|
| `backend/app/routers/dashboard.py` | dashboard + alerts/recent endpoints | Create |
| `backend/app/main.py` | register dashboard router | Modify |
| `frontend/src/types/index.ts` | dashboard TS types | Modify |
| `frontend/src/services/api.ts` | `getDashboard`, `getRecentAlerts` | Modify |
| `frontend/src/stores/dashboard.ts` | dashboard state + `applyMetricPush` | Create |
| `frontend/src/components/ui/MetricBar.vue` | metric bar atom | Create |
| `frontend/src/components/ui/index.ts` | export `MetricBar` | Modify |
| `frontend/src/components/servers/ServerCard.vue` | live server card | Create |
| `frontend/src/components/dashboard/RecentAlertsPanel.vue` | recent alerts panel | Create |
| `frontend/src/views/dashboard/DashboardView.vue` | assemble dashboard + live wiring | Modify (rewrite has-orgs branch) |
| `pm/PROGRESS.md`, `pm/DASHBOARD.html` | progress tracking | Modify (final task) |

**Smoke prereq block** (run once per shell that needs auth/IDs — Bash shells do NOT persist env between tool calls, so set these in the SAME shell as the command that uses them):
```bash
cd /Users/pocketdata/Code/Work/opspilot
H='$2b$12$5FtoMstccMPVWSs7us0S1Oj2qMXxOqQ4BuEzN9wjjgsxpO1yGoxV2'  # bcrypt of SmokeTest123!
docker exec opspilot-postgres psql -U opspilot -d opspilot -q -c \
"INSERT INTO \"user\" (id, username, password_hash, role) VALUES (gen_random_uuid(),'smoketest_admin','$H','admin') ON CONFLICT (username) DO UPDATE SET password_hash=EXCLUDED.password_hash, role='admin';"
TOK=$(curl -s -c - -X POST http://127.0.0.1:8765/api/auth/login -H 'Content-Type: application/json' -d '{"username":"smoketest_admin","password":"SmokeTest123!"}' | grep opspilot_jwt | awk '{print $7}')
ORG=$(docker exec opspilot-postgres psql -U opspilot -d opspilot -tA -c "SELECT id FROM organization LIMIT 1;")
```
Final task cleans up `smoketest_admin`.

---

## Task 1: Backend dashboard router

**Files:**
- Create: `backend/app/routers/dashboard.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create `backend/app/routers/dashboard.py`**

```python
"""Global dashboard read endpoints (spec 04 §2).

Servers + live metrics are real now; services/alerts/ssl summary blocks return
zeros until their phases (each isolated for a one-line swap later)."""
from fastapi import APIRouter, Depends
from sqlalchemy import bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import CurrentUser
from app.models.other import Alert
from app.models.server import Server
from app.routers.servers import _assert_org_access, _compute_status

router = APIRouter(prefix="/api/organizations", tags=["dashboard"])

CPU_METRIC = "cpu.usage_active"
RAM_METRIC = "mem.used_percent"
DISK_METRIC = "disk.used_percent"


@router.get("/{org_id}/dashboard")
async def get_dashboard(org_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_org_access(org_id, user, db)

    servers = (
        await db.execute(
            select(Server).where(Server.org_id == org_id, Server.is_active == True)
        )
    ).scalars().all()
    ids = [str(s.id) for s in servers]

    # Latest value per (server, metric) for the three card metrics.
    latest: dict[tuple[str, str], float] = {}
    if ids:
        stmt = text(
            """
            SELECT DISTINCT ON (server_id, metric_name)
                   server_id::text AS sid, metric_name, value
            FROM server_metrics
            WHERE server_id IN :ids
              AND metric_name IN :metrics
              AND (metric_name <> :disk OR labels->>'path' = '/')
            ORDER BY server_id, metric_name, time DESC
            """
        ).bindparams(bindparam("ids", expanding=True), bindparam("metrics", expanding=True))
        result = await db.execute(
            stmt,
            {"ids": ids, "metrics": [CPU_METRIC, RAM_METRIC, DISK_METRIC], "disk": DISK_METRIC},
        )
        for sid, mname, value in result:
            latest[(sid, mname)] = value

    server_out = []
    online = offline = maintenance = 0
    for s in servers:
        status = _compute_status(s)
        if status == "online":
            online += 1
        elif status == "maintenance":
            maintenance += 1
        else:
            offline += 1
        sid = str(s.id)
        server_out.append({
            "id": sid,
            "name": s.name,
            "host": s.host,
            "tags": s.tags or [],
            "status": status,
            "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None,
            "metrics": {
                "cpu": latest.get((sid, CPU_METRIC)),
                "ram": latest.get((sid, RAM_METRIC)),
                "disk": latest.get((sid, DISK_METRIC)),
            },
        })

    # Alert counts scoped to this org's servers (zeros until Phase 8 populates).
    alerts = {"firing": 0, "snoozed": 0, "acknowledged": 0}
    if ids:
        rows = await db.execute(
            select(Alert.state, func.count())
            .where(Alert.server_id.in_(ids), Alert.state.in_(["firing", "snoozed", "acknowledged"]))
            .group_by(Alert.state)
        )
        for state, count in rows:
            alerts[state] = count

    return {
        "summary": {
            "servers": {"total": len(servers), "online": online, "offline": offline, "maintenance": maintenance},
            "services": {"up": 0, "down": 0},           # Phase 4
            "alerts": alerts,                            # Phase 8 populates
            "ssl_domains": {"expiring": 0, "expired": 0},  # Phase 5
        },
        "servers": server_out,
    }


@router.get("/{org_id}/alerts/recent")
async def get_recent_alerts(org_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_org_access(org_id, user, db)
    rows = await db.execute(
        select(Alert, Server.name)
        .join(Server, Alert.server_id == Server.id)
        .where(Server.org_id == org_id)
        .order_by(Alert.sent_at.desc())
        .limit(10)
    )
    return [
        {
            "id": str(a.id),
            "server_name": name,
            "severity": a.severity,
            "message": a.message,
            "state": a.state,
            "sent_at": a.sent_at.isoformat() if a.sent_at else None,
        }
        for a, name in rows
    ]
```

- [ ] **Step 2: Register the router in `backend/app/main.py`.** Add the import beside the other router imports (after `from app.routers.servers import router as server_router`):
```python
from app.routers.dashboard import router as dashboard_router
```
and include it beside the others (after `app.include_router(server_router)`):
```python
app.include_router(dashboard_router)
```

- [ ] **Step 3: Smoke — both endpoints return expected shapes** (run the prereq block first, in the same shell):
```bash
echo "=== dashboard ==="
curl -s --cookie "opspilot_jwt=$TOK" "http://127.0.0.1:8765/api/organizations/$ORG/dashboard" | python3 -m json.tool
echo "=== alerts/recent ==="
curl -s --cookie "opspilot_jwt=$TOK" "http://127.0.0.1:8765/api/organizations/$ORG/alerts/recent"
```
Expected: dashboard JSON with `summary.servers.total >= 1`, `summary.servers.online >= 1`, and the `lima-ubuntu` entry under `servers` with **non-null** `metrics.cpu`, `metrics.ram`, `metrics.disk` (this confirms the metric-name mapping). `alerts/recent` → `[]`. If any metric is `null`, verify the metric name against live data: `docker exec opspilot-postgres psql -U opspilot -d opspilot -tA -c "SELECT DISTINCT metric_name FROM server_metrics WHERE metric_name LIKE 'cpu%' OR metric_name LIKE 'mem%' OR metric_name LIKE 'disk%';"` and adjust the `*_METRIC` constants, then re-run.

- [ ] **Step 4: Commit**
```bash
cd /Users/pocketdata/Code/Work/opspilot
git add backend/app/routers/dashboard.py backend/app/main.py
git commit -m "feat(dashboard): add dashboard + recent-alerts read endpoints

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Frontend types + service calls

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: Add dashboard types** at the end of `frontend/src/types/index.ts`:
```typescript
export interface ServerMetrics {
  cpu: number | null
  ram: number | null
  disk: number | null
}

export interface DashboardServer {
  id: string
  name: string
  host: string
  tags: string[]
  status: 'pending' | 'online' | 'offline' | 'maintenance'
  last_seen_at: string | null
  metrics: ServerMetrics
}

export interface DashboardSummary {
  servers: { total: number; online: number; offline: number; maintenance: number }
  services: { up: number; down: number }
  alerts: { firing: number; snoozed: number; acknowledged: number }
  ssl_domains: { expiring: number; expired: number }
}

export interface DashboardData {
  summary: DashboardSummary
  servers: DashboardServer[]
}

export interface RecentAlert {
  id: string
  server_name: string
  severity: string
  message: string
  state: string
  sent_at: string | null
}
```

- [ ] **Step 2: Add service functions** at the end of `frontend/src/services/api.ts`:
```typescript
import type { DashboardData, RecentAlert } from '@/types'

export async function getDashboard(orgId: string): Promise<DashboardData> {
  const { data } = await api.get<DashboardData>(`/api/organizations/${orgId}/dashboard`)
  return data
}

export async function getRecentAlerts(orgId: string): Promise<RecentAlert[]> {
  const { data } = await api.get<RecentAlert[]>(`/api/organizations/${orgId}/alerts/recent`)
  return data
}
```
(If `api.ts` already imports from `@/types`, merge the type names into the existing import instead of adding a duplicate `import` line.)

- [ ] **Step 3: Smoke — typecheck passes**
```bash
docker exec opspilot-frontend npx vue-tsc --noEmit
```
Expected: exits 0, no errors. (First run may take ~20-40s.)

- [ ] **Step 4: Commit**
```bash
git add frontend/src/types/index.ts frontend/src/services/api.ts
git commit -m "feat(dashboard): add dashboard types and service calls

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Dashboard Pinia store

**Files:**
- Create: `frontend/src/stores/dashboard.ts`

- [ ] **Step 1: Create the store** (mirrors the `server`/`onboarding` store style — `defineStore` with `ref`s + actions):
```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getDashboard } from '@/services/api'
import type { DashboardData, DashboardServer, DashboardSummary } from '@/types'

const EMPTY_SUMMARY: DashboardSummary = {
  servers: { total: 0, online: 0, offline: 0, maintenance: 0 },
  services: { up: 0, down: 0 },
  alerts: { firing: 0, snoozed: 0, acknowledged: 0 },
  ssl_domains: { expiring: 0, expired: 0 },
}

// WS push metric_name → DashboardServer.metrics key
const CPU_METRIC = 'cpu.usage_active'
const RAM_METRIC = 'mem.used_percent'
const DISK_METRIC = 'disk.used_percent'

interface PushRow {
  metric_name: string
  value: number | null
  labels: Record<string, unknown>
  time: string
}

export const useDashboardStore = defineStore('dashboard', () => {
  const summary = ref<DashboardSummary>({ ...EMPTY_SUMMARY })
  const servers = ref<DashboardServer[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchDashboard(orgId: string): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const data: DashboardData = await getDashboard(orgId)
      summary.value = data.summary
      servers.value = data.servers
    } catch {
      error.value = 'Could not load dashboard data.'
    } finally {
      loading.value = false
    }
  }

  // Apply a live server_metrics batch in place (no re-fetch).
  function applyMetricPush(serverId: string, rows: PushRow[]): void {
    const server = servers.value.find((s) => s.id === serverId)
    if (!server) return
    for (const row of rows) {
      if (row.value == null) continue
      if (row.metric_name === CPU_METRIC) server.metrics.cpu = row.value
      else if (row.metric_name === RAM_METRIC) server.metrics.ram = row.value
      else if (row.metric_name === DISK_METRIC && row.labels?.path === '/') server.metrics.disk = row.value
    }
  }

  function reset(): void {
    summary.value = { ...EMPTY_SUMMARY }
    servers.value = []
    loading.value = false
    error.value = null
  }

  return { summary, servers, loading, error, fetchDashboard, applyMetricPush, reset }
})
```

- [ ] **Step 2: Smoke — typecheck**
```bash
docker exec opspilot-frontend npx vue-tsc --noEmit
```
Expected: exits 0.

- [ ] **Step 3: Commit**
```bash
git add frontend/src/stores/dashboard.ts
git commit -m "feat(dashboard): add dashboard store with live applyMetricPush

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: MetricBar component

**Files:**
- Create: `frontend/src/components/ui/MetricBar.vue`
- Modify: `frontend/src/components/ui/index.ts`

**Invoke the UI/UX Pro Max skill for styling.** Logic + thresholds below are exact; match the dark-dashboard look.

- [ ] **Step 1: Create `frontend/src/components/ui/MetricBar.vue`**
```vue
<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ label: string; value: number | null }>()

// spec 04 §2.3 + spec 5.16.2 colour language
const GREEN = '#22c55e'
const AMBER = '#f59e0b'
const RED = '#ef4444'

const pct = computed(() => (props.value == null ? 0 : Math.max(0, Math.min(100, props.value))))
const hasValue = computed(() => props.value != null)
const color = computed(() => {
  const v = props.value ?? 0
  if (v >= 85) return RED
  if (v >= 70) return AMBER
  return GREEN
})
const warn = computed(() => (props.value ?? 0) > 80)
</script>

<template>
  <div class="metric-bar">
    <span class="mb-label">{{ label }}</span>
    <div class="mb-track">
      <div class="mb-fill" :style="{ width: pct + '%', background: color }"></div>
    </div>
    <span class="mb-value">
      <template v-if="hasValue">{{ Math.round(pct) }}%</template>
      <template v-else>—</template>
      <span v-if="warn" class="mb-warn" title="High usage">⚠</span>
    </span>
  </div>
</template>

<style scoped>
.metric-bar { display: grid; grid-template-columns: 40px 1fr 52px; align-items: center; gap: 10px; }
.mb-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
.mb-track { height: 6px; background: var(--surface-2); border-radius: 3px; overflow: hidden; }
.mb-fill { height: 100%; border-radius: 3px; transition: width 0.3s ease-out, background 0.3s; }
.mb-value { font-size: 12px; color: var(--text); text-align: right; font-variant-numeric: tabular-nums; }
.mb-warn { color: #f59e0b; margin-left: 4px; }
</style>
```

- [ ] **Step 2: Export it** — add to `frontend/src/components/ui/index.ts`:
```typescript
export { default as MetricBar } from './MetricBar.vue'
```

- [ ] **Step 3: Smoke — typecheck**
```bash
docker exec opspilot-frontend npx vue-tsc --noEmit
```
Expected: exits 0.

- [ ] **Step 4: Commit**
```bash
git add frontend/src/components/ui/MetricBar.vue frontend/src/components/ui/index.ts
git commit -m "feat(dashboard): add MetricBar component

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: ServerCard component

**Files:**
- Create: `frontend/src/components/servers/ServerCard.vue`

**Invoke the UI/UX Pro Max skill for styling.** Reuse `StatusBadge` (kind="server") and `MetricBar`.

- [ ] **Step 1: Create `frontend/src/components/servers/ServerCard.vue`**
```vue
<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { StatusBadge, MetricBar } from '@/components/ui'
import type { DashboardServer } from '@/types'

const props = defineProps<{ server: DashboardServer }>()
const router = useRouter()

const lastSeen = computed(() => {
  if (!props.server.last_seen_at) return 'never'
  const secs = Math.floor((Date.now() - new Date(props.server.last_seen_at).getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
})

function open(): void {
  void router.push(`/servers/${props.server.id}`)
}
</script>

<template>
  <button class="server-card" :class="`status-${server.status}`" @click="open">
    <div class="sc-head">
      <div class="sc-name">{{ server.name }}</div>
      <StatusBadge :status="server.status" kind="server" />
    </div>
    <div class="sc-host">{{ server.host }}</div>
    <div v-if="server.tags.length" class="sc-tags">
      <span v-for="t in server.tags" :key="t" class="sc-tag">{{ t }}</span>
    </div>
    <div class="sc-metrics">
      <MetricBar label="CPU" :value="server.metrics.cpu" />
      <MetricBar label="RAM" :value="server.metrics.ram" />
      <MetricBar label="Disk" :value="server.metrics.disk" />
    </div>
    <div class="sc-foot">Last seen: {{ lastSeen }}</div>
  </button>
</template>

<style scoped>
.server-card { display: block; width: 100%; text-align: left; cursor: pointer; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px; transition: border-color 0.15s, transform 0.1s; }
.server-card:hover { border-color: var(--accent); }
.server-card:active { transform: translateY(1px); }
.sc-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.sc-name { font-size: 14px; font-weight: 600; color: #fff; }
.sc-host { font-size: 12px; color: var(--muted); margin-top: 2px; }
.sc-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }
.sc-tag { font-size: 10px; color: var(--muted); background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 1px 6px; }
.sc-metrics { display: flex; flex-direction: column; gap: 8px; margin: 14px 0; }
.sc-foot { font-size: 11px; color: var(--muted); border-top: 1px solid var(--border); padding-top: 10px; }
</style>
```

- [ ] **Step 2: Smoke — typecheck**
```bash
docker exec opspilot-frontend npx vue-tsc --noEmit
```
Expected: exits 0.

- [ ] **Step 3: Commit**
```bash
git add frontend/src/components/servers/ServerCard.vue
git commit -m "feat(dashboard): add live ServerCard component

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: RecentAlertsPanel component

**Files:**
- Create: `frontend/src/components/dashboard/RecentAlertsPanel.vue`

**Invoke the UI/UX Pro Max skill for styling.** Reuse `StatusBadge` (kind="alert") and `EmptyState`.

- [ ] **Step 1: Create `frontend/src/components/dashboard/RecentAlertsPanel.vue`**
```vue
<script setup lang="ts">
import { StatusBadge, EmptyState } from '@/components/ui'
import type { RecentAlert } from '@/types'

defineProps<{ alerts: RecentAlert[] }>()

function rel(ts: string | null): string {
  if (!ts) return ''
  const secs = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}
</script>

<template>
  <section class="alerts-panel">
    <header class="ap-head">
      <h2>Recent Alerts</h2>
      <router-link to="/alerts" class="ap-viewall">View All →</router-link>
    </header>
    <EmptyState
      v-if="!alerts.length"
      title="No recent alerts"
      message="Alerts will appear here once alerting is active."
    />
    <ul v-else class="ap-list">
      <li v-for="a in alerts" :key="a.id" class="ap-row">
        <span class="ap-dot" :class="a.severity"></span>
        <span class="ap-desc">{{ a.server_name }} — {{ a.message }}</span>
        <StatusBadge :status="a.state" kind="alert" />
        <span class="ap-time">{{ rel(a.sent_at) }}</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.alerts-panel { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px; margin-top: 16px; }
.ap-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.ap-head h2 { font-size: 13px; font-weight: 600; color: #fff; }
.ap-viewall { font-size: 12px; color: var(--accent-2); text-decoration: none; }
.ap-list { list-style: none; display: flex; flex-direction: column; }
.ap-row { display: flex; align-items: center; gap: 10px; padding: 9px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
.ap-row:last-child { border-bottom: none; }
.ap-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: var(--muted); }
.ap-dot.critical { background: #ef4444; }
.ap-dot.warning { background: #f59e0b; }
.ap-desc { flex: 1; color: var(--text); }
.ap-time { font-size: 11px; color: var(--muted); }
</style>
```

- [ ] **Step 2: Smoke — typecheck**
```bash
docker exec opspilot-frontend npx vue-tsc --noEmit
```
Expected: exits 0.

- [ ] **Step 3: Commit**
```bash
git add frontend/src/components/dashboard/RecentAlertsPanel.vue
git commit -m "feat(dashboard): add RecentAlertsPanel component

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Assemble DashboardView + live wiring

**Files:**
- Modify: `frontend/src/views/dashboard/DashboardView.vue`

**Invoke the UI/UX Pro Max skill for styling.** Keep the existing no-orgs setup states exactly as they are; only replace the "Has orgs — Phase 2 placeholder" branch and add the live wiring in `<script setup>`.

- [ ] **Step 1: Replace the `<script setup>`** of `DashboardView.vue` with:
```typescript
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useOrgStore } from '@/stores/org'
import { useDashboardStore } from '@/stores/dashboard'
import { getRecentAlerts } from '@/services/api'
import { wsClient } from '@/utils/ws'
import { StatCard, EmptyState } from '@/components/ui'
import ServerCard from '@/components/servers/ServerCard.vue'
import RecentAlertsPanel from '@/components/dashboard/RecentAlertsPanel.vue'
import type { RecentAlert } from '@/types'

const auth = useAuthStore()
const orgStore = useOrgStore()
const dashboard = useDashboardStore()

const recentAlerts = ref<RecentAlert[]>([])
let unbindWs: (() => void) | null = null
let subscribedOrg: string | null = null

const alertAccent = computed<'success' | 'warning' | 'danger'>(() => {
  const f = dashboard.summary.alerts.firing
  if (f >= 3) return 'danger'
  if (f >= 1) return 'warning'
  return 'success'
})

async function load(orgId: string) {
  await dashboard.fetchDashboard(orgId)
  try { recentAlerts.value = await getRecentAlerts(orgId) } catch { recentAlerts.value = [] }
}

function subscribe(orgId: string) {
  if (subscribedOrg === orgId) return
  if (subscribedOrg) wsClient.send({ action: 'unsubscribe_org', org_id: subscribedOrg })
  wsClient.send({ action: 'subscribe_org', org_id: orgId })
  subscribedOrg = orgId
}

function unsubscribe() {
  if (subscribedOrg) wsClient.send({ action: 'unsubscribe_org', org_id: subscribedOrg })
  subscribedOrg = null
}

onMounted(() => {
  unbindWs = wsClient.on((msg: any) => {
    const channel: string | undefined = msg?.channel
    if (typeof channel === 'string' && channel.startsWith('server_metrics:')) {
      dashboard.applyMetricPush(channel.slice('server_metrics:'.length), msg.rows ?? [])
    }
  })
  const orgId = orgStore.activeOrgId
  if (orgId) { void load(orgId); subscribe(orgId) }
})

watch(() => orgStore.activeOrgId, (orgId) => {
  dashboard.reset()
  recentAlerts.value = []
  if (orgId) { void load(orgId); subscribe(orgId) }
  else unsubscribe()
})

onUnmounted(() => {
  unbindWs?.()
  unbindWs = null
  unsubscribe()
  dashboard.reset()
})
```

- [ ] **Step 2: Replace the has-orgs placeholder block** in the template. Find the `<!-- Has orgs — Phase 2 placeholder -->` `<div v-else>...</div>` block (the one containing `.stat-row` and `.coming-card`) and replace that entire `<div v-else>` with:
```vue
    <!-- Has orgs — live dashboard -->
    <div v-else class="dash">
      <div v-if="!orgStore.activeOrgId" class="hint">Select an organization to view its dashboard.</div>

      <template v-else>
        <div class="stat-grid">
          <StatCard label="Servers" :value="dashboard.summary.servers.total"
            :delta="{ value: `${dashboard.summary.servers.online} online · ${dashboard.summary.servers.offline} offline`, direction: 'flat' }"
            accent="info" />
          <StatCard label="Services Up" :value="dashboard.summary.services.up"
            :delta="{ value: `${dashboard.summary.services.down} down`, direction: 'flat' }" accent="success" />
          <StatCard label="Firing Alerts" :value="dashboard.summary.alerts.firing"
            :delta="{ value: `${dashboard.summary.alerts.snoozed} snoozed · ${dashboard.summary.alerts.acknowledged} ack`, direction: 'flat' }"
            :accent="alertAccent" />
          <StatCard label="SSL / Domains" :value="dashboard.summary.ssl_domains.expiring"
            :delta="{ value: `${dashboard.summary.ssl_domains.expired} expired`, direction: 'flat' }" accent="warning" />
        </div>

        <div v-if="dashboard.loading && !dashboard.servers.length" class="dash-loading">Loading…</div>
        <div v-else-if="dashboard.error" class="dash-error">{{ dashboard.error }}</div>

        <EmptyState v-else-if="!dashboard.servers.length"
          title="No servers yet"
          :message="auth.isAdmin ? 'Add your first server to start seeing data.' : 'No servers in this organization yet.'" />

        <div v-else class="server-grid">
          <ServerCard v-for="s in dashboard.servers" :key="s.id" :server="s" />
        </div>

        <RecentAlertsPanel :alerts="recentAlerts" />
      </template>
    </div>
```

- [ ] **Step 3: Add styles** for the new classes inside the component's `<style scoped>` (append; keep existing styles):
```css
.dash { }
.hint { color: var(--muted); font-size: 13px; padding: 40px; text-align: center; }
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
.server-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.dash-loading, .dash-error { padding: 32px; text-align: center; color: var(--muted); font-size: 13px; }
.dash-error { color: var(--red, #ef4444); }
@media (max-width: 900px) { .stat-grid { grid-template-columns: repeat(2, 1fr); } }
```
(You may remove the now-unused `.stat-row`/`.stat-tile`/`.coming-card`/`.stat-icon-wrap` styles that only served the old placeholder. Do NOT touch styles used by the setup/empty-org states.)

- [ ] **Step 4: Smoke — typecheck + dev server compiles**
```bash
docker exec opspilot-frontend npx vue-tsc --noEmit
docker logs opspilot-frontend --since 20s 2>&1 | grep -iE "error|failed" | grep -viE "0 error" | tail -5 || echo "no vite errors"
```
Expected: `vue-tsc` exits 0; no Vite compile errors.

- [ ] **Step 5: Commit**
```bash
git add frontend/src/views/dashboard/DashboardView.vue
git commit -m "feat(dashboard): assemble live dashboard view with WS wiring

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: End-to-end browser verification

**Files:**
- Create (throwaway, not committed): `/tmp/dash_check.mjs`

Playwright + Chromium are already installed under `/tmp/opspilot-verify` from Phase 1.

- [ ] **Step 1: Write `/tmp/dash_check.mjs`**
```javascript
import { chromium } from '/tmp/opspilot-verify/node_modules/playwright/index.mjs';
const BASE = 'http://localhost:5173';
const SHOTS = '/tmp/opspilot-verify/shots';
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
const txt = (sel) => page.textContent(sel).then(t => (t || '').trim()).catch(() => '(none)');
try {
  // login as the throwaway admin
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
  await page.fill('input[autocomplete="username"]', 'smoketest_admin');
  await page.fill('input[autocomplete="current-password"]', 'SmokeTest123!');
  await page.click('button.primary');
  await page.waitForURL(u => !u.pathname.startsWith('/login'), { timeout: 8000 });
  await page.waitForSelector('.server-card', { timeout: 10000 });
  await page.waitForTimeout(1500);

  // read the first server card's three metric values
  const read = async () => page.$$eval('.server-card .mb-value', els => els.slice(0, 3).map(e => e.textContent.trim()));
  const before = await read();
  console.log('stat cards present:', await page.$$eval('.stat-grid > *', e => e.length));
  console.log('server cards:', await page.$$eval('.server-card', e => e.length));
  console.log('metric values (t0):', before);
  await page.screenshot({ path: `${SHOTS}/dash-01-loaded.png` });

  // wait for a live Telegraf flush + WS push (~10-15s) and re-read
  await page.waitForTimeout(14000);
  const after = await read();
  console.log('metric values (t+14s):', after);
  await page.screenshot({ path: `${SHOTS}/dash-02-after.png` });

  const allPct = before.every(v => /%$/.test(v));
  const changed = JSON.stringify(before) !== JSON.stringify(after);
  console.log('bars show %:', allPct, '| live-updated:', changed);
  if (!allPct) throw new Error('metric bars not showing % values');
  console.log('DONE_OK');
} catch (e) { console.log('WALK_ERROR:', e.message); await page.screenshot({ path: `${SHOTS}/dash-err.png` }); process.exitCode = 1; }
finally { await browser.close(); }
```

- [ ] **Step 2: Run it** (run the prereq block first so `smoketest_admin` exists):
```bash
cd /tmp/opspilot-verify && node /tmp/dash_check.mjs
```
Expected: `stat cards present: 4`, `server cards: 1` (lima), `metric values (t0)` are three `NN%` strings, `bars show %: true`, and ideally `live-updated: true` (a value changed after the flush). Review `/tmp/opspilot-verify/shots/dash-01-loaded.png` to confirm the dashboard renders correctly (stat cards + lima card with three colored bars). If `live-updated` is false but values are valid %, note it — the 14s window can occasionally miss a change if values are flat; re-run once to confirm a change is observed.

- [ ] **Step 3: No commit** (verification only).

---

## Task 9: Update progress dashboard, clean up, final push

**Files:**
- Modify: `pm/PROGRESS.md`, `pm/DASHBOARD.html`

- [ ] **Step 1: Flip Global Dashboard tasks** in `pm/PROGRESS.md` (Phase 2 → Global Dashboard section). Set these `⬜` → `✅`:
```
- ✅ GET /api/organizations/:org_id/dashboard — summary + server latest metrics
- ✅ GET /api/organizations/:org_id/alerts/recent — last 10 alerts *(returns [] until Phase 8)*
- ✅ Summary stat cards (Servers, Services, Alerts, SSL/Domains) *(Servers live; others 0 until their phases)*
- ✅ Server card grid with live metric bars (CPU/RAM/Disk progress bars)
- ✅ Live card updates via WS (applyMetricPush)
- ✅ **Smoke test: dashboard loads, cards update live** *(verified on lima-ubuntu via Playwright; [Ack] deferred to Phase 8)*
```
Leave the `[Ack] works` part of the smoke note acknowledged as deferred (Ack is Phase 8). If the existing line reads "dashboard loads, cards update live, [Ack] works", replace it with the line above.

- [ ] **Step 2: Update Phase 2 count** in the summary table: `4 / 20` → `10 / 20`. Update Total: `64 / 191` → `70 / 191`.

- [ ] **Step 3: Flip matching entries** in `pm/DASHBOARD.html` — set `status: 'pending'` → `status: 'done'` for the six Global Dashboard tasks above (match each by its text string). Leave Server-Detail-Metrics tasks pending.

- [ ] **Step 4: Clean up the throwaway admin**
```bash
docker exec opspilot-postgres psql -U opspilot -d opspilot -q -c "
DELETE FROM session WHERE user_id=(SELECT id FROM \"user\" WHERE username='smoketest_admin');
DELETE FROM \"user\" WHERE username='smoketest_admin';"
docker exec opspilot-postgres psql -U opspilot -d opspilot -c "SELECT username, role FROM \"user\";"
```
Expected: only the original `admin` remains.

- [ ] **Step 5: Commit + push**
```bash
cd /Users/pocketdata/Code/Work/opspilot
git add pm/PROGRESS.md pm/DASHBOARD.html
git commit -m "feat(dashboard): complete Global Dashboard slice (Phase 2 → 10/20)

Live server-card grid (CPU/RAM/Disk bars) + summary stat cards, backed by
dashboard + recent-alerts endpoints. Verified on lima-ubuntu: dashboard loads
with real metric bars that update live via subscribe_org. Updates PROGRESS/DASHBOARD.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git push origin main
```

---

## Self-review notes

- **Spec coverage:** dashboard endpoint (Task 1), alerts/recent (Task 1), summary stat cards (Task 7), server grid + live bars (Tasks 4/5/7), `applyMetricPush` live wiring (Tasks 3/7), empty/loading/error + "select org" hint (Task 7), recent-alerts empty panel (Task 6), browser+curl verification (Tasks 1/8). All §1–§4 spec items covered. Deferred items (All-Orgs aggregate, Ack, ServersView unification) intentionally excluded per approved scope.
- **Type consistency:** `getDashboard`/`getRecentAlerts` (Task 2) match store + view usage (Tasks 3/7); `DashboardServer.metrics.{cpu,ram,disk}` consistent across endpoint (Task 1), types (Task 2), store push mapping (Task 3), `MetricBar`/`ServerCard` props (Tasks 4/5); metric-name constants identical in backend (Task 1) and store (Task 3): `cpu.usage_active`/`mem.used_percent`/`disk.used_percent`. `applyMetricPush(serverId, rows)` signature matches the view's WS handler call (Task 7).
- **No placeholders:** all code/commands concrete; styling delegated to UI/UX Pro Max per CLAUDE.md Rule 2 with exact thresholds/tokens given.
- **Reuse:** `StatCard`, `StatusBadge`, `EmptyState` reused (not recreated); `MetricBar`/`ServerCard` are the new canonical pieces (CLAUDE.md Rule 3).
