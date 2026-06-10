<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { PageHeader, EmptyState } from '@/components/ui'
import { useOrgStore } from '@/stores/org'
import { useNotify } from '@/composables/useNotify'
import { useDatabaseStore } from '@/stores/databases'
import type { DbCredentialPayload, DbInstanceStatus } from '@/stores/databases'
import DbNoCredentials from '@/components/databases/DbNoCredentials.vue'
import DbCredentialModal from '@/components/databases/DbCredentialModal.vue'
import DbHealthDashboard from '@/components/databases/DbHealthDashboard.vue'
import DbInfoPanel from '@/components/databases/DbInfoPanel.vue'

const orgStore = useOrgStore()
const store = useDatabaseStore()
const notify = useNotify()

const orgId = computed(() => orgStore.activeOrgId)
const canEdit = computed(() => orgStore.canEdit)

const selectedId = ref<string | null>(null)
const selectedInstanceId = ref<string | null>(null)
const modalOpen = ref(false)
const editingInstance = ref<DbInstanceStatus | null>(null)
const confirmRemove = ref(false)
const removingInstance = ref<DbInstanceStatus | null>(null)
const activePanel = ref<'metrics' | 'info'>('metrics')

const servers = computed(() => store.servers)
const selected = computed(() => servers.value.find((s) => s.server_id === selectedId.value) ?? null)
const selectedInstance = computed(
  () => selected.value?.instances.find((i) => i.credential_id === selectedInstanceId.value) ?? null,
)

