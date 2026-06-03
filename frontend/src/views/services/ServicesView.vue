<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { PageHeader, EmptyState } from '@/components/ui'
import ServiceRow from '@/components/services/ServiceRow.vue'
import ServiceModal from '@/components/services/ServiceModal.vue'
import { useAuthStore } from '@/stores/auth'
import { useOrgStore } from '@/stores/org'
import { useServerStore } from '@/stores/server'
import { useServiceStore } from '@/stores/services'
import { useNotify } from '@/composables/useNotify'
import { wsClient } from '@/utils/ws'
import { getApiError } from '@/services/api'
import type { Service } from '@/stores/services'

const auth = useAuthStore()
const orgStore = useOrgStore()
const serverStore = useServerStore()
const store = useServiceStore()
const notify = useNotify()
const router = useRouter()

const canEdit = computed(() => orgStore.canEdit)

// ── Filters ──────────────────────────────────────────────────────────────────
const filterServer = ref<string>('all')
const filterType = ref<string>('all')
const filterStatus = ref<string>('all')
const search = ref('')
const debouncedSearch = ref('')
let searchTimer: number | null = null
watch(search, (v) => {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => { debouncedSearch.value = v.trim().toLowerCase() }, 300)
})

const serverOptions = computed(() =>
  serverStore.servers.map((s) => ({ id: s.id, name: s.name, status: s.status })),
)

const filtered = computed(() => {
  let list = store.sortedServices
  if (filterServer.value !== 'all') list = list.filter((s) => s.server_id === filterServer.value)
  if (filterType.value !== 'all') list = list.filter((s) => s.type === filterType.value)
  if (filterStatus.value !== 'all') {
    list = list.filter((s) => {
      if (filterStatus.value === 'up') return s.last_status === 'up'
      if (filterStatus.value === 'down') return s.last_status === 'down'
      return s.last_status == null
    })
  }
  const q = debouncedSearch.value
  if (q) {
    list = list.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        (s.url ?? '').toLowerCase().includes(q) ||
        s.server_name.toLowerCase().includes(q),
    )
  }
  return list
})

const summary = computed(() => {
  const total = store.services.length
  const down = store.downServices.length
  const parts = [`${total} service${total === 1 ? '' : 's'}`]
  if (down) parts.push(`${down} down`)
  return parts.join(' • ')
})

// ── Modal + menu ─────────────────────────────────────────────────────────────
const modalOpen = ref(false)
const editing = ref<Service | null>(null)
const openMenuId = ref<string | null>(null)

function openAdd() {
  editing.value = null
  modalOpen.value = true
}
function openEdit(s: Service) {
  editing.value = s
  openMenuId.value = null
  modalOpen.value = true
}
function onSaved(s: Service) {
  notify.success(editing.value ? `Service "${s.name}" updated` : `Service "${s.name}" added`)
}

async function confirmDelete(s: Service) {
  openMenuId.value = null
  if (!window.confirm(`Delete "${s.name}"? This permanently removes all check history, incidents, and linked alert rules.`)) return
  try {
    await store.deleteService(s.id)
    notify.success(`Service "${s.name}" deleted`)
  } catch (err) {
    notify.error(getApiError(err)?.message ?? 'Could not delete service.')
  }
}

function openDetail(s: Service) {
  void router.push(`/services/${s.id}`)
}

// ── Data + WebSocket ─────────────────────────────────────────────────────────
let unbindWs: (() => void) | null = null
let subscribedOrg: string | null = null

async function load() {
  const orgId = orgStore.activeOrgId
  if (!orgId) { store.services = []; return }
  await Promise.all([
    store.fetchServices(orgId),
    serverStore.servers.length ? Promise.resolve() : serverStore.fetchByOrg(orgId),
  ])
  subscribeWs(orgId)
}

function subscribeWs(orgId: string) {
  if (subscribedOrg === orgId) return
  if (subscribedOrg) wsClient.send({ action: 'unsubscribe_org', org_id: subscribedOrg })
  wsClient.send({ action: 'subscribe_org', org_id: orgId })
  subscribedOrg = orgId
}

