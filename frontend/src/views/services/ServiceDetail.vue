<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { PageHeader, StatCard, StatusBadge } from '@/components/ui'
import ExpiryBar from '@/components/ssl-domains/ExpiryBar.vue'
import ResponseTimeChart from '@/components/services/ResponseTimeChart.vue'
import UptimeTimeline from '@/components/services/UptimeTimeline.vue'
import ServiceModal from '@/components/services/ServiceModal.vue'
import { useAuthStore } from '@/stores/auth'
import { useOrgStore } from '@/stores/org'
import { useServerStore } from '@/stores/server'
import { useServiceStore } from '@/stores/services'
import { useDateFormat } from '@/composables/useDateFormat'
import { useNotify } from '@/composables/useNotify'
import { wsClient } from '@/utils/ws'
import { relativeTime } from '@/utils/metrics'
import { getApiError } from '@/services/api'
import SecurityGrade from '@/components/SecurityGrade.vue'
import SecurityTab from '@/components/services/tabs/SecurityTab.vue'
import type { ResponseRange, ResponseTimeData, SecurityScan, Service } from '@/stores/services'

const props = withDefaults(defineProps<{
  serviceId?: string
  embedded?: boolean
}>(), { embedded: false })

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const orgStore = useOrgStore()
const serverStore = useServerStore()
const store = useServiceStore()
const notify = useNotify()
const { formatDateTime } = useDateFormat()

const serviceId = computed(() => props.serviceId ?? (route.params.id as string))
const service = computed<Service | null>(() => store.activeService)
const canEdit = computed(() => orgStore.canEdit)

const modalOpen = ref(false)

// ── Header derived state ─────────────────────────────────────────────────────
const dotClass = computed(() => {
  const s = service.value
  if (!s) return 'dot-unknown'
  if (!s.is_active) return 'dot-paused'
  switch (s.last_status) {
    case 'up': return 'dot-up'
    case 'down': return 'dot-down'
    case 'timeout': return 'dot-timeout'
    default: return 'dot-unknown'
  }
})
const statusBadge = computed<{ status: string }>(() => {
  const s = service.value
  if (!s || s.last_status == null) return { status: 'maintenance' } // grey-ish unknown
  return { status: s.last_status === 'timeout' ? 'down' : s.last_status }
})
const typeLabel = computed(() => (service.value?.type ?? 'http').toUpperCase())
const target = computed(() => {
  const s = service.value
  if (!s) return ''
  return s.type === 'http' ? (s.url ?? '') : `${s.url ?? ''}:${s.port ?? ''}`
})

// ── Plain English summary ────────────────────────────────────────────────────
const summary = computed(() => {
  const s = service.value
  if (!s) return null
  if (!s.is_active) return { text: 'This service is paused — monitoring is stopped.', tone: 'paused' }
  if (s.last_status == null) return { text: 'Waiting for the first check — this usually takes under a minute.', tone: 'unknown' }
  if (s.last_status === 'down' || s.last_status === 'timeout') {
    return { text: `${s.name} is DOWN right now. OpsPilot detected a failure — check the incidents below.`, tone: 'down' }
  }
  const uptime = s.uptime_24h
  const avg = s.avg_response_ms_24h
  if (uptime != null && uptime < 99) {
    const avgPart = avg != null ? ` Response time is ${avg}ms.` : ''
    return { text: `${s.name} is mostly healthy but had some hiccups today (${uptime}% uptime in the last 24h). Worth keeping an eye on.${avgPart}`, tone: 'warn' }
  }
  if (avg != null && avg > 500) {
    return { text: `${s.name} is up but responding slowly (${avg}ms average). Normal is under 100ms for a TCP check.`, tone: 'warn' }
  }
  const avgPart = avg != null ? ` and responds in ${avg}ms` : ''
  return { text: `${s.name} is running perfectly. It answered every check in the last 24h${avgPart} — nothing to worry about.`, tone: 'ok' }
})