const DB_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/></svg>`

function serverBadge(s: typeof servers.value[0]) {
  if (!s.instances.length) return { glyph: '—', tone: 'muted', title: 'No credentials configured' }
  if (s.instances.some((i) => i.last_check_ok === false)) return { glyph: '⚠', tone: 'warn', title: 'Connection error' }
  if (s.instances.every((i) => i.last_check_ok == null)) return { glyph: '◐', tone: 'pending', title: 'Deploying / awaiting first check' }
  return { glyph: '✓', tone: 'ok', title: 'Connected' }
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

function selectInstance(credentialId: string) {
  selectedInstanceId.value = credentialId
}

function selectServer(id: string) {
  selectedId.value = id
  const srv = servers.value.find((s) => s.server_id === id)
  if (!srv || !srv.instances.length) { selectedInstanceId.value = null; return }
  // prefer connected → pending → first
  const connected = srv.instances.find((i) => i.last_check_ok === true)
  const pending = srv.instances.find((i) => i.last_check_ok == null)
  selectedInstanceId.value = (connected ?? pending ?? srv.instances[0]).credential_id
}

async function load() {
  if (!orgId.value) return
  await store.fetchCredentials(orgId.value)
  // Auto-select first server with instances, else first server
  const withCreds = servers.value.find((s) => s.instances.length > 0)
  const target = withCreds ?? servers.value[0]
  if (target) selectServer(target.server_id)
  if (hasPending()) startPolling()
}

// Poll while any instance is awaiting first check
let pollTimer: ReturnType<typeof setInterval> | null = null

function hasPending(): boolean {
  return servers.value.some((s) => s.instances.some((i) => i.last_check_ok == null))
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

onMounted(load)
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => {
  stopPolling()
  window.removeEventListener('keydown', onKey)
})

watch(orgId, () => {
  stopPolling()
  store.reset()
  selectedId.value = null
  selectedInstanceId.value = null
  void load()
})

watch(selectedInstanceId, () => { activePanel.value = 'metrics' })

// Keyboard: ← / → between server tabs
function onKey(e: KeyboardEvent) {
  if (modalOpen.value || confirmRemove.value) return
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
  const idx = servers.value.findIndex((s) => s.server_id === selectedId.value)
  if (idx < 0) return
  const next = e.key === 'ArrowRight' ? idx + 1 : idx - 1
  if (next >= 0 && next < servers.value.length) selectServer(servers.value[next].server_id)
}

function openAddInstance() {
  editingInstance.value = null
  modalOpen.value = true
}

function openEditInstance(inst: DbInstanceStatus) {
  editingInstance.value = inst
  modalOpen.value = true
}

async function onSave(payload: DbCredentialPayload, credentialId: string | null) {
  if (!selectedId.value) return
  try {
    await store.saveCredentials(selectedId.value, payload, credentialId)
    modalOpen.value = false
    notify.success(credentialId ? 'Credentials updated.' : 'DB instance added. Re-deploying Telegraf…')
    if (orgId.value) await store.fetchCredentials(orgId.value)
    if (hasPending()) startPolling()
    // select the newly added instance (last one on server)
    if (!credentialId) {
      const srv = servers.value.find((s) => s.server_id === selectedId.value)
      if (srv?.instances.length) {
        selectedInstanceId.value = srv.instances[srv.instances.length - 1].credential_id
      }
    }
  } catch (err) {
    notify.error(err as Error, { title: 'Could not save credentials' })
  }
}

function promptRemove(inst: DbInstanceStatus) {
  removingInstance.value = inst
  confirmRemove.value = true
}

async function onRemove() {
  if (!selectedId.value || !removingInstance.value) return
  try {
    await store.deleteCredentials(selectedId.value, removingInstance.value.credential_id)
    confirmRemove.value = false
    removingInstance.value = null
    notify.success('DB instance removed. Re-deploying Telegraf…')
    if (orgId.value) await store.fetchCredentials(orgId.value)
    // re-select first instance on server
    const srv = servers.value.find((s) => s.server_id === selectedId.value)
    selectedInstanceId.value = srv?.instances[0]?.credential_id ?? null
  } catch (err) {
    notify.error(err as Error, { title: 'Could not remove instance' })
  }
}
</script>

<template>
  <div class="page">
    <PageHeader title="Database Monitoring" subtitle="MariaDB & PostgreSQL health metrics per server" />

    <EmptyState
      v-if="!store.loadingCredentials && !servers.length"
      :icon="DB_ICON"
      title="No servers to monitor"
      message="Add and onboard a server before configuring database monitoring."
    >
      <template #action>
        <router-link to="/" class="link-btn">Go to Dashboard</router-link>
      </template>
    </EmptyState>

    <template v-else>
      <!-- Server tab strip -->
      <div class="tab-strip" role="tablist" aria-label="Servers">
        <button
          v-for="s in servers" :key="s.server_id"
          class="srv-tab" :class="{ active: s.server_id === selectedId }"
          role="tab" :aria-selected="s.server_id === selectedId"
          type="button" @click="selectServer(s.server_id)"
        >
          <span class="srv-name">{{ s.server_name }}</span>
          <span class="srv-badge" :class="serverBadge(s).tone" :title="serverBadge(s).title">
            {{ serverBadge(s).glyph }}
          </span>
        </button>
      </div>

      <div class="content" v-if="selected">
        <!-- Instance pill bar (only when at least one instance exists) -->
        <div v-if="selected.instances.length" class="inst-bar">
          <button
            v-for="inst in selected.instances" :key="inst.credential_id"
            class="inst-pill"
            :class="{ active: inst.credential_id === selectedInstanceId }"
            type="button"
            @click="selectInstance(inst.credential_id)"
          >
            <span class="inst-dot" :class="instanceDotClass(inst)">{{ instanceDot(inst) }}</span>
            {{ inst.label }}
          </button>
          <button v-if="canEdit" class="inst-pill add-pill" type="button" @click="openAddInstance">
            + Add Instance
          </button>
        </div>

        <!-- No credentials yet -->
        <DbNoCredentials
          v-if="!selected.instances.length"
          :key="`nc-${selected.server_id}`"
          :server-name="selected.server_name"
          :can-edit="canEdit"
          db-type="mysql"
          @setup="openAddInstance"
        />

        <!-- Metrics / Info tab bar -->
        <div v-else-if="selectedInstance" class="panel-tabs">
          <button
            class="panel-tab" :class="{ active: activePanel === 'metrics' }"
            type="button" @click="activePanel = 'metrics'"
          >Metrics</button>
          <button
            class="panel-tab" :class="{ active: activePanel === 'info' }"
            type="button" @click="activePanel = 'info'"
          >Info</button>
        </div>

        <!-- Health dashboard for selected instance -->
        <DbHealthDashboard
          v-if="selectedInstance && activePanel === 'metrics'"
          :key="`hd-${selectedInstance.credential_id}`"
          :server-id="selected.server_id"
          :server-name="selected.server_name"
          :status="selectedInstance"
          :can-edit="canEdit"
          :db-type="selectedInstance.db_type"
          :credential-id="selectedInstance.credential_id"
          @edit="openEditInstance(selectedInstance)"
          @remove="promptRemove(selectedInstance)"
        />

        <!-- Info panel for selected instance -->
        <DbInfoPanel
          v-else-if="selectedInstance && activePanel === 'info'"
          :key="`info-${selectedInstance.credential_id}`"
          :server-id="selected.server_id"
          :credential-id="selectedInstance.credential_id"
        />
      </div>
    </template>

    <!-- Credential modal -->
    <DbCredentialModal
      v-model="modalOpen"
      :server-name="selected?.server_name ?? ''"
      :existing="editingInstance"
      @save="onSave"
    />

    <!-- Remove confirmation -->
    <Teleport to="body">
      <div v-if="confirmRemove" class="confirm-scrim" @click.self="confirmRemove = false; removingInstance = null">
        <div class="confirm" role="alertdialog" aria-modal="true">
          <h3 class="cf-title">Remove {{ removingInstance?.label }} from {{ selected?.server_name }}?</h3>
          <ul class="cf-list">
            <li>Remove stored credentials for this instance</li>
            <li>Remove this input block from Telegraf config (re-deploy required)</li>
            <li>Stop collecting metrics for this instance (history retained)</li>
          </ul>
          <div class="cf-actions">
            <button class="btn ghost" type="button" @click="confirmRemove = false">Cancel</button>
            <button class="btn danger" type="button" @click="onRemove">Remove</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.page { padding: 28px; max-width: 1300px; }
.link-btn {
  display: inline-block; background: var(--accent); color: #fff; text-decoration: none;
  padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600;
}
.tab-strip {
  display: flex; gap: 6px; flex-wrap: wrap; border-bottom: 1px solid var(--border);
  padding-bottom: 14px; margin-bottom: 20px;
}
.srv-tab {
  display: inline-flex; align-items: center; gap: 8px;
  background: var(--surface-2); border: 1px solid var(--border); color: var(--text);
  font-size: 13px; padding: 8px 14px; border-radius: 8px; cursor: pointer; min-height: 38px;
  transition: border-color 0.15s, background 0.15s;
}
.srv-tab:hover { border-color: var(--accent); }
.srv-tab.active { background: rgba(99,102,241,0.15); border-color: var(--accent); color: #fff; }
.srv-name { font-weight: 500; }
.srv-badge {
  display: inline-flex; align-items: center; justify-content: center;
  width: 18px; height: 18px; border-radius: 50%; font-size: 11px; font-weight: 700;
}
.srv-badge.ok { background: rgba(34,197,94,0.18); color: var(--green); }
.srv-badge.warn { background: rgba(245,158,11,0.18); color: var(--amber); }
.srv-badge.pending { background: rgba(99,102,241,0.18); color: var(--accent-2); }
.srv-badge.muted { background: rgba(107,114,128,0.2); color: var(--muted); }
.content { min-height: 300px; }

.confirm-scrim {
  position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 1200;
  display: flex; align-items: center; justify-content: center; padding: 20px;
}
.confirm {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 22px 24px; max-width: 440px; width: 100%; box-shadow: 0 24px 60px rgba(0,0,0,0.5);
}
.cf-title { font-size: 16px; color: #fff; margin-bottom: 12px; }
.cf-list { margin: 0 0 18px; padding-left: 18px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.cf-actions { display: flex; justify-content: flex-end; gap: 10px; }
.btn { border-radius: 8px; font-size: 13px; font-weight: 600; padding: 9px 16px; cursor: pointer; border: 1px solid transparent; min-height: 40px; }
.btn.ghost { background: var(--surface-2); border-color: var(--border); color: var(--text); }
.btn.ghost:hover { border-color: var(--accent); }
.btn.danger { background: var(--red); color: #fff; }
.btn.danger:hover { opacity: 0.92; }

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
.inst-pill.add-pill { border-style: dashed; }
.inst-dot { font-size: 10px; }
.inst-dot.ok { color: var(--green); }
.inst-dot.warn { color: var(--amber); }
.inst-dot.pending { color: var(--accent-2); }

.panel-tabs {
  display: flex; gap: 0; border-bottom: 1px solid var(--border);
  margin-bottom: 20px;
}
.panel-tab {
  padding: 9px 20px; font-size: 13px; font-weight: 600;
  color: var(--text-muted); background: none; border: none;
  border-bottom: 2px solid transparent; cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}
.panel-tab:hover { color: var(--text); }
.panel-tab.active { color: #60a5fa; border-bottom-color: #3b82f6; }
</style>
