# Server Detail — Monitoring Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Monitoring" tab to the server detail page showing HTTP/TCP monitoring checks registered for that server, with inline delete.

**Architecture:** New `GET /api/servers/{server_id}/monitoring` endpoint in `services.py` returns `list[ServiceOut]` filtered to that server. New `MonitoringTab.vue` fetches from this endpoint, renders a table, and handles inline delete confirmation. `ServerDetail.vue` adds "Monitoring" to its tab list.

**Tech Stack:** FastAPI + SQLAlchemy (backend), Vue 3 + Vuestic Admin + TypeScript (frontend)

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/app/routers/services.py` | Add `GET /api/servers/{server_id}/monitoring` |
| Modify | `frontend/src/types/index.ts` | Add `MonitoringService` type |
| Modify | `frontend/src/services/api.ts` | Add `getServerMonitoring`, `deleteMonitoringService` |
| Create | `frontend/src/components/servers/tabs/MonitoringTab.vue` | Monitoring tab component |
| Modify | `frontend/src/views/servers/ServerDetail.vue` | Wire MonitoringTab into tab list |

---

## Task 1: Backend — GET /api/servers/{server_id}/monitoring

**Files:**
- Modify: `backend/app/routers/services.py` — add endpoint after `list_services` (~line 163)

- [ ] **Step 1: Add the endpoint**

Insert after the `list_services` function (around line 163) in `backend/app/routers/services.py`:

```python
@router.get("/api/servers/{server_id}/monitoring", response_model=list[ServiceOut])
async def list_server_monitoring(
    server_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    server = await db.get(Server, server_id)
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})
    if user.role != "admin":
        membership = await db.scalar(
            select(UserOrganization).where(
                UserOrganization.user_id == user.id,
                UserOrganization.org_id == server.org_id,
            )
        )
        if not membership:
            raise HTTPException(403, detail={"error": "forbidden", "message": "Access denied."})
    rows = (
        await db.execute(
            select(Service).where(Service.server_id == server_id).order_by(Service.name)
        )
    ).scalars().all()
    return [await _service_to_out(svc, server.name, db) for svc in rows]
