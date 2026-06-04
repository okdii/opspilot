<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch, nextTick } from 'vue'
import { useOrgStore } from '@/stores/org'
import { useAuthStore } from '@/stores/auth'
import { useSslDomainStore, type CombinedRow } from '@/stores/sslDomains'
import { useNotify } from '@/composables/useNotify'
import { getApiError } from '@/services/api'
import { PageHeader, StatusBadge, EmptyState, SlideOver } from '@/components/ui'
import ExpiryBar from '@/components/ssl-domains/ExpiryBar.vue'
import ExpiryTimeline from '@/components/ssl-domains/ExpiryTimeline.vue'

const orgStore = useOrgStore()
const auth = useAuthStore()
const store = useSslDomainStore()
const notify = useNotify()

const canEdit = computed(() => auth.isAdmin)

// ── Load ──────────────────────────────────────────────────────────────────
async function load() {
  if (orgStore.activeOrgId) await store.fetchAll(orgStore.activeOrgId)
  else store.reset()
}
onMounted(load)
watch(() => orgStore.activeOrgId, load)
onUnmounted(() => store.reset())

// ── Filters + sort ──────────────────────────────────────────────────────────
const typeFilter = ref<'all' | 'domain' | 'ssl'>('all')
const statusFilter = ref<'all' | string>('all')
const search = ref('')
const debouncedSearch = ref('')
let searchTimer: ReturnType<typeof setTimeout> | undefined
watch(search, (v) => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => (debouncedSearch.value = v.trim().toLowerCase()), 300)
})

const sortKey = ref<'name' | 'type' | 'expiry' | 'days' | 'status'>('expiry')
const sortDir = ref<'asc' | 'desc'>('asc')
function toggleSort(key: typeof sortKey.value) {
  if (sortKey.value === key) sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  else {
    sortKey.value = key
    sortDir.value = 'asc'
  }
}

const filtered = computed<CombinedRow[]>(() => {
  let rows = store.combinedRows
  if (typeFilter.value !== 'all') rows = rows.filter((r) => r.type === typeFilter.value)
  if (statusFilter.value !== 'all') rows = rows.filter((r) => r.status === statusFilter.value)
  if (debouncedSearch.value) rows = rows.filter((r) => r.domainName.toLowerCase().includes(debouncedSearch.value))
  return rows
})

function rowName(r: CombinedRow): string {
  return r.type === 'ssl' ? `${r.domainName}:${r.port}` : r.domainName
}

const sorted = computed<CombinedRow[]>(() => {
  const rows = [...filtered.value]
  const dir = sortDir.value === 'asc' ? 1 : -1
  rows.sort((a, b) => {
    // Critical/expired float to top regardless of direction on default expiry sort.
    if (sortKey.value === 'expiry') {
      const ra = store.statusRank(a.status)
      const rb = store.statusRank(b.status)
      if ((ra <= 1 || rb <= 1) && ra !== rb) return ra - rb
    }
    let cmp = 0
    switch (sortKey.value) {
      case 'name':
        cmp = rowName(a).localeCompare(rowName(b))
        break
      case 'type':
        cmp = a.type.localeCompare(b.type)
        break
      case 'days': {
        const da = a.daysRemaining ?? Number.POSITIVE_INFINITY
        const db = b.daysRemaining ?? Number.POSITIVE_INFINITY
        cmp = da - db
        break
      }
      case 'status':
        cmp = store.statusRank(a.status) - store.statusRank(b.status)
        break
      case 'expiry':
      default: {
        const ea = a.expiryDate ? new Date(a.expiryDate).getTime() : Number.POSITIVE_INFINITY
        const eb = b.expiryDate ? new Date(b.expiryDate).getTime() : Number.POSITIVE_INFINITY
        cmp = ea - eb
      }
    }
    // Secondary group key: keep a domain's SSL row next to its domain row.
    if (cmp === 0) cmp = a.domainName.localeCompare(b.domainName) || (a.type === 'domain' ? -1 : 1)
    return cmp * dir
  })
  return rows
})

