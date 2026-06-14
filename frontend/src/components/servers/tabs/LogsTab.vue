<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useMetricsStore } from '@/stores/metrics'
import { useLogStore, ALL_SOURCES, ALL_SEVERITIES } from '@/stores/logs'
import { useLogIntelligenceStore } from '@/stores/logIntelligence'
import { wsClient } from '@/utils/ws'
import { EmptyState } from '@/components/ui'
import LogRow from '@/components/logs/LogRow.vue'
import type { LogEntry, LogSeverity, LogSource, LogTimeRange } from '@/types'
import { relativeTime } from '@/utils/time'

const props = withDefaults(defineProps<{ logsSupported?: boolean }>(), { logsSupported: true })

const metrics = useMetricsStore()
const logs = useLogStore()
const intel = useLogIntelligenceStore()
const route = useRoute()

const INTEL_RANGE_OPTIONS = [
  { value: '1h', label: 'Last 1 hour' },
  { value: '6h', label: 'Last 6 hours' },
  { value: '24h', label: 'Last 24 hours' },
]

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
  { value: '30d', label: 'Last 30 days' },
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
const subscribedServer = ref(false)

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

const totalLogCount = computed(() => {
  if (!logs.volumeData.length) return null
  return logs.volumeData.reduce(
    (sum, b) => sum + (b.debug || 0) + (b.info || 0) + (b.warn || 0) + (b.error || 0) + (b.fatal || 0),
    0,
  )
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
  logs.clearFilters()
  logs.setFilter('serverIds', [serverId.value])
  reload()
}

function clickBand(sev: 'error' | 'warn'): void {
  logs.setFilter('severities', [sev])
  reload()
}

async function setIntelRange(r: string): Promise<void> {
  if (serverId.value) await intel.fetchIntelligence(null, r, serverId.value)
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
  if (!subscribedServer.value && serverId.value) {
    wsClient.send({ action: 'subscribe_logs', server_id: serverId.value })
    wsClient.send({ action: 'subscribe', server_id: serverId.value })
    subscribedServer.value = true
  }
}

function stopLiveTail(): void {
  logs.setLiveTail(false)
  if (subscribedServer.value && serverId.value) {
    wsClient.send({ action: 'unsubscribe_logs', server_id: serverId.value })
    subscribedServer.value = false
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
  if (!serverId.value) return
  logs.setFilter('serverIds', [serverId.value])
  if (route.query.source === 'kernel') {
    logs.setFilter('sources', ['kernel'])
    logs.setFilter('range', '7d')
  }
  await Promise.all([
    reload(),
    intel.fetchIntelligence(null, intel.range, serverId.value),
  ])
})

onUnmounted(() => {
  unbindWs?.(); unbindWs = null
  stopLiveTail()
  logs.reset()
  intel.reset()
})
</script>

<template>
  <div class="logs-tab">
    <div v-if="!props.logsSupported" class="unsupported-notice">
      Log collection is not available on this server. Fluent Bit has no packages for Debian 9 (stretch) — upgrade to Debian 10+ to enable log monitoring.
    </div>
    <!-- Intelligence cards -->
    <div class="intel-header">
      <span class="intel-title">Log Intelligence</span>
      <select class="intel-range-sel" :value="intel.range" @change="setIntelRange(($event.target as HTMLSelectElement).value)">
        <option v-for="o in INTEL_RANGE_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
    </div>
    <div v-if="intel.loading" class="intel-loading">Loading intelligence…</div>
    <div v-else-if="intel.data" class="intel-grid">
      <!-- Critical Errors -->
      <div class="intel-card">
        <div class="icard-header">
          <span class="icard-icon error-icon">!</span>
          <h4>Critical Errors</h4>
          <span class="icard-total">{{ (intel.data.summary.error + intel.data.summary.fatal).toLocaleString() }} total</span>
        </div>
        <div v-if="!intel.data.top_errors.length" class="icard-empty">No errors in this range</div>
        <div v-else class="ierror-list">
          <div v-for="(e, i) in intel.data.top_errors" :key="i" class="ierror-row">
            <span class="ierror-count">×{{ e.count }}</span>
            <span class="isrc-badge" :class="`isrc-${e.source}`">{{ e.source }}</span>
            <span class="ierror-msg" :title="e.message">{{ e.message }}</span>
          </div>
        </div>
      </div>

      <!-- HTTP Errors -->
      <div class="intel-card" :class="{ dimmed: !intel.data.http_errors }">
        <div class="icard-header">
          <span class="icard-icon http-icon">HTTP</span>
          <h4>HTTP Errors</h4>
        </div>
        <div v-if="!intel.data.http_errors" class="icard-empty">No nginx_access data</div>
        <template v-else>
          <div class="ihttp-summary">
            <span class="ihttp-5xx">{{ intel.data.http_errors.total_5xx }} <small>5xx</small></span>
            <span class="ihttp-4xx">{{ intel.data.http_errors.total_4xx }} <small>4xx</small></span>
          </div>
          <div class="iurl-list">
            <div v-for="(u, i) in intel.data.http_errors.top_urls" :key="i" class="iurl-row">
              <span class="iurl-status" :class="u.status >= 500 ? 'err' : 'warn'">{{ u.status }}</span>
              <span class="iurl-path" :title="u.url">{{ u.url }}</span>
              <span class="iurl-count">×{{ u.count }}</span>
            </div>
          </div>
        </template>
      </div>

      <!-- Slow Queries -->
      <div class="intel-card" :class="{ dimmed: !intel.data.slow_queries }">
        <div class="icard-header">
          <span class="icard-icon slow-icon">⏱</span>
          <h4>Slow Queries</h4>
        </div>
        <div v-if="!intel.data.slow_queries" class="icard-empty">No slow query data</div>
        <template v-else>
          <div class="islow-stats">
            <div class="islow-stat">
              <span class="istat-val">{{ intel.data.slow_queries.total }}</span>
              <span class="istat-label">slow queries</span>
            </div>
            <div class="islow-stat">
              <span class="istat-val warn-text">{{ (intel.data.slow_queries.worst_duration_ms / 1000).toFixed(2) }}s</span>
              <span class="istat-label">worst</span>
            </div>
          </div>
          <pre class="islow-query">{{ intel.data.slow_queries.worst_query }}</pre>
        </template>
      </div>

      <!-- Auth Events -->
      <div class="intel-card" :class="{ dimmed: !intel.data.auth_events }">
        <div class="icard-header">
          <span class="icard-icon auth-icon">🔒</span>
          <h4>Auth Events</h4>
        </div>
        <div v-if="!intel.data.auth_events" class="icard-empty">No auth data</div>
        <template v-else>
          <div class="iauth-stats">
            <div class="iauth-stat-row">
              <span class="istat-val warn-text">{{ intel.data.auth_events.failed_logins }}</span>
              <span class="istat-label"> failed logins</span>
            </div>
            <div class="iauth-stat-row" :class="{ 'iauth-success-alert': intel.data.auth_events.successful_logins > 0 }">
              <span class="istat-val" :class="intel.data.auth_events.successful_logins > 0 ? 'idanger-text' : 'iclean-text'">
                {{ intel.data.auth_events.successful_logins }}
              </span>
              <span class="istat-label">{{ intel.data.auth_events.successful_logins === 0 ? ' successful — clean ✓' : ' successful logins !' }}</span>
            </div>
          </div>
          <div class="iip-list">
            <div v-for="(ip, i) in intel.data.auth_events.top_ips" :key="i" class="iip-row" :class="{ flagged: ip.count > 10 }">
              <span class="iip-addr">{{ ip.ip }}</span>
              <span class="iip-count">×{{ ip.count }}</span>
              <span v-if="ip.count > 10" class="iip-flag">⚠</span>
            </div>
          </div>
          <template v-if="intel.data.auth_events.successful_logins > 0">
            <div class="isuccess-divider">Successful logins</div>
            <div class="isuccess-list">
              <div v-for="(s, i) in intel.data.auth_events.successful_top" :key="i" class="isuccess-row">
                <span class="isuccess-user">{{ s.user }}</span>
                <span class="isuccess-ip">{{ s.ip }}</span>
                <span class="isuccess-count">×{{ s.count }}</span>
              </div>
            </div>
          </template>
        </template>
      </div>
    </div>

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
        <span v-if="totalLogCount !== null" class="total-count">{{ totalLogCount.toLocaleString() }} total logs</span>
        <span class="count-sep" v-if="totalLogCount !== null">·</span>
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
.unsupported-notice { background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.35); border-radius: 6px; color: #f59e0b; font-size: 13px; padding: 10px 14px; margin-bottom: 14px; }

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
.sub-right { display: flex; align-items: center; gap: 10px; }
.total-count { color: var(--text); font-size: 12.5px; font-weight: 600; }
.count-sep { color: var(--muted); font-size: 12px; }
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

/* Intelligence cards */
.intel-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.intel-title { font-size: 12px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.intel-range-sel { background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 5px 10px; border-radius: 7px; font-size: 12px; cursor: pointer; }
.intel-loading { font-size: 12px; color: var(--muted); padding: 12px 0; margin-bottom: 14px; }
.intel-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-bottom: 14px; }

.intel-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; min-width: 0; overflow: hidden; }
.intel-card.dimmed { opacity: 0.55; }
.icard-header { display: flex; align-items: center; gap: 8px; }
.icard-header h4 { font-size: 12px; font-weight: 600; color: var(--text); margin: 0; }
.icard-total { margin-left: auto; font-size: 11px; color: var(--muted); white-space: nowrap; }
.icard-icon { font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 5px; flex-shrink: 0; }
.error-icon { background: rgba(239,68,68,0.18); color: #f87171; }
.http-icon  { background: rgba(59,130,246,0.18); color: #60a5fa; font-size: 9px; }
.slow-icon  { background: rgba(245,158,11,0.18); color: #fbbf24; }
.auth-icon  { background: rgba(20,184,166,0.18); color: #2dd4bf; }
.icard-empty { color: var(--muted); font-size: 11.5px; }

/* Error list */
.ierror-list { display: flex; flex-direction: column; gap: 5px; max-height: 160px; overflow-y: auto; }
.ierror-row { display: flex; align-items: center; gap: 6px; font-size: 11.5px; min-width: 0; }
.ierror-count { font-size: 10.5px; font-weight: 700; color: #f87171; width: 28px; flex-shrink: 0; text-align: right; }
.ierror-msg { flex: 1; min-width: 0; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-family: ui-monospace, monospace; font-size: 11px; }

/* HTTP */
.ihttp-summary { display: flex; gap: 20px; }
.ihttp-5xx { font-size: 20px; font-weight: 700; color: #f87171; }
.ihttp-4xx { font-size: 20px; font-weight: 700; color: #fbbf24; }
.ihttp-5xx small, .ihttp-4xx small { font-size: 10px; color: var(--muted); margin-left: 3px; font-weight: 400; }
.iurl-list { display: flex; flex-direction: column; gap: 3px; }
.iurl-row { display: flex; align-items: center; gap: 6px; font-size: 11px; min-width: 0; }
.iurl-status { font-size: 10px; font-weight: 700; padding: 1px 5px; border-radius: 4px; flex-shrink: 0; }
.iurl-status.err  { background: rgba(239,68,68,0.18); color: #f87171; }
.iurl-status.warn { background: rgba(245,158,11,0.18); color: #fbbf24; }
.iurl-path { flex: 1; min-width: 0; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-family: ui-monospace, monospace; }
.iurl-count { color: var(--muted); font-size: 10.5px; flex-shrink: 0; }

/* Slow queries */
.islow-stats { display: flex; gap: 20px; }
.islow-stat { display: flex; flex-direction: column; }
.istat-val { font-size: 20px; font-weight: 700; color: var(--text); line-height: 1.1; }
.istat-label { font-size: 10.5px; color: var(--muted); }
.warn-text { color: #fbbf24 !important; }
.islow-query { background: #0f1117; border: 1px solid var(--border); border-radius: 5px; padding: 6px 8px; color: #e2e8f0; font-family: ui-monospace, monospace; font-size: 10.5px; white-space: pre-wrap; word-break: break-all; margin: 0; max-height: 60px; overflow: hidden; }

/* Auth */
.iauth-stats { display: flex; flex-direction: column; gap: 3px; }
.iauth-stat-row { display: flex; align-items: baseline; gap: 0; font-size: 12px; }
.iauth-success-alert { background: rgba(239,68,68,0.08); border-radius: 5px; padding: 2px 5px; margin: 0 -5px; }
.iclean-text { color: #4ade80 !important; font-size: 20px; font-weight: 700; }
.idanger-text { color: #f87171 !important; font-size: 20px; font-weight: 700; }
.iip-list { display: flex; flex-direction: column; gap: 3px; max-height: 80px; overflow-y: auto; }
.iip-row { display: flex; align-items: center; gap: 6px; font-size: 11px; }
.iip-addr { flex: 1; font-family: ui-monospace, monospace; color: var(--text); }
.iip-count { color: var(--muted); font-size: 10.5px; }
.iip-flag { color: #fbbf24; font-size: 10px; }
.iip-row.flagged .iip-addr { color: #fbbf24; }
.isuccess-divider { font-size: 10px; font-weight: 600; color: #f87171; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 3px; }
.isuccess-list { display: flex; flex-direction: column; gap: 2px; }
.isuccess-row { display: flex; align-items: center; gap: 6px; font-size: 11px; }
.isuccess-user { font-weight: 600; color: #f87171; font-family: ui-monospace, monospace; }
.isuccess-ip { flex: 1; color: var(--muted); font-family: ui-monospace, monospace; font-size: 10.5px; }
.isuccess-count { color: var(--muted); font-size: 10px; }

/* Source badges */
.isrc-badge { font-size: 9.5px; font-weight: 600; padding: 1px 5px; border-radius: 4px; flex-shrink: 0; text-transform: lowercase; }
.isrc-syslog       { background: rgba(148,163,184,0.16); color: #cbd5e1; }
.isrc-auth         { background: rgba(20,184,166,0.18);  color: #2dd4bf; }
.isrc-kernel       { background: rgba(100,116,139,0.22); color: #94a3b8; }
.isrc-nginx_access { background: rgba(59,130,246,0.18);  color: #60a5fa; }
.isrc-nginx_error  { background: rgba(37,99,235,0.22);   color: #3b82f6; }
.isrc-php_fpm      { background: rgba(168,85,247,0.18);  color: #c084fc; }
.isrc-php_app      { background: rgba(147,51,234,0.22);  color: #a855f7; }
.isrc-mariadb_error{ background: rgba(245,158,11,0.18);  color: #fbbf24; }
.isrc-mariadb_slow { background: rgba(217,119,6,0.22);   color: #f59e0b; }
</style>
