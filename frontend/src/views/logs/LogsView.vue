<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useOrgStore } from '@/stores/org'
import { useServerStore } from '@/stores/server'
import { useLogStore, ALL_SOURCES, ALL_SEVERITIES } from '@/stores/logs'
import { wsClient } from '@/utils/ws'
import { PageHeader, EmptyState, StatusBadge } from '@/components/ui'
import MetricChart from '@/components/charts/MetricChart.vue'
import LogRow from '@/components/logs/LogRow.vue'
import type { LogEntry, LogSeverity, LogSource, LogTimeRange } from '@/types'

const orgStore = useOrgStore()
const serverStore = useServerStore()
const logs = useLogStore()

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
]

const SEV_COLORS: Record<LogSeverity, string> = {
  debug: '#6b7280', info: '#3b82f6', warn: '#f59e0b', error: '#ef4444', fatal: '#991b1b',
}

const expanded = ref<Set<string>>(new Set())
const freshIds = ref<Set<string>>(new Set())
const chartCollapsed = ref(false)
const serverMenuOpen = ref(false)
const sourceMenuOpen = ref(false)
const searchInput = ref<HTMLInputElement | null>(null)
const scroller = ref<HTMLElement | null>(null)
const atTop = ref(true)

let unbindWs: (() => void) | null = null
let searchTimer: number | null = null
const subscribedLogServers = new Set<string>()
let subscribedOrg: string | null = null

const showServerColumn = computed(() => logs.filters.serverIds.length !== 1)

const sourcesSelected = (group: LogSource[]) => group.every((s) => logs.filters.sources.includes(s))

const entryCountLabel = computed(() => {
  const n = logs.entries.length
  if (logs.limitReached) return `Showing ${n} entries (limit reached)`
  return `Showing ${n} ${n === 1 ? 'entry' : 'entries'}`
})

// --- Filter mutations -------------------------------------------------------

function toggleServer(id: string): void {
  const cur = logs.filters.serverIds
  logs.setFilter('serverIds', cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id])
  reload()
}

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
  searchTimer = window.setTimeout(() => { if (v.trim().length === 0 || v.trim().length >= 2) reload() }, 300)
}

function clearSearch(): void {
  logs.setFilter('search', '')
  reload()
}

function clearFilters(): void {
  logs.clearFilters()
  reload()
}

function onFilterSource(source: string): void {
  logs.setFilter('sources', [source as LogSource])
  reload()
}

function onFilterIp(ip: string): void {
  logs.setFilter('search', ip)
  reload()
}

// --- Loading ----------------------------------------------------------------

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

// --- Live tail --------------------------------------------------------------

function targetServerIds(): string[] {
  return logs.filters.serverIds.length
    ? logs.filters.serverIds
    : serverStore.servers.map((s) => s.id)
}

function startLiveTail(): void {
  logs.setLiveTail(true)
  if (orgStore.activeOrgId && subscribedOrg !== orgStore.activeOrgId) {
    wsClient.send({ action: 'subscribe_org', org_id: orgStore.activeOrgId })
    subscribedOrg = orgStore.activeOrgId
  }
  for (const id of targetServerIds()) {
    if (!subscribedLogServers.has(id)) {
      wsClient.send({ action: 'subscribe_logs', server_id: id })
      wsClient.send({ action: 'subscribe', server_id: id })
      subscribedLogServers.add(id)
    }
  }
}

function stopLiveTail(): void {
  logs.setLiveTail(false)
  for (const id of subscribedLogServers) {
    wsClient.send({ action: 'unsubscribe_logs', server_id: id })
  }
  subscribedLogServers.clear()
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

// --- Volume chart -----------------------------------------------------------

const volumeSeries = computed(() =>
  ALL_SEVERITIES.map((sev) => ({
    name: sev,
    data: logs.volumeData.map((b) => b[sev]),
  })).filter((s) => s.data.some((n) => n > 0)),
)

const volumeCategories = computed(() =>
  logs.volumeData.map((b) => new Date(b.time).getTime()),
)

const volumeColors = computed(() => volumeSeries.value.map((s) => SEV_COLORS[s.name as LogSeverity]))

const hasVolume = computed(() => volumeSeries.value.length > 0 && logs.volumeData.length > 0)

// --- Keyboard shortcuts (spec §14) ------------------------------------------

function onKeydown(e: KeyboardEvent): void {
  const tag = (e.target as HTMLElement)?.tagName
  const typing = tag === 'INPUT' || tag === 'TEXTAREA'
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
    e.preventDefault(); searchInput.value?.focus(); return
  }
  if (typing) {
    if (e.key === 'Escape' && document.activeElement === searchInput.value) clearSearch()
    return
  }
  if (e.key === 'l') { e.preventDefault(); toggleLiveTail() }
  else if (e.key === 'c') { e.preventDefault(); chartCollapsed.value = !chartCollapsed.value }
}