```

- [ ] **Step 2: Smoke test the endpoint**

Get a token first:
```bash
TOKEN=$(curl -s -X POST http://localhost:8765/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@opspilot.io","password":"admin123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

Get a server ID:
```bash
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8765/api/servers | python3 -m json.tool | grep '"id"' | head -3
```

Hit the new endpoint (replace `<server_id>`):
```bash
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8765/api/servers/<server_id>/monitoring | python3 -m json.tool
```

Expected: JSON array (empty `[]` if no checks registered, or list of ServiceOut objects).

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/services.py
git commit -m "feat(api): add GET /api/servers/{server_id}/monitoring endpoint"
```

---

## Task 2: Frontend — MonitoringService type + API functions

**Files:**
- Modify: `frontend/src/types/index.ts` — add `MonitoringService` interface
- Modify: `frontend/src/services/api.ts` — add `getServerMonitoring`, `deleteMonitoringService`

- [ ] **Step 1: Add MonitoringService type to types/index.ts**

Add after the `ServerServiceEntry` block (~line 215):

```ts
// --- Monitoring checks (HTTP/TCP probes, spec 06) ----------------------------

export type MonitoringServiceStatus = 'up' | 'down' | 'timeout' | null
export type MonitoringServiceType = 'http' | 'tcp' | 'db'

export interface MonitoringService {
  id: string
  server_id: string
  server_name: string
  name: string
  type: MonitoringServiceType
  url: string | null
  port: number | null
  last_status: MonitoringServiceStatus
  last_checked: string | null
  uptime_24h: number | null
  uptime_7d: number | null
  avg_response_ms_24h: number | null
  open_incident_id: string | null
}
```

- [ ] **Step 2: Add API functions to api.ts**

Add after the `getServerServices` function (~line 131):

```ts
export async function getServerMonitoring(serverId: string): Promise<MonitoringService[]> {
  const { data } = await api.get<MonitoringService[]>(`/api/servers/${serverId}/monitoring`)
  return data
}

export async function deleteMonitoringService(serviceId: string): Promise<void> {
  await api.delete(`/api/services/${serviceId}`)
}
```

Add `MonitoringService` to the import list at the top of `api.ts` — find the existing import from `@/types` and add it:

```ts
import type {
  // ... existing imports ...
  MonitoringService,
} from '@/types'
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/services/api.ts
git commit -m "feat(frontend): add MonitoringService type and API functions"
```

---

## Task 3: Create MonitoringTab.vue

**Files:**
- Create: `frontend/src/components/servers/tabs/MonitoringTab.vue`

- [ ] **Step 1: Create the component**

```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { EmptyState, StatusBadge } from '@/components/ui'
import { deleteMonitoringService, getServerMonitoring } from '@/services/api'
import { useMetricsStore } from '@/stores/metrics'
import type { MonitoringService } from '@/types'

const metrics = useMetricsStore()
const services = ref<MonitoringService[]>([])
const loading = ref(true)
const confirmingId = ref<string | null>(null)
const deletingId = ref<string | null>(null)
const deleteError = ref<string | null>(null)

async function fetchServices() {
  const id = metrics.activeServerId
  if (!id) return
  loading.value = true
  try {
    services.value = await getServerMonitoring(id)
  } catch {
    // keep stale data on transient error
  } finally {
    loading.value = false
  }
}

function startConfirm(id: string) {
  confirmingId.value = id
  deleteError.value = null
}

function cancelConfirm() {
  confirmingId.value = null
  deleteError.value = null
}

async function confirmDelete(id: string) {
  deletingId.value = id
  deleteError.value = null
  try {
    await deleteMonitoringService(id)
    services.value = services.value.filter((s) => s.id !== id)
    confirmingId.value = null
  } catch {
    deleteError.value = id
  } finally {
    deletingId.value = null
  }
}

function formatUptime(pct: number | null): string {
  if (pct == null) return '—'
  return `${pct.toFixed(1)}%`
}

function formatResponse(ms: number | null): string {
  if (ms == null) return '—'
  return `${ms}ms`
}

function formatUrl(svc: MonitoringService): string {
  if (svc.type === 'http') return svc.url ?? '—'
  if (svc.url && svc.port) return `${svc.url}:${svc.port}`
  return svc.url ?? '—'
}

onMounted(() => void fetchServices())
</script>

<template>
  <div class="mon">
    <div class="mon-head">
      <h3>Monitoring Checks</h3>
    </div>

    <div v-if="loading && !services.length" class="skeleton-wrap">
      <div class="skeleton-row" v-for="i in 4" :key="i" />
    </div>

    <EmptyState
      v-else-if="!loading && !services.length"
      title="No monitoring checks"
      message="Register checks for this server on the Services page."
    />

    <div class="table-wrap" v-else>
      <table class="mon-table">
        <thead>
          <tr>
            <th class="t-name">Name</th>
            <th class="t-type">Type</th>
            <th class="t-url">URL / Host</th>
            <th class="t-status">Status</th>
            <th class="t-uptime">Uptime 24h</th>
            <th class="t-resp">Avg Response</th>
            <th class="t-actions"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="svc in services" :key="svc.id" :class="{ 'row-confirming': confirmingId === svc.id }">
            <td class="t-name">{{ svc.name }}</td>
            <td class="t-type"><span class="type-pill" :class="`type-${svc.type}`">{{ svc.type.toUpperCase() }}</span></td>
            <td class="t-url url-cell">{{ formatUrl(svc) }}</td>
            <td class="t-status">
              <StatusBadge :status="svc.last_status ?? 'unknown'" kind="service" />
            </td>
            <td class="t-uptime">{{ formatUptime(svc.uptime_24h) }}</td>
            <td class="t-resp">{{ formatResponse(svc.avg_response_ms_24h) }}</td>
            <td class="t-actions">
              <template v-if="confirmingId === svc.id">
                <span class="confirm-text">Delete?</span>
                <button
                  class="btn-confirm"
                  :disabled="deletingId === svc.id"
                  @click="confirmDelete(svc.id)"
                >{{ deletingId === svc.id ? '…' : 'Yes' }}</button>
                <button class="btn-cancel" @click="cancelConfirm">No</button>
                <span v-if="deleteError === svc.id" class="err-text">Failed</span>
              </template>
              <button v-else class="btn-delete" title="Delete check" @click="startConfirm(svc.id)">
                <va-icon name="delete" size="small" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.mon { display: flex; flex-direction: column; gap: 1rem; }
.mon-head h3 { font-size: 0.9rem; font-weight: 600; color: var(--va-text-secondary); text-transform: uppercase; letter-spacing: 0.05em; margin: 0; }

.skeleton-wrap { display: flex; flex-direction: column; gap: 0.5rem; }
.skeleton-row { height: 2.5rem; border-radius: 0.375rem; background: var(--va-background-secondary); animation: pulse 1.5s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

.table-wrap { overflow-x: auto; }
.mon-table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
.mon-table th { padding: 0.5rem 0.75rem; text-align: left; font-size: 0.75rem; font-weight: 600; color: var(--va-text-secondary); text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid var(--va-background-secondary); white-space: nowrap; }
.mon-table td { padding: 0.625rem 0.75rem; border-bottom: 1px solid rgba(255,255,255,0.05); vertical-align: middle; }
.mon-table tbody tr:hover { background: rgba(255,255,255,0.03); }
.row-confirming td { background: rgba(239,68,68,0.05); }

.t-name { min-width: 120px; font-weight: 500; }
.t-type { width: 70px; }
.t-url { min-width: 160px; }
.t-status { width: 90px; }
.t-uptime { width: 90px; }
.t-resp { width: 110px; }
.t-actions { width: 120px; text-align: right; white-space: nowrap; }

.url-cell { font-family: monospace; font-size: 0.8rem; color: var(--va-text-secondary); max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.type-pill { display: inline-block; padding: 0.15rem 0.45rem; border-radius: 0.25rem; font-size: 0.7rem; font-weight: 700; letter-spacing: 0.05em; }
.type-http { background: rgba(59,130,246,0.2); color: #60a5fa; }
.type-tcp  { background: rgba(168,85,247,0.2); color: #c084fc; }
.type-db   { background: rgba(234,179,8,0.2);  color: #facc15; }

.btn-delete { background: none; border: none; cursor: pointer; color: var(--va-text-secondary); padding: 0.25rem; border-radius: 0.25rem; transition: color 0.15s; }
.btn-delete:hover { color: #ef4444; }

.confirm-text { font-size: 0.8rem; color: var(--va-text-secondary); margin-right: 0.4rem; }
.btn-confirm { background: #ef4444; border: none; color: #fff; font-size: 0.75rem; padding: 0.2rem 0.55rem; border-radius: 0.25rem; cursor: pointer; margin-right: 0.25rem; }
.btn-confirm:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-cancel  { background: none; border: 1px solid var(--va-background-secondary); color: var(--va-text-secondary); font-size: 0.75rem; padding: 0.2rem 0.55rem; border-radius: 0.25rem; cursor: pointer; }
.err-text { font-size: 0.75rem; color: #ef4444; margin-left: 0.4rem; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/servers/tabs/MonitoringTab.vue
git commit -m "feat(frontend): add MonitoringTab component for server-scoped monitoring checks"
```

---

## Task 4: Wire MonitoringTab into ServerDetail.vue

**Files:**
- Modify: `frontend/src/views/servers/ServerDetail.vue`

- [ ] **Step 1: Add import**

Find the existing tab imports block (around line 7-15) and add:

```ts
import MonitoringTab from '@/components/servers/tabs/MonitoringTab.vue'
```

- [ ] **Step 2: Add to TABS and TAB_COMPONENTS**

Find this line (~line 40):
```ts
const TABS = ['Info', 'Overview', 'CPU', 'Memory', 'Disk', 'Network', 'System', 'Processes', 'Services'] as const
```
Change to:
```ts
const TABS = ['Info', 'Overview', 'CPU', 'Memory', 'Disk', 'Network', 'System', 'Processes', 'Services', 'Monitoring'] as const
```

Find the `TAB_COMPONENTS` object (~line 42-46) and add `Monitoring`:
```ts
const TAB_COMPONENTS = {
  Info: InfoTab, Overview: OverviewTab, CPU: CpuTab, Memory: MemoryTab,
  Disk: DiskTab, Network: NetworkTab, System: SystemTab, Processes: ProcessesTab,
  Services: ServicesTab, Monitoring: MonitoringTab,
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/servers/ServerDetail.vue
git commit -m "feat(frontend): wire MonitoringTab into ServerDetail tabs"
```

---

## Task 5: Smoke Test + Dashboard Update + Push

- [ ] **Step 1: Verify the tab appears**

Open `http://localhost:9090/servers` → click any server → confirm "Monitoring" tab is visible in the tab bar.

- [ ] **Step 2: Verify empty state**

Click the Monitoring tab on a server with no monitoring checks registered → EmptyState renders with "No monitoring checks" message.

- [ ] **Step 3: Verify list renders**

Go to the Services page and register at least one HTTP check for this server. Return to server detail → Monitoring tab → confirm the check appears in the table with correct name, type pill, URL, status badge, uptime, and response.

- [ ] **Step 4: Verify delete**

Click the delete icon on a row → "Delete? Yes / No" appears inline (no modal). Click "Yes" → row disappears. Verify the check is also gone from the main Services page.

- [ ] **Step 5: Update PROGRESS.md and DASHBOARD.html**

In `PROGRESS.md`, add a ✅ entry for the Monitoring tab feature.

In `DASHBOARD.html`, find the matching task entry in the `phases` data array and change `status: 'pending'` to `status: 'done'`. Update `LAST_UPDATED` to `2026-06-04`.

- [ ] **Step 6: Final commit and push**

```bash
git add PROGRESS.md DASHBOARD.html
git commit -m "feat(server-detail): add Monitoring tab — server-scoped HTTP/TCP check list with delete"
git push origin main
```
