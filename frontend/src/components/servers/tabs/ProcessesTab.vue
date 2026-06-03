<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import MetricChart from '@/components/charts/MetricChart.vue'
import { EmptyState, MetricBar } from '@/components/ui'
import { getProcesses } from '@/services/api'
import { useMetricsStore } from '@/stores/metrics'
import { toApexSeries } from '@/utils/metrics'
import type { MetricRange, ProcessSnapshot } from '@/types'

const props = defineProps<{ range: MetricRange }>()
const metrics = useMetricsStore()

const TREND_KEY = 'proc.trend'
const POLL_MS = 5000

// --- Live snapshot polling -------------------------------------------------
const snapshot = ref<ProcessSnapshot | null>(null)
const lastUpdated = ref<number | null>(null)
const lastOk = ref(false)
// `ago` is a 1s-ticked seconds counter for the "Updated Xs ago" label.
const ago = ref(0)

let pollTimer: ReturnType<typeof setInterval> | null = null
let tickTimer: ReturnType<typeof setInterval> | null = null

async function poll() {
  const id = metrics.activeServerId
  if (!id) return
  try {
    const snap = await getProcesses(id)
    snapshot.value = snap
    lastUpdated.value = Date.now()
    lastOk.value = snap.reachable === true
    ago.value = 0
  } catch {
    // Network/auth error — mark paused but keep the last good snapshot visible.
    lastOk.value = false
  }
}

// Staleness colour for the "Updated Xs ago" label: amber >60s, red >120s.
const agoClass = computed(() => {
  if (ago.value > 120) return 'stale-red'
  if (ago.value > 60) return 'stale-amber'
  return ''
})

const live = computed(() => lastOk.value && snapshot.value?.reachable === true)

// --- Trend chart -----------------------------------------------------------
async function loadTrend(range: MetricRange) {
  await metrics.loadChartData(['proctop.cpu_pct'], range, TREND_KEY)
}

const trendSeries = computed(() =>
  toApexSeries(metrics.chartData[TREND_KEY]?.series ?? [], { name: (s) => s.labels.name }),
)

// --- All-processes table: text filter + client-side sort -------------------
const filter = ref('')
type SortKey = 'cpu_pct' | 'mem_pct' | 'pid' | 'name'
const sortKey = ref<SortKey>('cpu_pct')
const sortDesc = ref(true)

function sortBy(key: SortKey) {
  if (sortKey.value === key) {
    sortDesc.value = !sortDesc.value
  } else {
    sortKey.value = key
    // Numeric columns default desc; name defaults asc.
    sortDesc.value = key !== 'name'
  }
}

const filteredProcesses = computed(() => {
  const rows = snapshot.value?.processes ?? []
  const q = filter.value.trim().toLowerCase()
  const matched = q ? rows.filter((p) => p.name.toLowerCase().includes(q)) : rows.slice()
  const key = sortKey.value
  const dir = sortDesc.value ? -1 : 1
  return matched.sort((a, b) => {
    const av = a[key]
    const bv = b[key]
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
    return String(av).localeCompare(String(bv)) * dir
  })
})

function ariaSort(key: SortKey): 'ascending' | 'descending' | 'none' {
  if (sortKey.value !== key) return 'none'
  return sortDesc.value ? 'descending' : 'ascending'
}