// --- Lifecycle --------------------------------------------------------------

async function init(orgId: string): Promise<void> {
  logs.setOrg(orgId)
  await serverStore.fetchByOrg(orgId)
  await reload()
}

onMounted(async () => {
  if (window.innerWidth < 720) chartCollapsed.value = true
  unbindWs = wsClient.on(handleWsMessage)
  window.addEventListener('keydown', onKeydown)
  const orgId = orgStore.activeOrgId
  if (orgId) await init(orgId)
})

watch(() => orgStore.activeOrgId, async (orgId) => {
  stopLiveTail()
  logs.reset()
  if (orgId) await init(orgId)
})

onUnmounted(() => {
  unbindWs?.(); unbindWs = null
  window.removeEventListener('keydown', onKeydown)
  stopLiveTail()
  logs.reset()
})
</script>

<template>
  <div class="page">
    <PageHeader title="Logs" :subtitle="orgStore.activeOrg?.name ?? undefined" />

    <div v-if="!orgStore.activeOrgId" class="hint">Select an organization to view logs.</div>

    <template v-else>
      <!-- Filter bar -->
      <div class="filter-bar">
        <!-- Server dropdown -->
        <div class="fb-dd" @click.stop>
          <button class="fb-trigger" @click="serverMenuOpen = !serverMenuOpen">
            Servers
            <span class="fb-count">{{ logs.filters.serverIds.length || 'All' }}</span>
          </button>
          <div v-if="serverMenuOpen" class="fb-menu">
            <label v-for="s in serverStore.servers" :key="s.id" class="fb-opt">
              <input type="checkbox" :checked="logs.filters.serverIds.includes(s.id)" @change="toggleServer(s.id)" />
              <span class="fb-opt-name">{{ s.name }}</span>
              <StatusBadge :status="s.status" kind="server" />
            </label>
            <div v-if="!serverStore.servers.length" class="fb-empty">No servers</div>
          </div>
        </div>

        <!-- Source dropdown -->
        <div class="fb-dd" @click.stop>
          <button class="fb-trigger" @click="sourceMenuOpen = !sourceMenuOpen">
            Sources
            <span class="fb-count">{{ logs.filters.sources.length }}/{{ ALL_SOURCES.length }}</span>
          </button>
          <div v-if="sourceMenuOpen" class="fb-menu wide">
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

        <!-- Severity chips -->
        <div class="sev-chips">
          <button v-for="s in ALL_SEVERITIES" :key="s" class="chip"
            :class="{ active: logs.filters.severities.includes(s) }"
            :style="{ '--chip': SEV_COLORS[s] }"
            @click="toggleSeverity(s)">
            <span class="chip-dot"></span>{{ s }}
          </button>
        </div>

        <!-- Search -->
        <div class="fb-search">
          <input ref="searchInput" type="text" placeholder="Search logs…"
            :value="logs.filters.search" @input="onSearchInput" @keydown.escape="clearSearch" />
          <span v-if="logs.filters.search.trim().length === 1" class="search-hint">Enter at least 2 characters</span>
        </div>

        <!-- Time range -->
        <select class="fb-range" :disabled="logs.liveTailActive"
          :value="logs.filters.range" @change="setRange(($event.target as HTMLSelectElement).value as LogTimeRange)">
          <template v-if="logs.liveTailActive"><option>Live</option></template>
          <template v-else>
            <option v-for="o in RANGE_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
          </template>
        </select>
      </div>

      <!-- Sub-bar: live tail + count -->
      <div class="sub-bar">
        <button class="live-btn" :class="{ on: logs.liveTailActive }" @click="toggleLiveTail">
          <span class="live-dot" :class="{ pulse: logs.liveTailActive }"></span>
          {{ logs.liveTailActive ? 'Live Tail ON' : 'Live Tail OFF' }}
        </button>
        <div class="sub-right">
          <span class="count">{{ entryCountLabel }}</span>
          <button v-if="logs.filtersActive" class="link-btn" @click="clearFilters">Clear filters</button>
          <button class="link-btn" @click="chartCollapsed = !chartCollapsed">
            {{ chartCollapsed ? 'Show chart' : 'Hide chart' }}
          </button>
        </div>
      </div>

      <!-- Volume chart -->
      <section v-if="!chartCollapsed" class="card chart-card">
        <h3>Log Volume</h3>
        <MetricChart v-if="hasVolume" type="bar" unit="count" stacked
          :series="volumeSeries" :categories="volumeCategories"
          :colors="volumeColors" :height="240" />
        <div v-else class="chart-empty">No log activity in this range.</div>
      </section>

      <!-- Table -->
      <div class="table-card">
        <div class="t-head">
          <span class="th-caret"></span>
          <span class="th-time">Time</span>
          <span v-if="showServerColumn" class="th-server">Server</span>
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
              <button v-if="logs.filtersActive" class="es-btn" @click="clearFilters">Clear filters</button>
            </template>
          </EmptyState>

          <template v-else>
            <LogRow v-for="e in logs.entries" :key="e.id" :entry="e"
              :expanded="expanded.has(e.id)" :show-server="showServerColumn"
              :fresh="freshIds.has(e.id)" :search="logs.filters.search"
              @toggle="toggleRow(e.id)" @filter-source="onFilterSource" @filter-ip="onFilterIp" />

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
    </template>
  </div>