// ── Uptime summary ───────────────────────────────────────────────────────────
const uptime30d = ref<number | null>(null)
const incidentCount = ref(0)
const securityScan = ref<SecurityScan | null>(null)
const securityLoading = ref(false)
const securityScanning = ref(false)

const uptime24hStr = computed(() => fmtPct(service.value?.uptime_24h ?? null))
const uptime7dStr = computed(() => fmtPct(service.value?.uptime_7d ?? null))
const uptime30dStr = computed(() => fmtPct(uptime30d.value))
const avgStr = computed(() =>
  service.value?.avg_response_ms_24h != null ? `${service.value.avg_response_ms_24h}ms` : '—',
)
function fmtPct(v: number | null): string {
  return v != null ? `${v}%` : '—'
}

async function loadSecurity() {
  if (!service.value?.ssl_enabled || !orgStore.activeOrgId) return
  securityLoading.value = true
  try {
    securityScan.value = await store.fetchSecurityScan(orgStore.activeOrgId, serviceId.value)
  } catch {
    securityScan.value = null
  } finally {
    securityLoading.value = false
  }
}

async function runSecurityScan() {
  if (!orgStore.activeOrgId || securityScanning.value) return
  securityScanning.value = true
  try {
    await store.triggerSecurityScan(orgStore.activeOrgId, serviceId.value)
    // Poll until the scan result is newer than what we have now
    const before = securityScan.value?.scanned_at ?? null
    for (let i = 0; i < 30; i++) {
      await new Promise(r => setTimeout(r, 2000))
      const fresh = await store.fetchSecurityScan(orgStore.activeOrgId, serviceId.value)
      if (fresh && fresh.scanned_at !== before) {
        securityScan.value = fresh
        break
      }
    }
  } finally {
    securityScanning.value = false
  }
}

// ── Response time chart ──────────────────────────────────────────────────────
const range = ref<ResponseRange>('24h')
const respData = ref<ResponseTimeData | null>(null)
const respLoading = ref(false)

const downPeriods = computed(() =>
  store.incidents
    .filter((inc) => inc.started_at != null)
    .map((inc) => ({
      start: new Date(inc.started_at!).getTime(),
      end: inc.resolved_at ? new Date(inc.resolved_at).getTime() : Date.now(),
    })),
)

async function loadResponse(r: ResponseRange) {
  respLoading.value = true
  try {
    respData.value = await store.fetchResponseTime(serviceId.value, r)
  } catch {
    respData.value = null
  } finally {
    respLoading.value = false
  }
}
watch(range, (r) => loadResponse(r))