const summary = computed(() => {
  const parts = [`${store.combinedRows.length} items`]
  if (store.criticalCount) parts.push(`${store.criticalCount} critical`)
  if (store.expiringCount) parts.push(`${store.expiringCount} expiring`)
  return parts.join(' • ')
})

// ── Kebab + check-now transient state ─────────────────────────────────────
const openMenuId = ref<string | null>(null)
const checking = reactive<Record<string, boolean>>({})

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return iso.slice(0, 10)
}
function relTime(iso: string | null): string {
  if (!iso) return 'never'
  const diff = Date.now() - new Date(iso).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}
function daysLabel(r: CombinedRow): string {
  if (r.status === 'unreachable' || r.daysRemaining == null) return '—'
  return `${r.daysRemaining}`
}

async function checkNow(r: CombinedRow) {
  openMenuId.value = null
  if (!orgStore.activeOrgId) return
  checking[r.id] = true
  try {
    if (r.type === 'domain') await store.checkDomain(r.id)
    else await store.checkCert(r.id)
    notify.info(`Re-checking ${rowName(r)}… this may take a few seconds.`)
    await store.pollUntilChecked(orgStore.activeOrgId, r.type, r.id)
  } catch (err) {
    const apiErr = getApiError(err)
    if (apiErr?.error === 'rate_limited') {
      notify.warning('Check already in progress or recently completed.')
    } else {
      notify.error(apiErr?.message ?? 'Could not trigger a re-check.')
    }
  } finally {
    checking[r.id] = false
  }
}

