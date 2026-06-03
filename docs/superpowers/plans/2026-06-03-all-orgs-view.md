# All-Organizations Dashboard & Servers View — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When an admin selects "All Organizations" from the org switcher, Dashboard shows a global cross-org overview and Servers shows all servers grouped by org — replacing the current "Select an organization" dead-end.

**Architecture:** Add one backend endpoint (`GET /api/dashboard/global`) that aggregates per-org stats for admins. On the frontend, persist "All Orgs" mode via a localStorage sentinel, add a `GlobalDashboard` component for the cross-org view, and extend `ServersView` to render org-grouped sections when no active org is selected.

**Tech Stack:** FastAPI (backend), Vue 3 + Pinia (frontend), existing `api` service, existing `useOrgStore` / `useServerStore`

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `backend/app/routers/dashboard.py` | Modify | Add `GET /api/dashboard/global` admin endpoint |
| `frontend/src/stores/org.ts` | Modify | Persist "All Orgs" selection via `'__all__'` sentinel |
| `frontend/src/stores/globalDashboard.ts` | Create | Pinia store for cross-org summary data |
| `frontend/src/components/dashboard/GlobalDashboard.vue` | Create | All-orgs overview: totals banner + per-org cards |
| `frontend/src/views/dashboard/DashboardView.vue` | Modify | Swap hint for `GlobalDashboard` when `!activeOrgId && isAdmin` |
| `frontend/src/views/servers/ServersView.vue` | Modify | Add org-grouped layout when `!activeOrgId` |

---

## Task 1 — Backend: `GET /api/dashboard/global`

**Files:**
- Modify: `backend/app/routers/dashboard.py`

- [ ] **Step 1: Add the global dashboard endpoint after the existing per-org dashboard route**

Open `backend/app/routers/dashboard.py` and add after the existing `get_recent_alerts` function (end of file):

```python
@router.get("/global", tags=["dashboard"])
async def get_global_dashboard(user: AdminUser, db: AsyncSession = Depends(get_db)):
    """Cross-org summary — admin only. Returns one entry per org."""
    from app.models.organization import Organization
    from app.models.server import Server
    from app.models.alert import Alert
    from app.models.service import ServiceCheck
    from sqlalchemy import func, case

    orgs_result = await db.execute(select(Organization).order_by(Organization.name))
    orgs = orgs_result.scalars().all()

    out = []
    for org in orgs:
        # Server counts
        srv = await db.execute(
            select(
                func.count(Server.id).label("total"),
                func.sum(case((Server.status == "online", 1), else_=0)).label("online"),
                func.sum(case((Server.status == "offline", 1), else_=0)).label("offline"),
            ).where(Server.org_id == org.id, Server.is_active == True)
        )
        srv_row = srv.one()

        # Alert counts
        alrt = await db.execute(
            select(
                func.count(Alert.id).label("total"),
                func.sum(case((Alert.state == "firing", 1), else_=0)).label("firing"),
            ).where(Alert.org_id == org.id)
        )
        alrt_row = alrt.one()

        out.append({
            "org": {"id": str(org.id), "name": org.name},
            "servers": {
                "total": int(srv_row.total or 0),
                "online": int(srv_row.online or 0),
                "offline": int(srv_row.offline or 0),
            },
            "alerts": {
                "total": int(alrt_row.total or 0),
                "firing": int(alrt_row.firing or 0),
            },
        })
    return out
```

Note: The router uses prefix `/api/organizations`, so add this route **outside** that router — register it on a separate `/api/dashboard` prefix or directly on the app router. Check `backend/app/main.py` to see how routers are included and add accordingly.

- [ ] **Step 2: Register the route correctly**

Check `backend/app/main.py` for how the dashboard router is included. If it uses prefix `/api/organizations`, the global route won't fit. Add it as a standalone route in `dashboard.py` with an explicit full path:

```python
# Add at the TOP of dashboard.py, before the existing router definition:
global_router = APIRouter(tags=["dashboard"])

@global_router.get("/api/dashboard/global")
async def get_global_dashboard(user: AdminUser, db: AsyncSession = Depends(get_db)):
    # ... same body as above
```

