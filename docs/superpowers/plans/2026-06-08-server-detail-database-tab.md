# Server Detail — Database Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only "Database" tab to the server detail page that shows the database health dashboard for all DB instances linked to that server, reusing existing store and components.

**Architecture:** A new `DatabaseTab.vue` component follows the `BackupTab` pattern — it uses `route.params.id` for the server ID, calls `store.fetchCredentials(orgId)` on mount (idempotent cache), and renders `DbHealthDashboard` with `canEdit=false`. The instance pill bar is copied from `DatabasesView` but without the "+ Add Instance" button. `ServerDetail.vue` is updated to include the new tab.

**Tech Stack:** Vue 3 + Pinia (TypeScript), existing `useDatabaseStore`, existing `DbHealthDashboard` and `EmptyState` components

---

## File Map

| File | Change |
|---|---|
| `frontend/src/components/servers/tabs/DatabaseTab.vue` | **Create** — new tab component |
| `frontend/src/views/servers/ServerDetail.vue` | **Modify** — add import, tab entry, component mapping |

---

### Task 1: Create `DatabaseTab.vue`

**Files:**
- Create: `frontend/src/components/servers/tabs/DatabaseTab.vue`

- [ ] **Step 1: Create the file with the full component**

Create `frontend/src/components/servers/tabs/DatabaseTab.vue` with this exact content:

```vue
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useOrgStore } from '@/stores/org'
import { useDatabaseStore } from '@/stores/databases'
import type { DbInstanceStatus } from '@/stores/databases'
import { EmptyState } from '@/components/ui'
import DbHealthDashboard from '@/components/databases/DbHealthDashboard.vue'

const route = useRoute()
const orgStore = useOrgStore()
const store = useDatabaseStore()

const serverId = computed(() => route.params.id as string)
const orgId = computed(() => orgStore.activeOrgId)

const serverEntry = computed(() => store.serverFor(serverId.value))
const instances = computed(() => serverEntry.value?.instances ?? [])
const selectedInstanceId = ref<string | null>(null)
const selectedInstance = computed(
  () => instances.value.find((i) => i.credential_id === selectedInstanceId.value) ?? null,
)

function selectInstance(credentialId: string) {
  selectedInstanceId.value = credentialId
}

function instanceDot(inst: DbInstanceStatus): string {
  if (inst.last_check_ok === false) return '⚠'
  if (inst.last_check_ok == null) return '◐'
  return '●'
}

function instanceDotClass(inst: DbInstanceStatus): string {
  if (inst.last_check_ok === false) return 'warn'
  if (inst.last_check_ok == null) return 'pending'
  return 'ok'
}

let pollTimer: ReturnType<typeof setInterval> | null = null

function hasPending(): boolean {
  return instances.value.some((i) => i.last_check_ok == null)
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    if (!orgId.value) return
    await store.fetchCredentials(orgId.value)
    if (!hasPending()) stopPolling()
  }, 10_000)
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

async function load() {
  if (!orgId.value) return
  await store.fetchCredentials(orgId.value)
  const best =
    instances.value.find((i) => i.last_check_ok === true) ??
    instances.value.find((i) => i.last_check_ok == null) ??
    instances.value[0]
  if (best) selectedInstanceId.value = best.credential_id
  if (hasPending()) startPolling()
}

onMounted(load)
onUnmounted(stopPolling)

const DB_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/></svg>`
</script>

<template>
  <div class="db-tab">
    <div v-if="store.loadingCredentials" class="loading">Loading database info…</div>

    <EmptyState
      v-else-if="!instances.length"
      :icon="DB_ICON"
      title="No database monitoring configured"
      message="Set up credentials from the Databases page to monitor this server's database instances."
    />

    <template v-else>
      <div v-if="instances.length > 1" class="inst-bar">
        <button
          v-for="inst in instances" :key="inst.credential_id"
          class="inst-pill"
          :class="{ active: inst.credential_id === selectedInstanceId }"
          type="button"
          @click="selectInstance(inst.credential_id)"
        >
          <span class="inst-dot" :class="instanceDotClass(inst)">{{ instanceDot(inst) }}</span>
          {{ inst.label }}
        </button>
      </div>

      <DbHealthDashboard
        v-if="selectedInstance"
        :key="`hd-${selectedInstance.credential_id}`"
        :server-id="serverId"
        :server-name="serverEntry?.server_name ?? ''"
        :status="selectedInstance"
        :can-edit="false"
        :db-type="selectedInstance.db_type"
        :credential-id="selectedInstance.credential_id"
      />
    </template>
  </div>