// ── Add Domain modal ──────────────────────────────────────────────────────
const showDomainModal = ref(false)
const domainSubmitting = ref(false)
const domainForm = reactive({ domain: '', warn_days: 60, critical_days: 30 })
const domainErrors = reactive<Record<string, string>>({})
const normalisedDomain = computed(() => {
  let v = domainForm.domain.trim().toLowerCase()
  v = v.replace(/^https?:\/\//, '').replace(/^www\./, '').split('/')[0].trim()
  return v
})

function openAddDomain() {
  domainForm.domain = ''
  domainForm.warn_days = 60
  domainForm.critical_days = 30
  Object.keys(domainErrors).forEach((k) => delete domainErrors[k])
  showDomainModal.value = true
}

function validateDomain(): boolean {
  Object.keys(domainErrors).forEach((k) => delete domainErrors[k])
  if (!normalisedDomain.value) domainErrors.domain = 'Domain name is required'
  else if (!normalisedDomain.value.includes('.') || /\s/.test(normalisedDomain.value))
    domainErrors.domain = 'Enter a valid domain (e.g. example.com)'
  else if (store.domains.some((d) => d.domain === normalisedDomain.value))
    domainErrors.domain = `${normalisedDomain.value} is already tracked in this organisation.`
  if (domainForm.warn_days < 1 || domainForm.warn_days > 365) domainErrors.warn_days = '1–365'
  if (domainForm.critical_days < 1 || domainForm.critical_days >= domainForm.warn_days)
    domainErrors.critical_days = 'Critical threshold must be lower than warning threshold'
  return Object.keys(domainErrors).length === 0
}

async function submitDomain() {
  if (!validateDomain() || !orgStore.activeOrgId) return
  domainSubmitting.value = true
  try {
    const created = await store.addDomain({
      org_id: orgStore.activeOrgId,
      domain: normalisedDomain.value,
      warn_days: domainForm.warn_days,
      critical_days: domainForm.critical_days,
    })
    showDomainModal.value = false
    notify.success(`Tracking ${created.domain} — checking registration…`)
    void store.pollUntilChecked(orgStore.activeOrgId, 'domain', created.id)
  } catch (err) {
    domainErrors._form = getApiError(err)?.message ?? 'Unable to add domain.'
  } finally {
    domainSubmitting.value = false
  }
}

// ── Edit Domain modal ──────────────────────────────────────────────────────
const showEditDomain = ref(false)
const editDomainId = ref<string | null>(null)
const editDomainForm = reactive({ domain: '', warn_days: 60, critical_days: 30 })
const editDomainErrors = reactive<Record<string, string>>({})

function openEditDomain(r: CombinedRow) {
  openMenuId.value = null
  editDomainId.value = r.id
  editDomainForm.domain = r.domainName
  editDomainForm.warn_days = r.warnDays
  editDomainForm.critical_days = r.criticalDays
  Object.keys(editDomainErrors).forEach((k) => delete editDomainErrors[k])
  showEditDomain.value = true
}
async function submitEditDomain() {
  Object.keys(editDomainErrors).forEach((k) => delete editDomainErrors[k])
  if (editDomainForm.critical_days >= editDomainForm.warn_days) {
    editDomainErrors.critical_days = 'Critical threshold must be lower than warning threshold'
    return
  }
  if (!editDomainId.value) return
  try {
    await store.updateDomain(editDomainId.value, {
      warn_days: editDomainForm.warn_days,
      critical_days: editDomainForm.critical_days,
    })
    showEditDomain.value = false
    notify.success('Domain thresholds updated.')
  } catch (err) {
    editDomainErrors._form = getApiError(err)?.message ?? 'Unable to update domain.'
  }
}

// ── Add SSL modal ──────────────────────────────────────────────────────────
const showSslModal = ref(false)
const sslSubmitting = ref(false)
const sslParent = reactive({ domainId: '', domainName: '' })
const sslForm = reactive({ port: 443, warn_days: 30, critical_days: 7 })
const sslErrors = reactive<Record<string, string>>({})

function openAddSsl(r: CombinedRow) {
  openMenuId.value = null
  // r may be a domain row or a domain's empty-ssl slot row
  sslParent.domainId = r.type === 'domain' ? r.id : r.domainId ?? ''
  sslParent.domainName = r.domainName
  sslForm.port = 443
  sslForm.warn_days = 30
  sslForm.critical_days = 7
  Object.keys(sslErrors).forEach((k) => delete sslErrors[k])
  showSslModal.value = true
}

function validateSsl(): boolean {
  Object.keys(sslErrors).forEach((k) => delete sslErrors[k])
  if (sslForm.port < 1 || sslForm.port > 65535) sslErrors.port = 'Enter a valid port number'
  if (sslForm.warn_days < 1 || sslForm.warn_days > 365) sslErrors.warn_days = '1–365'
  if (sslForm.critical_days < 1 || sslForm.critical_days >= sslForm.warn_days)
    sslErrors.critical_days = 'Critical threshold must be lower than warning threshold'
  return Object.keys(sslErrors).length === 0
}

async function submitSsl() {
  if (!validateSsl() || !orgStore.activeOrgId || !sslParent.domainId) return
  sslSubmitting.value = true
  try {
    const created = await store.addCert({
      domain_id: sslParent.domainId,
      port: sslForm.port,
      warn_days: sslForm.warn_days,
      critical_days: sslForm.critical_days,
    })
    showSslModal.value = false
    notify.success(`Tracking SSL for ${sslParent.domainName}:${created.port} — checking…`)
    void store.pollUntilChecked(orgStore.activeOrgId, 'ssl', created.id)
  } catch (err) {
    sslErrors._form = getApiError(err)?.message ?? 'Unable to add SSL certificate.'
  } finally {
    sslSubmitting.value = false
  }
}

// ── Edit SSL modal ──────────────────────────────────────────────────────────
const showEditSsl = ref(false)
const editSslId = ref<string | null>(null)
const editSslForm = reactive({ name: '', port: 443, warn_days: 30, critical_days: 7 })
const editSslErrors = reactive<Record<string, string>>({})

function openEditSsl(r: CombinedRow) {
  openMenuId.value = null
  editSslId.value = r.id
  editSslForm.name = r.domainName
  editSslForm.port = r.port ?? 443
  editSslForm.warn_days = r.warnDays
  editSslForm.critical_days = r.criticalDays
  Object.keys(editSslErrors).forEach((k) => delete editSslErrors[k])
  showEditSsl.value = true
}
async function submitEditSsl() {
  Object.keys(editSslErrors).forEach((k) => delete editSslErrors[k])
  if (editSslForm.port < 1 || editSslForm.port > 65535) editSslErrors.port = 'Enter a valid port number'
  if (editSslForm.critical_days >= editSslForm.warn_days)
    editSslErrors.critical_days = 'Critical threshold must be lower than warning threshold'
  if (Object.keys(editSslErrors).length || !editSslId.value) return
  try {
    await store.updateCert(editSslId.value, {
      port: editSslForm.port,
      warn_days: editSslForm.warn_days,
      critical_days: editSslForm.critical_days,
    })
    showEditSsl.value = false
    notify.success('SSL certificate updated.')
  } catch (err) {
    editSslErrors._form = getApiError(err)?.message ?? 'Unable to update SSL certificate.'
  }
}

// ── Delete (confirm) ──────────────────────────────────────────────────────
const confirm = reactive<{
  open: boolean
  kind: 'domain' | 'ssl' | 'blocked'
  id: string
  name: string
}>({ open: false, kind: 'domain', id: '', name: '' })

function askDelete(r: CombinedRow) {
  openMenuId.value = null
  if (r.type === 'domain') {
    if (store.domainIdsWithCert.has(r.id)) {
      confirm.kind = 'blocked'
    } else {
      confirm.kind = 'domain'
    }
    confirm.id = r.id
    confirm.name = r.domainName
  } else {
    confirm.kind = 'ssl'
    confirm.id = r.id
    confirm.name = rowName(r)
  }
  confirm.open = true
}

async function doDelete() {
  try {
    if (confirm.kind === 'domain') await store.deleteDomain(confirm.id)
    else if (confirm.kind === 'ssl') await store.deleteCert(confirm.id)
    confirm.open = false
    notify.success('Deleted.')
  } catch (err) {
    notify.error(getApiError(err)?.message ?? 'Unable to delete.')
  }
}

// ── Timeline dot → scroll + highlight row ─────────────────────────────────
const highlightId = ref<string | null>(null)
async function onDotClick(id: string) {
  highlightId.value = id
  await nextTick()
  const el = document.getElementById(`row-${id}`)
  el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  setTimeout(() => (highlightId.value = null), 600)
}

// ── Keyboard shortcuts (spec §15) ─────────────────────────────────────────
const searchInput = ref<HTMLInputElement | null>(null)
function onKey(e: KeyboardEvent) {
  if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
    if (e.key === 'Escape') (e.target as HTMLElement).blur()
    return
  }
  if (e.key === 'n' && canEdit.value) {
    e.preventDefault()
    openAddDomain()
  } else if (e.key === 'r') {
    void load()
  } else if (e.key === '/') {
    e.preventDefault()
    searchInput.value?.focus()
  }
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="page" @click="openMenuId = null">
    <PageHeader title="SSL & Domain Monitoring" :subtitle="summary">
      <template #actions>
        <button class="ghost" title="Refresh (r)" @click="load">Refresh</button>
        <button v-if="canEdit" class="primary" @click="openAddDomain">+ Add Domain</button>
      </template>
    </PageHeader>

    <!-- Empty state -->
    <EmptyState
      v-if="!store.isLoading && store.combinedRows.length === 0"
      title="No domains tracked yet"
      message="Add domains to track WHOIS registration expiry and non-standard SSL certs (e.g. IMAPS:993). SSL for your HTTPS services is tracked automatically on the Services page."
    >
      <template #action>
        <button v-if="canEdit" class="primary" @click="openAddDomain">+ Add Your First Domain</button>
      </template>
    </EmptyState>

    <template v-else>
      <!-- Timeline -->
      <section v-if="store.timelineDots.length" class="panel">
        <h3 class="panel-title">Expiry Timeline</h3>
        <ExpiryTimeline :dots="store.timelineDots" @dot-click="onDotClick" />
      </section>

      <p class="page-hint">SSL for your HTTPS services is tracked automatically — add non-HTTP certs (e.g. IMAPS, SMTPS) here.</p>

      <!-- Filter bar -->
      <div class="filters">
        <select v-model="typeFilter">
          <option value="all">All Types</option>
          <option value="domain">Domain</option>
          <option value="ssl">SSL</option>
        </select>
        <select v-model="statusFilter">
          <option value="all">All Status</option>
          <option value="valid">Valid</option>
          <option value="expiring_soon">Expiring</option>
          <option value="critical">Critical</option>
          <option value="expired">Expired</option>
          <option value="unreachable">Unreachable</option>
        </select>
        <input ref="searchInput" v-model="search" class="search" placeholder="Search domains…  ( / )" />
      </div>

      <!-- Table -->
      <div class="table-wrap">
        <table class="grid">
          <thead>
            <tr>
              <th class="sortable" @click="toggleSort('name')">Name<span v-if="sortKey === 'name'" class="caret">{{ sortDir === 'asc' ? '▲' : '▼' }}</span></th>
              <th class="sortable" @click="toggleSort('type')">Type<span v-if="sortKey === 'type'" class="caret">{{ sortDir === 'asc' ? '▲' : '▼' }}</span></th>
              <th class="sortable" @click="toggleSort('expiry')">Expiry<span v-if="sortKey === 'expiry'" class="caret">{{ sortDir === 'asc' ? '▲' : '▼' }}</span></th>
              <th class="sortable num" @click="toggleSort('days')">Days Left<span v-if="sortKey === 'days'" class="caret">{{ sortDir === 'asc' ? '▲' : '▼' }}</span></th>
              <th class="bar-col">Progress</th>
              <th class="sortable" @click="toggleSort('status')">Status<span v-if="sortKey === 'status'" class="caret">{{ sortDir === 'asc' ? '▲' : '▼' }}</span></th>
              <th>Last Checked</th>
              <th v-if="canEdit" class="kebab-col"></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="r in sorted"
              :id="`row-${r.id}`"
              :key="r.id"
              :class="{ highlight: highlightId === r.id, 'is-ssl': r.type === 'ssl' }"
            >
              <td class="name">{{ rowName(r) }}</td>
              <td>
                <span class="type-badge" :class="r.type">{{ r.type === 'ssl' ? 'SSL' : 'Domain' }}</span>
              </td>
              <td class="mono">{{ fmtDate(r.expiryDate) }}</td>
              <td class="num mono">{{ daysLabel(r) }}</td>
              <td class="bar-col">
                <ExpiryBar :days-remaining="r.daysRemaining" :warn-threshold="r.warnThreshold" :status="r.status" />
              </td>
              <td>
                <span v-if="checking[r.id] || r.status === 'checking'" class="checking">
                  <span class="spinner"></span> Checking…
                </span>
                <StatusBadge v-else :kind="r.type" :status="r.status" />
              </td>
              <td class="muted small">{{ relTime(r.lastChecked) }}</td>
              <td v-if="canEdit" class="kebab-col" @click.stop>
                <button class="kebab" aria-label="Row actions" @click="openMenuId = openMenuId === r.id ? null : r.id">⋮</button>
                <div v-if="openMenuId === r.id" class="kebab-menu">
                  <button class="kmi" @click="checkNow(r)">Check Now</button>
                  <button v-if="r.type === 'domain' && !store.domainIdsWithCert.has(r.id)" class="kmi" @click="openAddSsl(r)">Add SSL Cert</button>
                  <button class="kmi" @click="r.type === 'domain' ? openEditDomain(r) : openEditSsl(r)">Edit</button>
                  <div class="kmi-div"></div>
                  <button class="kmi danger" @click="askDelete(r)">Delete</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="sorted.length === 0" class="no-match">No items match your filters.</div>
      </div>
    </template>

    <!-- Add Domain SlideOver -->
    <SlideOver v-model="showDomainModal" title="Add Domain" subtitle="Track WHOIS registration expiry" width="480px">
      <form id="domain-form" @submit.prevent="submitDomain">
        <label>Domain Name *</label>
        <input v-model="domainForm.domain" placeholder="example.com" :class="{ invalid: domainErrors.domain }" autofocus />
        <small v-if="normalisedDomain && normalisedDomain !== domainForm.domain.trim()" class="hint">Will be saved as: <code>{{ normalisedDomain }}</code></small>
        <div v-if="domainErrors.domain" class="err">{{ domainErrors.domain }}</div>
        <div class="form-row">
          <div class="col">
            <label>Warn at (days)</label>
            <input v-model.number="domainForm.warn_days" type="number" min="1" max="365" :class="{ invalid: domainErrors.warn_days }" />
            <div v-if="domainErrors.warn_days" class="err">{{ domainErrors.warn_days }}</div>
          </div>
          <div class="col">
            <label>Critical at (days)</label>
            <input v-model.number="domainForm.critical_days" type="number" min="1" :class="{ invalid: domainErrors.critical_days }" />
            <div v-if="domainErrors.critical_days" class="err">{{ domainErrors.critical_days }}</div>
          </div>
        </div>
        <div v-if="domainErrors._form" class="err">{{ domainErrors._form }}</div>
      </form>
      <template #footer>
        <button class="ghost" @click="showDomainModal = false">Cancel</button>
        <button class="primary" form="domain-form" type="submit" :disabled="domainSubmitting">
          <span v-if="domainSubmitting" class="spinner light"></span><span v-else>Add Domain</span>
        </button>
      </template>
    </SlideOver>

    <!-- Edit Domain SlideOver -->
    <SlideOver v-model="showEditDomain" title="Edit Domain" width="480px">
      <form id="edit-domain-form" @submit.prevent="submitEditDomain">
        <label>Domain Name</label>
        <input :value="editDomainForm.domain" disabled />
        <small class="hint">Domain name cannot be changed — delete and re-add if needed.</small>
        <div class="form-row">
          <div class="col">
            <label>Warn at (days)</label>
            <input v-model.number="editDomainForm.warn_days" type="number" min="1" max="365" />
          </div>
          <div class="col">
            <label>Critical at (days)</label>
            <input v-model.number="editDomainForm.critical_days" type="number" min="1" :class="{ invalid: editDomainErrors.critical_days }" />
            <div v-if="editDomainErrors.critical_days" class="err">{{ editDomainErrors.critical_days }}</div>
          </div>
        </div>
        <div v-if="editDomainErrors._form" class="err">{{ editDomainErrors._form }}</div>
      </form>
      <template #footer>
        <button class="ghost" @click="showEditDomain = false">Cancel</button>
        <button class="primary" form="edit-domain-form" type="submit">Save Changes</button>
      </template>
    </SlideOver>

    <!-- Add SSL SlideOver -->
    <SlideOver v-model="showSslModal" title="Add SSL Certificate" :subtitle="sslParent.domainName" width="420px">
      <form id="ssl-form" @submit.prevent="submitSsl">
        <label>Domain</label>
        <input :value="sslParent.domainName" disabled />
        <div class="form-row">
          <div class="col">
            <label>Port</label>
            <input v-model.number="sslForm.port" type="number" min="1" max="65535" :class="{ invalid: sslErrors.port }" />
            <div v-if="sslErrors.port" class="err">{{ sslErrors.port }}</div>
          </div>
        </div>
        <div class="form-row">
          <div class="col">
            <label>Warn at (days)</label>
            <input v-model.number="sslForm.warn_days" type="number" min="1" max="365" :class="{ invalid: sslErrors.warn_days }" />
            <div v-if="sslErrors.warn_days" class="err">{{ sslErrors.warn_days }}</div>
          </div>
          <div class="col">
            <label>Critical at (days)</label>
            <input v-model.number="sslForm.critical_days" type="number" min="1" :class="{ invalid: sslErrors.critical_days }" />
            <div v-if="sslErrors.critical_days" class="err">{{ sslErrors.critical_days }}</div>
          </div>
        </div>
        <div v-if="sslErrors._form" class="err">{{ sslErrors._form }}</div>
      </form>
      <template #footer>
        <button class="ghost" @click="showSslModal = false">Cancel</button>
        <button class="primary" form="ssl-form" type="submit" :disabled="sslSubmitting">
          <span v-if="sslSubmitting" class="spinner light"></span><span v-else>Add SSL Cert</span>
        </button>
      </template>
    </SlideOver>

    <!-- Edit SSL SlideOver -->
    <SlideOver v-model="showEditSsl" title="Edit SSL Certificate" :subtitle="editSslForm.name" width="420px">
      <form id="edit-ssl-form" @submit.prevent="submitEditSsl">
        <div class="form-row">
          <div class="col">
            <label>Port</label>
            <input v-model.number="editSslForm.port" type="number" min="1" max="65535" :class="{ invalid: editSslErrors.port }" />
            <div v-if="editSslErrors.port" class="err">{{ editSslErrors.port }}</div>
          </div>
        </div>
        <div class="form-row">
          <div class="col">
            <label>Warn at (days)</label>
            <input v-model.number="editSslForm.warn_days" type="number" min="1" max="365" />
          </div>
          <div class="col">
            <label>Critical at (days)</label>
            <input v-model.number="editSslForm.critical_days" type="number" min="1" :class="{ invalid: editSslErrors.critical_days }" />
            <div v-if="editSslErrors.critical_days" class="err">{{ editSslErrors.critical_days }}</div>
          </div>
        </div>
        <div v-if="editSslErrors._form" class="err">{{ editSslErrors._form }}</div>
      </form>
      <template #footer>
        <button class="ghost" @click="showEditSsl = false">Cancel</button>
        <button class="primary" form="edit-ssl-form" type="submit">Save Changes</button>
      </template>
    </SlideOver>

    <!-- Delete / blocked confirm -->
    <div v-if="confirm.open" class="modal-overlay" @click.self="confirm.open = false">
      <div class="modal sm">
        <template v-if="confirm.kind === 'blocked'">
          <h2>Cannot Delete Domain</h2>
          <p class="mb-msg">{{ confirm.name }} has a linked SSL certificate. Delete the SSL cert first, then delete the domain.</p>
          <div class="actions"><button class="primary" @click="confirm.open = false">Close</button></div>
        </template>
        <template v-else-if="confirm.kind === 'ssl'">
          <h2>Delete SSL cert for {{ confirm.name }}?</h2>
          <p class="mb-msg">This will permanently remove all SSL check history.</p>
          <div class="actions">
            <button class="ghost" @click="confirm.open = false">Cancel</button>
            <button class="danger-btn" @click="doDelete">Delete SSL Cert</button>
          </div>
        </template>
        <template v-else>
          <h2>Delete {{ confirm.name }}?</h2>
          <p class="mb-msg">This will permanently remove the domain registration record and all linked alert history.</p>
          <div class="actions">
            <button class="ghost" @click="confirm.open = false">Cancel</button>
            <button class="danger-btn" @click="doDelete">Delete Domain</button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 28px; }
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; margin-bottom: 18px; }
.panel-title { font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin-bottom: 8px; }