</template>

<style scoped>
.page { padding: 28px; display: flex; flex-direction: column; height: calc(100vh - 0px); box-sizing: border-box; }
.hint { color: var(--muted); font-size: 13px; padding: 40px; text-align: center; }

/* Filter bar */
.filter-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
.fb-dd { position: relative; }
.fb-trigger { display: inline-flex; align-items: center; gap: 8px; background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 8px 12px; border-radius: 8px; font-size: 13px; cursor: pointer; }
.fb-trigger:hover { border-color: var(--accent); }
.fb-count { font-size: 11px; color: var(--accent-2); background: rgba(99,102,241,0.12); padding: 1px 7px; border-radius: 10px; }
.fb-menu { position: absolute; top: calc(100% + 6px); left: 0; z-index: 30; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 8px; min-width: 220px; max-height: 320px; overflow-y: auto; box-shadow: 0 10px 30px rgba(0,0,0,0.4); }
.fb-menu.wide { min-width: 240px; }
.fb-opt { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 6px; cursor: pointer; font-size: 12.5px; color: var(--text); }
.fb-opt:hover { background: var(--surface-2); }
.fb-opt-name { flex: 1; }
.fb-group { margin-bottom: 4px; }
.fb-group-head strong { font-size: 12px; }
.fb-sub { padding-left: 22px; color: var(--muted); }
.fb-empty { padding: 8px; color: var(--muted); font-size: 12px; }

/* Severity chips */
.sev-chips { display: flex; gap: 6px; }
.chip { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 20px; font-size: 11.5px; cursor: pointer; border: 1px solid var(--border); background: transparent; color: var(--muted); text-transform: capitalize; transition: all 0.12s; }
.chip .chip-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--chip); }
.chip.active { background: color-mix(in srgb, var(--chip) 18%, transparent); border-color: var(--chip); color: var(--text); }

/* Search + range */
.fb-search { flex: 1; min-width: 180px; position: relative; }
.fb-search input { width: 100%; box-sizing: border-box; background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 8px 12px; border-radius: 8px; font-size: 13px; }
.fb-search input:focus { outline: none; border-color: var(--accent); }
.search-hint { position: absolute; top: calc(100% + 4px); left: 4px; font-size: 11px; color: var(--amber); }
.fb-range { background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 8px 12px; border-radius: 8px; font-size: 13px; cursor: pointer; }
.fb-range:disabled { opacity: 0.6; cursor: not-allowed; }

/* Sub bar */
.sub-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.live-btn { display: inline-flex; align-items: center; gap: 8px; background: var(--surface); border: 1px solid var(--border); color: var(--muted); padding: 7px 14px; border-radius: 8px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
.live-btn.on { color: var(--green); border-color: rgba(34,197,94,0.4); background: rgba(34,197,94,0.08); }
.live-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
.live-dot.pulse { background: var(--green); animation: pulse 1.4s ease-in-out infinite; }
@keyframes pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(34,197,94,0.5); } 50% { box-shadow: 0 0 0 5px rgba(34,197,94,0); } }
.sub-right { display: flex; align-items: center; gap: 16px; }
.count { color: var(--muted); font-size: 12.5px; }
.link-btn { background: none; border: none; color: var(--accent-2); font-size: 12.5px; cursor: pointer; padding: 0; }
.link-btn:hover { text-decoration: underline; }

/* Chart card */
.card.chart-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; margin-bottom: 12px; }
.chart-card h3 { font-size: 13px; color: var(--text); margin-bottom: 8px; }
.chart-empty { color: var(--muted); font-size: 12.5px; padding: 24px; text-align: center; }

/* Table */
.table-card { flex: 1; min-height: 0; display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
.t-head { display: flex; align-items: center; gap: 12px; padding: 10px 14px; border-bottom: 1px solid var(--border); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); background: var(--surface-2); }
.th-caret { width: 8px; }
.th-time { width: 110px; }
.th-server { width: 96px; }
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
</style>