// ── Incidents ────────────────────────────────────────────────────────────────
function durationLabel(inc: { resolved_at: string | null; duration_sec: number | null }): string {
  if (!inc.resolved_at) return 'Ongoing'
  const sec = inc.duration_sec ?? 0
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  if (m < 60) return `${m} min`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}min`
}
// ── Load + WS ────────────────────────────────────────────────────────────────
let unbindWs: (() => void) | null = null
let subscribedOrg: string | null = null

async function load() {
  try {
    const svc = await store.fetchService(serviceId.value)
    await Promise.all([
      store.fetchUptimeTimeline(serviceId.value, 90),
      loadResponse(range.value),
      store.fetchIncidents(serviceId.value),
      store.fetchChecks(serviceId.value),
      loadSecurity(),
    ])
    // 30d uptime + incident count derived from timeline / incident list.
    const tl = store.uptimeTimeline
    if (tl.length) {
      const totalDown = tl.reduce((a, p) => a + (100 - p.uptime_pct), 0)
      uptime30d.value = Math.round((100 - totalDown / tl.length) * 100) / 100
    }
    incidentCount.value = store.incidents.length
    subscribeWs(svc)
  } catch {
    if (!props.embedded) {
      notify.error('Service not found.')
      void router.replace('/services')
    }
  }
}

function subscribeWs(svc: Service) {
  const server = serverStore.servers.find((s) => s.id === svc.server_id)
  const orgId = server?.org_id ?? orgStore.activeOrgId
  if (!orgId) return
  wsClient.send({ action: 'subscribe_org', org_id: orgId })
  subscribedOrg = orgId
}

function bindWs() {
  unbindWs = wsClient.on((msg: any) => {
    if (msg?.event === 'service_check' && msg.data?.service_id === serviceId.value) {
      store.handleCheckEvent(msg.data)
      // Live-append latest point to the 1h chart only.
      if (range.value === '1h' && respData.value && msg.data.response_time_ms != null) {
        respData.value.data.push({
          time: msg.data.checked_at,
          avg_ms: msg.data.response_time_ms,
          p95_ms: msg.data.response_time_ms,
        })
      }
    } else if (msg?.event === 'service_ssl_updated' && msg.data?.service_id === serviceId.value) {
      store.handleSslEvent(msg.data)
    } else if (msg?.event === 'service_security_updated' && msg.data?.service_id === serviceId.value) {
      void loadSecurity()
    } else if (msg?.event === 'incident_opened' && msg.data?.service_id === serviceId.value) {
      store.handleIncidentOpened(msg.data)
      void store.fetchIncidents(serviceId.value)
    } else if (msg?.event === 'incident_resolved' && msg.data?.service_id === serviceId.value) {
      store.handleIncidentResolved(msg.data)
    }
  })
}

function onSaved(s: Service) {
  notify.success(`Service "${s.name}" updated`)
}

async function togglePause() {
  if (!service.value) return
  try {
    const next = await store.toggleActive(service.value.id)
    notify.success(next.is_active ? 'Service resumed' : 'Service paused')
  } catch (err) {
    notify.error(getApiError(err)?.message ?? 'Could not update service.')
  }
}

onMounted(() => {
  bindWs()
  void load()
})

onUnmounted(() => {
  if (subscribedOrg) wsClient.send({ action: 'unsubscribe_org', org_id: subscribedOrg })
  unbindWs?.()
  store.activeService = null
})
</script>

<template>
  <div class="detail" :class="{ embedded }" v-if="service">
    <router-link v-if="!embedded" to="/services" class="back">← Services</router-link>

    <PageHeader v-if="!embedded" :title="service.name">
      <template #actions>
        <div class="hdr-status">
          <StatusBadge kind="service" v-bind="statusBadge" />
          <span class="seen">Last checked {{ relativeTime(service.last_checked) }}</span>
        </div>
        <template v-if="canEdit">
          <button class="btn ghost" @click="modalOpen = true">Edit</button>
          <button class="btn ghost" @click="togglePause">{{ service.is_active ? 'Pause' : 'Resume' }}</button>
        </template>
      </template>
    </PageHeader>

    <div class="ident-bar">
      <span class="dot" :class="dotClass"></span>
      <span class="type-badge">{{ typeLabel }}</span>
      <span class="server">{{ service.server_name }}</span>
      <span class="target">{{ target }}</span>
      <span v-if="!service.is_active" class="paused-badge">Paused</span>
      <span v-if="service.is_public" class="public-badge">Public</span>
    </div>

    <!-- Plain English summary -->
    <div v-if="summary" class="summary-banner" :class="`summary-${summary.tone}`">
      {{ summary.text }}
    </div>

    <!-- Uptime summary cards -->
    <div class="cards">
      <StatCard label="Uptime 24h" :value="uptime24hStr" accent="success" />
      <StatCard label="Uptime 7d" :value="uptime7dStr" accent="success" />
      <StatCard label="Uptime 30d" :value="uptime30dStr" accent="success" />
      <StatCard label="Avg Response" :value="avgStr" :delta="{ value: '24h average', direction: 'flat' }" accent="info" />
    </div>

    <!-- SSL Certificate Card — HTTPS services only -->
    <section v-if="service.ssl_enabled" class="card ssl-section">
      <div class="ssl-section-header">
        <h3 class="ssl-section-title">SSL Certificate</h3>
        <StatusBadge kind="ssl" :status="service.ssl_status ?? 'unreachable'" />
      </div>
      <div class="ssl-meta-grid">
        <div class="ssl-meta-item">
          <span class="ssl-label">Expiry Date</span>
          <span class="ssl-value mono">{{ service.ssl_expiry_date ? service.ssl_expiry_date.slice(0, 10) : '—' }}</span>
        </div>
        <div class="ssl-meta-item">
          <span class="ssl-label">Days Left</span>
          <span
            class="ssl-value mono"
            :class="{
              'ssl-warn': (service.ssl_days_remaining ?? 999) <= service.ssl_warn_days && (service.ssl_days_remaining ?? 999) > service.ssl_critical_days,
              'ssl-crit': (service.ssl_days_remaining ?? 999) <= service.ssl_critical_days
            }"
          >{{ service.ssl_days_remaining ?? '—' }}</span>
        </div>
        <div class="ssl-meta-item">
          <span class="ssl-label">Issuer</span>
          <span class="ssl-value">{{ service.ssl_issuer ?? '—' }}</span>
        </div>
        <div class="ssl-meta-item">
          <span class="ssl-label">Last Checked</span>
          <span class="ssl-value muted">{{ service.ssl_last_checked ? relativeTime(service.ssl_last_checked) : 'never' }}</span>
        </div>
      </div>
      <ExpiryBar
        class="ssl-expiry-bar"
        :days-remaining="service.ssl_days_remaining"
        :warn-threshold="service.ssl_warn_days"
        :status="service.ssl_status ?? 'unreachable'"
      />
    </section>

    <!-- Security Audit Card — HTTPS services only -->
    <section v-if="service.ssl_enabled" class="card">
      <div class="card-hd">
        <h3>Security Audit</h3>
        <SecurityGrade
          v-if="securityScan"
          :grade="securityScan.grade"
          :score="securityScan.score"
          size="sm"
        />
      </div>
      <SecurityTab :scan="securityScan" :loading="securityLoading" :scanning="securityScanning" @run-scan="runSecurityScan" />
    </section>

    <!-- Uptime timeline -->
    <section class="card">
      <h3>Uptime — last 90 days</h3>
      <UptimeTimeline :points="store.uptimeTimeline" :days="90" />
    </section>

    <!-- Response time -->
    <section class="card">
      <ResponseTimeChart
        title="Response Time"
        :data="respData"
        :range="range"
        :down-periods="downPeriods"
        :loading="respLoading"
        @range-change="(r) => (range = r)"
      />
    </section>

    <!-- Incidents -->
    <section class="card">
      <h3>Incidents (last 90 days)</h3>
      <div v-if="store.incidents.length" class="table">
        <div class="thead">
          <span>Started</span>
          <span>Resolved</span>
          <span>Duration</span>
        </div>
        <div v-for="inc in store.incidents" :key="inc.id" class="trow">
          <span class="mono">{{ formatDateTime(inc.started_at) }}</span>
          <span v-if="!inc.resolved_at" class="ongoing">Ongoing</span>
          <span v-else class="mono">{{ formatDateTime(inc.resolved_at) }}</span>
          <span class="dur" :class="{ open: !inc.resolved_at }">{{ durationLabel(inc) }}</span>
        </div>
      </div>
      <p v-else class="placeholder">No incidents in the last 90 days.</p>
    </section>

    <ServiceModal
      v-if="!embedded"
      v-model="modalOpen"
      :service="service"
      :servers="[{ id: service.server_id, name: service.server_name, status: 'online' }]"
      @saved="onSaved"
    />
  </div>
</template>

<style scoped>
.detail { padding: 24px 28px; max-width: 1300px; }
.detail.embedded { padding: 0; max-width: none; }
.back { display: inline-block; color: var(--muted); text-decoration: none; font-size: 13px; margin-bottom: 12px; }
.back:hover { color: var(--text); }
.hdr-status { display: flex; align-items: center; gap: 10px; }
.seen { color: var(--muted); font-size: 12px; }
.btn { padding: 8px 16px; border-radius: 8px; font-size: 12px; cursor: pointer; border: 1px solid var(--border); background: var(--surface-2); color: var(--text); }
.btn.ghost:hover { border-color: var(--accent); color: var(--accent-2); }
.ident-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }
.dot { width: 10px; height: 10px; border-radius: 50%; }
.dot-up { background: var(--green); box-shadow: 0 0 8px rgba(34,197,94,0.6); }
.dot-down { background: var(--red); box-shadow: 0 0 8px rgba(239,68,68,0.5); }
.dot-timeout { background: var(--amber); }
.dot-unknown { background: var(--grey, #6b7280); }
.dot-paused { background: var(--grey, #6b7280); opacity: 0.6; }
.type-badge { font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; background: rgba(59,130,246,0.15); color: var(--blue, #3b82f6); }
.server { font-size: 12px; color: var(--muted); }
.target { font-size: 12px; color: var(--muted); font-family: ui-monospace, monospace; }
.paused-badge { font-size: 10px; font-weight: 600; text-transform: uppercase; padding: 2px 6px; border-radius: 4px; background: rgba(245,158,11,0.15); color: var(--amber); }
.public-badge { font-size: 10px; font-weight: 600; text-transform: uppercase; padding: 2px 6px; border-radius: 4px; background: rgba(99,102,241,0.15); color: var(--accent-2); }
.cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 20px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; margin-bottom: 16px; }
.card h3 { font-size: 13px; color: var(--text); margin-bottom: 14px; font-weight: 600; }
.card-hd { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.card-hd h3 { margin-bottom: 0; }
.placeholder { color: var(--muted); font-size: 13px; text-align: center; padding: 30px; }
.table { display: flex; flex-direction: column; }
.thead, .trow { display: grid; grid-template-columns: 1fr 1fr 120px; gap: 12px; padding: 10px 4px; align-items: center; }
.thead { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); border-bottom: 1px solid var(--border); }
.trow { border-bottom: 1px solid var(--border); font-size: 13px; color: var(--text); }
.trow:last-child { border-bottom: none; }
.mono { font-family: ui-monospace, monospace; font-size: 12px; }
.dur { color: var(--muted); }
.dur.open { color: var(--red); font-weight: 600; }
.ongoing { color: var(--red); font-weight: 600; font-size: 12px; }
.summary-banner { padding: 14px 18px; border-radius: 10px; border-left: 4px solid; font-size: 14px; line-height: 1.5; margin-bottom: 20px; }
.summary-ok { background: rgba(34,197,94,0.08); border-color: var(--green); color: var(--text); }
.summary-warn { background: rgba(245,158,11,0.08); border-color: var(--amber); color: var(--text); }
.summary-down { background: rgba(239,68,68,0.1); border-color: var(--red); color: var(--text); }
.summary-paused { background: rgba(107,114,128,0.08); border-color: var(--grey, #6b7280); color: var(--muted); }
.summary-unknown { background: rgba(99,102,241,0.08); border-color: var(--accent); color: var(--muted); }
@media (max-width: 720px) { .cards { grid-template-columns: repeat(2, 1fr); } }
.ssl-section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.ssl-section-title { font-size: 13px; font-weight: 600; color: var(--text); margin: 0; }
.ssl-meta-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px 20px; margin-bottom: 14px; }
.ssl-meta-item { display: flex; flex-direction: column; gap: 3px; }
.ssl-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }
.ssl-value { font-size: 14px; color: var(--text); }
.ssl-value.mono { font-family: ui-monospace, monospace; }
.ssl-value.muted { color: var(--muted); }
.ssl-warn { color: #f59e0b; }
.ssl-crit { color: #ef4444; }
.ssl-expiry-bar { margin-top: 4px; }
</style>