Then in `main.py`, include `global_router` alongside the existing `dashboard.router`.

- [ ] **Step 3: Smoke test the endpoint**

```bash
# Get a JWT first (assumes dev stack running)
TOKEN=$(curl -s -X POST http://localhost:8765/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"OpsPilot123!"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8765/api/dashboard/global | python3 -m json.tool
```

Expected: JSON array with one object per org, each having `org`, `servers`, `alerts` keys.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/dashboard.py backend/app/main.py
git commit -m "feat(api): add GET /api/dashboard/global admin cross-org summary"
```

---

## Task 2 — Frontend: Persist "All Organizations" in org store

**Files:**
- Modify: `frontend/src/stores/org.ts`

**Context:** Currently `setActiveOrg(null)` removes the localStorage key, so on reload `fetchOrgs` sees no key and auto-selects the first org, losing the "All Orgs" choice. Fix: store sentinel `'__all__'` to distinguish "explicitly chose All" from "never set".

- [ ] **Step 1: Update `org.ts` — sentinel constant, init read, setActiveOrg, fetchOrgs**

Replace the top of the store (lines before `export const useOrgStore`):

```typescript
const ACTIVE_ORG_KEY = 'opspilot.activeOrgId'
const ALL_SENTINEL = '__all__'

function readStoredOrgId(): string | null {
  const v = localStorage.getItem(ACTIVE_ORG_KEY)
  if (v === ALL_SENTINEL) return null   // "All Orgs" was explicitly chosen
  return v                               // UUID or null (never set)
}
```

Update `activeOrgId` initialization:

```typescript
const activeOrgId = ref<string | null>(readStoredOrgId())
```

Update `setActiveOrg`:

```typescript
function setActiveOrg(orgId: string | null): void {
  activeOrgId.value = orgId
  localStorage.setItem(ACTIVE_ORG_KEY, orgId ?? ALL_SENTINEL)
}
```

Update the auto-select logic inside `fetchOrgs` — only fall back to first org if the key has never been set at all (key is literally absent from localStorage):

```typescript
async function fetchOrgs(): Promise<void> {
  loading.value = true
  try {
    const { data } = await api.get<Organization[]>('/api/organizations')
    orgs.value = data
    const stored = localStorage.getItem(ACTIVE_ORG_KEY)
    if (stored === null) {
      // First ever login — default to first org
      if (orgs.value.length > 0) setActiveOrg(orgs.value[0].id)
    } else if (stored !== ALL_SENTINEL && !orgs.value.find((o) => o.id === stored)) {
      // Previously selected org no longer accessible — reset
      if (orgs.value.length > 0) setActiveOrg(orgs.value[0].id)
    }
  } finally {
    loading.value = false
  }
}
```

- [ ] **Step 2: Verify in browser**

1. Open the org switcher, click "All Organizations"
2. Reload the page
3. Confirm the switcher still shows "All Organizations" (not an org name)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/org.ts
git commit -m "fix(store): persist 'All Organizations' selection across page reloads"
```

---

## Task 3 — Frontend: Global Dashboard Pinia store

**Files:**
- Create: `frontend/src/stores/globalDashboard.ts`

- [ ] **Step 1: Create the store**

```typescript
// frontend/src/stores/globalDashboard.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/services/api'

export interface OrgSummary {
  org: { id: string; name: string }
  servers: { total: number; online: number; offline: number }
  alerts: { total: number; firing: number }
}

export const useGlobalDashboardStore = defineStore('globalDashboard', () => {
  const orgs = ref<OrgSummary[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  const totals = computed(() => ({
    servers: orgs.value.reduce((a, o) => a + o.servers.total, 0),
    online:  orgs.value.reduce((a, o) => a + o.servers.online, 0),
    offline: orgs.value.reduce((a, o) => a + o.servers.offline, 0),
    firing:  orgs.value.reduce((a, o) => a + o.alerts.firing, 0),
  }))

  async function fetch(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const { data } = await api.get<OrgSummary[]>('/api/dashboard/global')
      orgs.value = data
    } catch (e: any) {
      error.value = e?.response?.data?.detail ?? 'Failed to load global summary'
    } finally {
      loading.value = false
    }
  }

  function reset() {
    orgs.value = []
    error.value = null
  }

  return { orgs, loading, error, totals, fetch, reset }
})
```