.page-hint { font-size: 12px; color: var(--muted); margin-bottom: 10px; }
.filters { display: flex; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
.filters select, .search { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; color: var(--text); font-size: 13px; outline: none; }
.filters select:focus, .search:focus { border-color: var(--accent); }
.search { flex: 1; min-width: 200px; }

.table-wrap { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; }
table.grid { width: 100%; border-collapse: collapse; font-size: 13px; }
thead th { text-align: left; padding: 12px 14px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); border-bottom: 1px solid var(--border); background: var(--surface-2); white-space: nowrap; }
th.sortable { cursor: pointer; user-select: none; }
th.sortable:hover { color: var(--text); }
.caret { margin-left: 4px; font-size: 9px; }
th.num, td.num { text-align: right; }
th.bar-col, td.bar-col { width: 130px; }
th.kebab-col, td.kebab-col { width: 40px; position: relative; }
tbody td { padding: 11px 14px; border-bottom: 1px solid var(--border); vertical-align: middle; }
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover td { background: rgba(99,102,241,0.04); }
tr.is-ssl td.name { padding-left: 28px; color: var(--muted); }
tr.highlight td { outline: 2px solid var(--amber); outline-offset: -2px; animation: fade-hl 0.6s ease-out; }
@keyframes fade-hl { from { background: rgba(245,158,11,0.18); } to { background: transparent; } }
.name { color: #fff; font-weight: 500; }
.mono { font-family: ui-monospace, monospace; }
.muted { color: var(--muted); }
.small { font-size: 12px; }
.type-badge { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; padding: 2px 7px; border-radius: 4px; }
.type-badge.domain { background: rgba(99,102,241,0.15); color: var(--accent-2); }
.type-badge.ssl { background: rgba(6,182,212,0.15); color: #22d3ee; }
.checking { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; color: var(--muted); }
.no-match { padding: 28px; text-align: center; color: var(--muted); font-size: 13px; }

/* Kebab */
.kebab { background: none; border: none; color: var(--muted); font-size: 16px; cursor: pointer; padding: 2px 6px; border-radius: 6px; line-height: 1; }
.kebab:hover { background: var(--surface-2); color: var(--text); }
.kebab-menu { position: absolute; top: 100%; right: 10px; margin-top: 2px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 4px 0; min-width: 160px; z-index: 50; box-shadow: 0 12px 30px rgba(0,0,0,0.4); }
.kmi { display: block; width: 100%; text-align: left; background: none; border: none; color: var(--text); font-size: 12px; padding: 8px 14px; cursor: pointer; }
.kmi:hover { background: rgba(99,102,241,0.1); color: var(--accent-2); }
.kmi.danger { color: #fca5a5; }
.kmi.danger:hover { background: rgba(239,68,68,0.1); color: var(--red); }
.kmi-div { height: 1px; background: var(--border); margin: 2px 0; }

/* Buttons */
.primary { padding: 9px 18px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); color: #fff; border: none; border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 38px; }
.primary:disabled { opacity: 0.6; cursor: wait; }
.ghost { padding: 8px 16px; border-radius: 8px; font-size: 13px; cursor: pointer; border: 1px solid var(--border); background: var(--surface-2); color: var(--text); }
.ghost:hover { border-color: var(--accent); color: var(--accent-2); }
.danger-btn { padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; border: 1px solid rgba(239,68,68,0.4); background: rgba(239,68,68,0.12); color: #fca5a5; }
.danger-btn:hover { background: rgba(239,68,68,0.2); color: #fff; }

/* Form fields (in SlideOver) */
form { display: block; }
label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; margin-top: 14px; }
form > label:first-child { margin-top: 0; }
input { width: 100%; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; color: var(--text); font-size: 13px; outline: none; }
input:focus { border-color: var(--accent); }
input:disabled { opacity: 0.6; cursor: not-allowed; }
input.invalid { border-color: var(--red); }
.form-row { display: flex; gap: 12px; }
.col { flex: 1; }
.hint { font-size: 11px; color: var(--muted); margin-top: 4px; display: block; }
.hint code { color: var(--accent-2); font-family: ui-monospace, monospace; }
.err { color: var(--red); font-size: 11px; margin-top: 6px; }

/* Confirm modal */
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 1200; padding: 20px; }
.modal { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 24px; width: 100%; }
.modal.sm { max-width: 440px; }
.modal h2 { font-size: 16px; color: #fff; margin-bottom: 10px; }
.mb-msg { color: var(--muted); font-size: 13px; line-height: 1.6; margin-bottom: 20px; }
.actions { display: flex; gap: 10px; justify-content: flex-end; }

/* Spinner */
.spinner { width: 12px; height: 12px; border: 2px solid rgba(99,102,241,0.25); border-top-color: var(--accent-2); border-radius: 50%; animation: spin 0.7s linear infinite; display: inline-block; }
.spinner.light { border-color: rgba(255,255,255,0.4); border-top-color: #fff; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
