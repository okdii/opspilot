<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useMetricsStore } from '@/stores/metrics'
import { useLogStore, ALL_SOURCES, ALL_SEVERITIES } from '@/stores/logs'
import { wsClient } from '@/utils/ws'
import { EmptyState } from '@/components/ui'
import LogRow from '@/components/logs/LogRow.vue'
import type { LogEntry, LogSeverity, LogSource, LogTimeRange } from '@/types'
import { relativeTime } from '@/utils/time'

const props = withDefaults(defineProps<{ logsSupported?: boolean }>(), { logsSupported: true })

const metrics = useMetricsStore()
const logs = useLogStore()

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

function clickBand(sev: 'fatal' | 'error' | 'warn'): void {
  logs.setFilter('severities', [sev])
  reload()
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
  await reload()
})

onUnmounted(() => {
  unbindWs?.(); unbindWs = null
  stopLiveTail()
  logs.reset()
})
</script>

<template>
  <div class="logs-tab">
    <div v-if="!props.logsSupported" class="unsupported-notice">
      Log collection is not available on this server. Fluent Bit has no packages for Debian 9 (stretch) — upgrade to Debian 10+ to enable log monitoring.
    </div>
    <!-- Severity summary panels -->
    <div class="summary-panels">
      <div
        v-for="band in (['fatal', 'error', 'warn'] as const)"
        :key="band"
        class="summary-card"
        :class="band"
        @click="clickBand(band)"
      >
        <div class="sc-header">
          <span class="sc-dot"></span>
          <span class="sc-label">{{ band.toUpperCase() }}</span>
          <span class="sc-count">{{ logs.summary?.[band]?.count ?? '—' }}</span>
        </div>
        <template v-if="logs.summary?.[band]?.count">
          <div class="sc-msg">{{ logs.summary[band].latest?.message ?? '' }}</div>
          <div class="sc-meta">{{ logs.summary[band].latest?.source }} · {{ relativeTime(logs.summary[band].latest?.time ?? null) }}</div>
        </template>
        <div v-else-if="logs.summary" class="sc-empty">No issues in this range</div>
        <div v-else class="sc-empty">—</div>
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
.sub-right { display: flex; align-items: center; gap: 16px; }
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

.summary-panels {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-bottom: 14px;
}

.summary-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid var(--sc-color);
  border-radius: 10px;
  padding: 12px 14px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.summary-card:hover {
  background: var(--surface-2);
  border-color: var(--sc-color);
}
.summary-card.fatal { --sc-color: #991b1b; }
.summary-card.error { --sc-color: #ef4444; }
.summary-card.warn  { --sc-color: #f59e0b; }

.sc-header {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 6px;
}
.sc-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--sc-color);
  flex-shrink: 0;
}
.sc-label {
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--sc-color);
}
.sc-count {
  margin-left: auto;
  font-size: 18px;
  font-weight: 700;
  color: var(--sc-color);
  line-height: 1;
}
.sc-msg {
  font-size: 12px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
  margin-bottom: 4px;
}
.sc-meta {
  font-size: 11px;
  color: var(--muted);
}
.sc-empty {
  font-size: 12px;
  color: var(--muted);
}
</style>