Note: add `import { computed } from 'vue'` at the top alongside `ref`.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/stores/globalDashboard.ts
git commit -m "feat(store): add globalDashboard store for cross-org summary"
```

---

## Task 4 — Frontend: GlobalDashboard component

**Files:**
- Create: `frontend/src/components/dashboard/GlobalDashboard.vue`

- [ ] **Step 1: Create the component**

```vue
<!-- frontend/src/components/dashboard/GlobalDashboard.vue -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useOrgStore } from '@/stores/org'
import { useGlobalDashboardStore } from '@/stores/globalDashboard'
import { StatCard } from '@/components/ui'

const orgStore = useOrgStore()
const global = useGlobalDashboardStore()

onMounted(() => global.fetch())

function switchToOrg(orgId: string) {
  orgStore.setActiveOrg(orgId)
}
</script>

<template>
  <div class="global-dash">
    <div v-if="global.loading && !global.orgs.length" class="loading">Loading…</div>
    <div v-else-if="global.error" class="error">{{ global.error }}</div>
    <template v-else>
      <!-- Totals banner -->
      <div class="stat-grid">
        <StatCard
          label="Total Servers"
          :value="global.totals.online"
          :delta="{ value: `${global.totals.online} online · ${global.totals.offline} offline`, direction: 'flat' }"
          accent="info"
        />
        <StatCard
          label="Firing Alerts"
          :value="global.totals.firing"
          :delta="{ value: 'across all organizations', direction: 'flat' }"
          :accent="global.totals.firing > 0 ? 'danger' : 'success'"
        />
        <StatCard
          label="Organizations"
          :value="global.orgs.length"
          :delta="{ value: 'registered', direction: 'flat' }"
          accent="info"
        />
      </div>

      <!-- Per-org cards -->
      <div class="org-grid">
        <div
          v-for="o in global.orgs"
          :key="o.org.id"
          class="org-card"
          :class="{ 'has-alerts': o.alerts.firing > 0 }"
          @click="switchToOrg(o.org.id)"
        >
          <div class="org-name">{{ o.org.name }}</div>
          <div class="org-stats">
            <span class="stat-pill online">{{ o.servers.online }} online</span>
            <span v-if="o.servers.offline" class="stat-pill offline">{{ o.servers.offline }} offline</span>
            <span v-if="o.alerts.firing" class="stat-pill firing">{{ o.alerts.firing }} firing</span>
          </div>
          <div class="org-total">{{ o.servers.total }} server{{ o.servers.total !== 1 ? 's' : '' }} total</div>
          <div class="org-arrow">→</div>
        </div>
      </div>

      <div v-if="global.orgs.length === 0" class="empty">No organizations yet.</div>
    </template>
  </div>
</template>

