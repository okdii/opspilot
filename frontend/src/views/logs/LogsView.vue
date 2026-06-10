<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useOrgStore } from '@/stores/org'
import { useLogIntelligenceStore } from '@/stores/logIntelligence'
import { useLogStore, ALL_SEVERITIES } from '@/stores/logs'
import { PageHeader, EmptyState } from '@/components/ui'
import MetricChart from '@/components/charts/MetricChart.vue'
import type { LogSeverity, VolumeBucket } from '@/types'

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
  logs.volumeData.map((b: VolumeBucket) => formatTime(b.time)),
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
  logs.setFilter('range', range as any)
  await Promise.all([
    intel.fetchIntelligence(orgId, range),
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
            <span v-for="sev in (['fatal', 'error', 'warn', 'info'] as LogSeverity[])" :key="sev"
              class="count-item" :style="{ '--dot': SEV_COLORS[sev] }">
              <span class="count-dot"></span>
              <span class="count-label">{{ sev.charAt(0).toUpperCase() + sev.slice(1) }}:</span>
              <span class="count-val">{{ intel.data.summary[sev].toLocaleString() }}</span>
            </span>
          </template>
        </div>
        <select class="range-sel" :value="intel.range"
          @change="setRange(($event.target as HTMLSelectElement).value)">
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
                  :style="{ height: `${Math.max(2, Math.round((v / (Math.max(...s.sparkline) || 1)) * 24))}px` }">
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
@media (max-width: 1023px) { .page { padding: 20px; } }
@media (max-width: 767px)  { .page { padding: 14px; } }
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

/* Source badge — shared across error-list and fatals */
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
.chart-empty { color: var(--muted); font-size: 12.5px; padding: 24px; text-align: center; }
</style>