onMounted(() => {
  void poll()
  void loadTrend(props.range)
  pollTimer = setInterval(() => void poll(), POLL_MS)
  tickTimer = setInterval(() => {
    if (lastUpdated.value != null) ago.value = Math.round((Date.now() - lastUpdated.value) / 1000)
  }, 1000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (tickTimer) clearInterval(tickTimer)
})

watch(() => props.range, (r) => void loadTrend(r))
</script>

<template>
  <div class="proc">
    <!-- Header -->
    <div class="proc-head">
      <h3>Top Processes by CPU</h3>
      <div class="proc-meta">
        <span class="ago" :class="agoClass" v-if="lastUpdated != null">Updated {{ ago }}s ago</span>
        <span class="ago" v-else>Updating…</span>
        <span class="live-badge" :class="{ on: live }">
          <span class="dot">●</span>{{ live ? 'Live' : 'Paused' }}
        </span>
      </div>
    </div>

    <!-- Agent unreachable -->
    <EmptyState
      v-if="snapshot && snapshot.reachable === false"
      title="Agent unreachable"
      message="Agent unreachable — can't read live processes."
    />

    <template v-else>
      <div class="grid">
        <!-- Top by CPU -->
        <section class="card">
          <h4>Top by CPU</h4>
          <table class="ptable" v-if="snapshot?.top_cpu.length">
            <thead>
              <tr>
                <th class="t-proc">Process</th>
                <th class="t-num">PID</th>
                <th class="t-bar">CPU%</th>
                <th class="t-num">MEM%</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in snapshot.top_cpu" :key="p.pid">
                <td class="t-bar-cell" colspan="3">
                  <MetricBar :label="p.name" :value="p.cpu_pct" />
                </td>
                <td class="t-num muted">{{ p.mem_pct.toFixed(1) }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="empty">No process data.</p>
        </section>

        <!-- Top by Memory -->
        <section class="card">
          <h4>Top by Memory</h4>
          <table class="ptable" v-if="snapshot?.top_mem.length">
            <thead>
              <tr>
                <th class="t-proc">Process</th>
                <th class="t-num">PID</th>
                <th class="t-bar">MEM%</th>
                <th class="t-num">CPU%</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in snapshot.top_mem" :key="p.pid">
                <td class="t-bar-cell" colspan="3">
                  <MetricBar :label="p.name" :value="p.mem_pct" />
                </td>
                <td class="t-num muted">{{ p.cpu_pct.toFixed(1) }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="empty">No process data.</p>
        </section>
      </div>

      <!-- Trend -->
      <section class="card">
        <h4>Top CPU consumers (trend)</h4>
        <MetricChart type="area" stacked unit="%" :series="trendSeries" :height="260" />
      </section>

      <!-- All processes -->
      <section class="card">
        <div class="all-head">
          <h4>All Processes</h4>
          <input
            v-model="filter"
            class="filter"
            type="text"
            placeholder="Filter by name…"
            aria-label="Filter processes by name"
          />
        </div>
        <div class="table-scroll">
          <table class="ptable full">
            <thead>
              <tr>
                <th class="sortable" :aria-sort="ariaSort('name')" @click="sortBy('name')">
                  Process<span class="caret" v-if="sortKey === 'name'">{{ sortDesc ? '▾' : '▴' }}</span>
                </th>
                <th class="t-num sortable" :aria-sort="ariaSort('pid')" @click="sortBy('pid')">
                  PID<span class="caret" v-if="sortKey === 'pid'">{{ sortDesc ? '▾' : '▴' }}</span>
                </th>
                <th class="t-user">User</th>
                <th class="t-num sortable" :aria-sort="ariaSort('cpu_pct')" @click="sortBy('cpu_pct')">
                  CPU%<span class="caret" v-if="sortKey === 'cpu_pct'">{{ sortDesc ? '▾' : '▴' }}</span>
                </th>
                <th class="t-num sortable" :aria-sort="ariaSort('mem_pct')" @click="sortBy('mem_pct')">
                  MEM%<span class="caret" v-if="sortKey === 'mem_pct'">{{ sortDesc ? '▾' : '▴' }}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in filteredProcesses" :key="p.pid">
                <td class="t-name">{{ p.name }}</td>
                <td class="t-num muted">{{ p.pid }}</td>
                <td class="t-user muted">{{ p.user ?? '—' }}</td>
                <td class="t-num">{{ p.cpu_pct.toFixed(1) }}</td>
                <td class="t-num">{{ p.mem_pct.toFixed(1) }}</td>
              </tr>
              <tr v-if="!filteredProcesses.length">
                <td colspan="5" class="empty">{{ filter ? 'No matching processes.' : 'No process data.' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.proc { display: flex; flex-direction: column; gap: 16px; }
.proc-head { display: flex; align-items: center; justify-content: space-between; }
.proc-head h3 { font-size: 15px; color: var(--text); font-weight: 600; }
.proc-meta { display: flex; align-items: center; gap: 12px; }
.ago { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.ago.stale-amber { color: var(--amber, #f59e0b); }
.ago.stale-red { color: var(--red, #ef4444); }

.live-badge {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 999px;
  background: var(--surface-2); color: var(--muted); border: 1px solid var(--border);
}
.live-badge .dot { font-size: 9px; line-height: 1; }
.live-badge.on { color: var(--green, #22c55e); border-color: rgba(34, 197, 94, 0.4); background: rgba(34, 197, 94, 0.1); }

.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 880px) { .grid { grid-template-columns: 1fr; } }

.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }
.card h4 { font-size: 13px; color: var(--text); margin-bottom: 12px; font-weight: 600; }

.ptable { width: 100%; border-collapse: collapse; font-size: 13px; }
.ptable th {
  text-align: left; color: var(--muted); font-size: 11px; font-weight: 500;
  text-transform: uppercase; letter-spacing: 0.05em; padding: 6px 8px;
  border-bottom: 1px solid var(--border); white-space: nowrap;
}
.ptable td { padding: 7px 8px; color: var(--text); border-bottom: 1px solid var(--border); }
.ptable tbody tr:last-child td { border-bottom: none; }
.ptable .t-num { text-align: right; font-variant-numeric: tabular-nums; }
.ptable .t-name { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.t-bar-cell { padding-right: 16px; }
.muted { color: var(--muted); }

.sortable { cursor: pointer; user-select: none; }
.sortable:hover { color: var(--text); }
.caret { margin-left: 4px; color: var(--accent-2); }

.all-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.all-head h4 { margin-bottom: 0; }
.filter {
  background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px;
  color: var(--text); font-size: 13px; padding: 7px 12px; min-width: 220px; outline: none;
}
.filter:focus { border-color: var(--accent); }
.filter::placeholder { color: var(--muted); }

.table-scroll { max-height: 420px; overflow-y: auto; }
.empty { color: var(--muted); font-size: 13px; text-align: center; padding: 16px 0; }
</style>