<style scoped>
.global-dash { }
.loading, .error { padding: 40px; text-align: center; color: var(--muted); font-size: 13px; }
.error { color: #ef4444; }
.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}
.org-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}
.org-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 18px 20px;
  cursor: pointer;
  transition: border-color 0.15s;
  position: relative;
}
.org-card:hover { border-color: var(--accent); }
.org-card.has-alerts { border-color: rgba(239,68,68,0.35); }
.org-name { font-size: 15px; font-weight: 600; color: #fff; margin-bottom: 10px; }
.org-stats { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.stat-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
}
.stat-pill.online  { background: rgba(34,197,94,0.12);  color: #22c55e; }
.stat-pill.offline { background: rgba(239,68,68,0.12);  color: #ef4444; }
.stat-pill.firing  { background: rgba(239,68,68,0.15);  color: #ef4444; }
.org-total { font-size: 12px; color: var(--muted); }
.org-arrow {
  position: absolute;
  top: 18px;
  right: 18px;
  color: var(--muted);
  font-size: 14px;
  transition: color 0.15s;
}
.org-card:hover .org-arrow { color: var(--accent-2); }
.empty { color: var(--muted); font-size: 13px; text-align: center; padding: 40px; }
@media (max-width: 900px) { .stat-grid { grid-template-columns: 1fr 1fr; } }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/dashboard/GlobalDashboard.vue
git commit -m "feat(ui): add GlobalDashboard component — cross-org overview with per-org cards"
```

---

## Task 5 — Frontend: Wire GlobalDashboard into DashboardView

**Files:**
- Modify: `frontend/src/views/dashboard/DashboardView.vue`

- [ ] **Step 1: Import GlobalDashboard**

At the top of the `<script setup>` block, add:

```typescript
import GlobalDashboard from '@/components/dashboard/GlobalDashboard.vue'
```

- [ ] **Step 2: Replace the "Select an organization" hint**

In the template, find:

```html
<div v-if="!orgStore.activeOrgId" class="hint">Select an organization to view its dashboard.</div>
```

Replace with:

```html
<GlobalDashboard v-if="!orgStore.activeOrgId && auth.isAdmin" />
<div v-else-if="!orgStore.activeOrgId" class="hint">Select an organization to view its dashboard.</div>
```

- [ ] **Step 3: Verify in browser**

1. Click org switcher → select "All Organizations"
2. Dashboard should show the 3-stat banner + per-org cards
3. Clicking a card should switch to that org and show its dashboard
4. Reload — "All Organizations" should persist

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/dashboard/DashboardView.vue
git commit -m "feat(ui): show GlobalDashboard when All Organizations mode is active"
```

---

## Task 6 — Frontend: Org-grouped layout in ServersView

**Files:**
- Modify: `frontend/src/views/servers/ServersView.vue`

**Context:** `serverStore.servers` already contains all servers (flat) when `fetchAll()` is called. Need to group them by `org_id` and show org section headers. The `orgStore.orgs` array has the org names.

- [ ] **Step 1: Add `groupedServers` computed property**

Inside `<script setup>`, add after the existing `filteredServers` computed:

```typescript
interface OrgGroup {
  orgId: string
  orgName: string
  servers: Server[]
}

const groupedServers = computed<OrgGroup[]>(() => {
  if (orgStore.activeOrgId) return []   // only used in All Orgs mode
  const map = new Map<string, OrgGroup>()
  for (const s of serverStore.servers) {
    if (!map.has(s.org_id)) {
      const org = orgStore.orgs.find((o) => o.id === s.org_id)
      map.set(s.org_id, { orgId: s.org_id, orgName: org?.name ?? s.org_id, servers: [] })
    }
    map.get(s.org_id)!.servers.push(s)
  }
  return Array.from(map.values()).sort((a, b) => a.orgName.localeCompare(b.orgName))
})
```

- [ ] **Step 2: Update the template — add grouped layout**

In the template, find the flat server grid `<div v-else class="grid">` and replace the whole block with:

```html
<!-- All-orgs grouped layout -->
<template v-else-if="!orgStore.activeOrgId && auth.isAdmin">
  <div v-if="serverStore.servers.length === 0" class="empty">
    <div class="icon">🖥</div>
    <h2>No servers registered yet</h2>
    <p>Add a server inside an organization to get started.</p>
  </div>
  <template v-else>
    <div v-for="group in groupedServers" :key="group.orgId" class="org-section">
      <div class="org-section-head">
        <span class="org-section-name">{{ group.orgName }}</span>
        <span class="org-section-count">{{ group.servers.length }} server{{ group.servers.length !== 1 ? 's' : '' }}</span>
      </div>
      <div class="grid">
        <div v-for="s in group.servers" :key="s.id" class="card" :class="`status-${s.status}`">
          <!-- same card inner markup as the existing flat grid card — copy it here -->
          <div class="card-hd">
            <span v-if="s.status === 'pending' && cardOutcome(s.id) === 'failed'" class="hd-ico fail">✕</span>
            <span v-else-if="s.status === 'pending'" class="spinner"></span>
            <span v-else class="dot" :class="`dot-${s.status}`"></span>
            <span class="name">{{ s.name }}</span>
            <div v-if="auth.isAdmin" class="menu-wrap" @click.stop>
              <button class="kebab" aria-label="Server actions" @click="openMenuId = openMenuId === s.id ? null : s.id">⋮</button>
              <div v-if="openMenuId === s.id" class="kebab-menu">
                <button class="kmi" @click="openPanel(s.id)">View Onboarding Log</button>
                <button class="kmi" @click="redeployAgents(s.id)">Re-deploy Agents</button>
                <button class="kmi" @click="openEdit(s)">Edit Server</button>
                <div class="kmi-div"></div>
                <button class="kmi danger" @click="deleteServer(s.id)">Delete</button>
              </div>
            </div>
          </div>
          <div class="host">{{ s.host }}</div>
          <template v-if="s.status === 'pending'">
            <div v-if="cardOutcome(s.id) === 'failed'" class="ob ob-fail">
              <div class="ob-row"><span class="ob-label">ONBOARDING FAILED</span></div>
              <button class="ob-link fail" @click="openPanel(s.id)">View Error →</button>
            </div>
            <div v-else class="ob">
              <div class="ob-row">
                <span class="ob-label">ONBOARDING</span>
                <span class="ob-step mono">Step {{ onboarding.currentStepNumber(s.id) }} of {{ TOTAL_STEPS }}</span>
              </div>
              <div class="ob-running">{{ onboarding.runningLabel(s.id) || 'Starting…' }}</div>
              <div class="bar"><div class="bar-fill" :style="{ width: onboarding.progressPct(s.id) + '%' }"></div></div>
              <button class="ob-link" @click="openPanel(s.id)">View Progress →</button>
            </div>
          </template>
          <template v-else>
            <div class="meta">{{ s.os_distro ?? '—' }}</div>
            <div class="footer">
              <StatusBadge kind="server" :status="s.status" />
              <span class="time">{{ relativeTime(s.last_seen_at) }}</span>
            </div>
          </template>
          <div v-if="s.tags && s.tags.length" class="tags">
            <span v-for="t in s.tags" :key="t" class="tag">{{ t }}</span>
          </div>
        </div>
      </div>
    </div>
  </template>
</template>

<!-- Single-org flat layout (existing) -->
<div v-else class="grid">
  <!-- existing flat grid card markup unchanged -->
  ...
</div>
```

- [ ] **Step 3: Add org-section styles**

In the `<style scoped>` section, add:

```css
.org-section { margin-bottom: 28px; }
.org-section-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}
.org-section-name { font-size: 14px; font-weight: 600; color: #fff; }
.org-section-count { font-size: 12px; color: var(--muted); }
```

- [ ] **Step 4: Verify in browser**

1. Select "All Organizations" in the org switcher
2. Go to Servers — should see org section headers with grouped server cards
3. Switch back to a specific org — flat grid as before

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/servers/ServersView.vue
git commit -m "feat(ui): group servers by org in All Organizations mode"
```

---

## Task 7 — Final: push and smoke test

- [ ] **Step 1: Push all commits**

```bash
git push origin main
```

- [ ] **Step 2: End-to-end smoke test**

1. Login as admin → org switcher → "All Organizations" → reload → still "All Organizations" ✓
2. Dashboard → global banner (3 stat cards) + per-org cards visible ✓
3. Click an org card → switches to that org → per-org dashboard loads ✓
4. Org switcher → "All Organizations" → Servers → grouped by org headers ✓
5. Switch to specific org → Servers shows flat grid as before ✓
6. Non-admin user → org switcher has no "All Organizations" option → unaffected ✓

- [ ] **Step 3: Update PROGRESS.md and DASHBOARD.html if applicable**

This is a new enhancement (not a tracked phase task), so no dashboard update needed.