function bindWs() {
  unbindWs = wsClient.on((msg: any) => {
    if (msg?.event === 'service_check') store.handleCheckEvent(msg.data)
    else if (msg?.event === 'incident_opened') store.handleIncidentOpened(msg.data)
    else if (msg?.event === 'incident_resolved') store.handleIncidentResolved(msg.data)
  })
}

onMounted(() => {
  bindWs()
  void load()
})

watch(() => orgStore.activeOrgId, () => {
  serverStore.servers = []
  void load()
})

onUnmounted(() => {
  if (subscribedOrg) wsClient.send({ action: 'unsubscribe_org', org_id: subscribedOrg })
  unbindWs?.()
})
</script>

<template>
  <div class="page" @click="openMenuId = null">
    <PageHeader title="Services" :subtitle="summary">
      <template #actions>
        <button v-if="canEdit && serverStore.servers.length" class="primary" @click="openAdd">+ Add Service</button>
      </template>
    </PageHeader>

    <!-- No servers in org -->
    <EmptyState
      v-if="serverStore.servers.length === 0 && store.services.length === 0 && !store.isLoadingList"
      title="Add a server first"
      message="Services are attached to servers. Add a server before monitoring services."
    >
      <template #action>
        <router-link to="/servers" class="primary">Go to Servers</router-link>
      </template>
    </EmptyState>

    <!-- Empty state -->
    <EmptyState
      v-else-if="store.services.length === 0 && !store.isLoadingList"
      title="No services added yet"
      message="Add services to monitor uptime and response times for your web apps, APIs, and database ports."
    >
      <template #action>
        <button v-if="canEdit" class="primary" @click="openAdd">+ Add Your First Service</button>
      </template>
    </EmptyState>

    <template v-else>
      <p v-if="store.allPaused" class="banner amber">All services are paused — no checks running.</p>

      <div class="filters">
        <select v-model="filterServer">
          <option value="all">All Servers</option>
          <option v-for="s in serverOptions" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
        <select v-model="filterType">
          <option value="all">All Types</option>
          <option value="http">HTTP</option>
          <option value="tcp">TCP</option>
          <option value="db">DB Port</option>
        </select>
        <select v-model="filterStatus">
          <option value="all">All Status</option>
          <option value="up">Up</option>
          <option value="down">Down</option>
          <option value="unknown">Unknown</option>
        </select>
        <input v-model="search" class="search" placeholder="Search services…" />
      </div>

      <div v-if="filtered.length" class="list">
        <ServiceRow
          v-for="s in filtered"
          :key="s.id"
          :service="s"
          :can-edit="canEdit"
          :menu-open="openMenuId === s.id"
          @open="openDetail(s)"
          @toggle-menu="openMenuId = openMenuId === s.id ? null : s.id"
          @edit="openEdit(s)"
          @delete="confirmDelete(s)"
        />
      </div>
      <p v-else class="banner muted">No services match the current filters.</p>
    </template>

    <ServiceModal
      v-model="modalOpen"
      :service="editing"
      :servers="serverOptions"
      @saved="onSaved"
    />
  </div>
</template>

<style scoped>
.page { padding: 28px; }
.filters { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
.filters select, .search { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 9px 12px; color: var(--text); font-size: 13px; outline: none; }
.filters select:focus, .search:focus { border-color: var(--accent); }
.search { flex: 1; min-width: 200px; }
.list { display: flex; flex-direction: column; gap: 10px; }
.banner { font-size: 13px; padding: 12px 16px; border-radius: 8px; }
.banner.amber { background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.25); color: var(--amber); margin-bottom: 14px; }
.banner.muted { color: var(--muted); text-align: center; padding: 40px; }
.primary { padding: 9px 18px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); color: #fff; border: none; border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; gap: 8px; min-height: 38px; }
</style>