</template>

<style scoped>
.db-tab { padding: 4px 0; }
.loading { color: var(--muted); font-size: 13px; padding: 40px 0; text-align: center; }
.inst-bar {
  display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px; align-items: center;
}
.inst-pill {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--surface-2); border: 1px solid var(--border); color: var(--muted);
  font-size: 12px; font-weight: 500; padding: 5px 12px; border-radius: 20px; cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}
.inst-pill:hover { border-color: var(--accent); color: var(--text); }
.inst-pill.active { background: rgba(99,102,241,0.15); border-color: var(--accent); color: #fff; }
.inst-dot { font-size: 10px; }
.inst-dot.ok { color: var(--green); }
.inst-dot.warn { color: var(--amber); }
.inst-dot.pending { color: var(--accent-2); }
</style>
```

- [ ] **Step 2: TypeScript check**

```bash
cd /Users/pocketdata/Code/Work/opspilot/frontend && npx vue-tsc --noEmit 2>&1 | grep "DatabaseTab" | head -10
```

Expected: no output (zero errors in the new file).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/servers/tabs/DatabaseTab.vue
git commit -m "feat(db): add read-only DatabaseTab component for server detail"
```

---

### Task 2: Wire `DatabaseTab` into `ServerDetail.vue`

**Files:**
- Modify: `frontend/src/views/servers/ServerDetail.vue`

- [ ] **Step 1: Add the import**

In `frontend/src/views/servers/ServerDetail.vue`, find the block of tab imports (lines importing `BackupTab`, `AlertsTab`, etc.) and add:

```typescript
import DatabaseTab from '@/components/servers/tabs/DatabaseTab.vue'
```

- [ ] **Step 2: Add "Database" to the TABS array**

Find this line:

```typescript
const TABS = ['Info', 'Overview', 'CPU', 'Memory', 'Disk', 'Network', 'System', 'Processes', 'Services', 'Monitoring', 'Alerts', 'Logs', 'Backup'] as const
```

Replace it with:

```typescript
const TABS = ['Info', 'Overview', 'CPU', 'Memory', 'Disk', 'Network', 'System', 'Processes', 'Services', 'Database', 'Monitoring', 'Alerts', 'Logs', 'Backup'] as const
```

- [ ] **Step 3: Add `DatabaseTab` to `TAB_COMPONENTS`**

Find this block:

```typescript
const TAB_COMPONENTS = {
  Info: InfoTab, Overview: OverviewTab, CPU: CpuTab, Memory: MemoryTab,
  Disk: DiskTab, Network: NetworkTab, System: SystemTab, Processes: ProcessesTab,
  Services: ServicesTab, Monitoring: MonitoringTab, Alerts: AlertsTab, Logs: LogsTab,
  Backup: BackupTab,
}
```

Replace it with:

```typescript
const TAB_COMPONENTS = {
  Info: InfoTab, Overview: OverviewTab, CPU: CpuTab, Memory: MemoryTab,
  Disk: DiskTab, Network: NetworkTab, System: SystemTab, Processes: ProcessesTab,
  Services: ServicesTab, Database: DatabaseTab, Monitoring: MonitoringTab,
  Alerts: AlertsTab, Logs: LogsTab, Backup: BackupTab,
}
```

- [ ] **Step 4: TypeScript check — expect zero errors**

```bash
cd /Users/pocketdata/Code/Work/opspilot/frontend && npx vue-tsc --noEmit 2>&1 | head -10
```

Expected: no output.

- [ ] **Step 5: Smoke test in browser**

1. Open `http://localhost:9090/servers`
2. Click on a server that has database credentials configured (e.g., lima-ubuntu)
3. Confirm a "Database" tab appears in the tab strip between "Services" and "Monitoring"
4. Click "Database" tab
5. Confirm the health dashboard loads showing the correct instance (mysql:3306 or the configured label)
6. If the server has multiple DB instances, confirm the pill bar appears and switching pills updates the dashboard
7. Confirm there are NO Edit Credentials, Remove, or Copy Password buttons
8. Click another server that has NO database credentials
9. Click "Database" tab — confirm the empty state shows ("No database monitoring configured")
10. Confirm the range selector strip (1h/6h/24h/7d/30d) still appears in the tab bar header from `ServerDetail` (it's inherited from the layout — `DatabaseTab` ignores the `range` prop but that's fine)

- [ ] **Step 6: Commit and push**

```bash
git add frontend/src/views/servers/ServerDetail.vue
git commit -m "feat(db): wire Database tab into server detail page"
git push origin main
```
