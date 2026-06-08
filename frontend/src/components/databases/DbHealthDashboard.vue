<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { StatCard } from '@/components/ui'
import DbChartPanel from './DbChartPanel.vue'
import DbGaugePanel from './DbGaugePanel.vue'
import { useDatabaseStore } from '@/stores/databases'
import type { DbCredentialStatus, DbMetricName, DbSeriesPoint } from '@/stores/databases'
import type { MetricRange } from '@/types'

const props = defineProps<{
  serverId: string
  serverName: string
  status: DbCredentialStatus
  canEdit: boolean
  dbType?: 'mysql' | 'postgres'
}>()
const emit = defineEmits<{ (e: 'edit'): void; (e: 'remove'): void }>()

const store = useDatabaseStore()

const RANGES: MetricRange[] = ['1h', '6h', '24h', '7d', '30d']
const range = ref<MetricRange>('1h')

const menuOpen = ref(false)
const advancedOpen = ref(false)
const replicationOpen = ref(true)

const loadingSeries = ref(false)

// Each chart's plotted series, kept as Apex datetime tuples.
type Series = { name: string; data: [number, number | null][] }[]
const seriesByMetric = ref<Record<string, Series>>({})
const connectionsMax = ref<number | null>(null)

const latest = computed(() => store.latestFor(props.serverId))
const isReplica = computed(() => props.status.is_replica ?? false)

function toTuples(points: DbSeriesPoint[]): [number, number | null][] {
  return points.map((p) => [Date.parse(p.time), p.value])
}
function hasPoints(metric: string): boolean {
  const s = seriesByMetric.value[metric]
  return !!s && s.some((ser) => ser.data.length > 0)
}

const METRICS: DbMetricName[] = [
  'connections_active',
  'queries_per_sec',
  'slow_queries_per_min',
  'innodb_deadlocks',
  'table_locks_waited',
  'aborted_connections',
]

const PG_METRICS = [
  'connections_active',
  'transactions_per_sec',
  'cache_hit_rate',
  'deadlocks',
  'tuple_ops_per_sec',
  'temp_files_per_min',
  'checkpoints_per_min',
]

async function loadSeries() {
  loadingSeries.value = true
  try {
    const wanted = props.dbType === 'postgres' ? [...PG_METRICS] : [...METRICS]
    if (isReplica.value) wanted.push('replication_lag_sec')
    const results = await Promise.all(
      wanted.map((m) =>
        store
          .fetchSeries(props.serverId, m as any, range.value)
          .then((r) => ({ metric: m, r }))
          .catch(() => ({ metric: m, r: null })),
      ),
    )
    const next: Record<string, Series> = {}
    for (const { metric, r } of results) {
      if (!r) {
        next[metric] = []
        continue
      }
      next[metric] = [{ name: metric, data: toTuples(r.data) }]
      if (metric === 'connections_active') connectionsMax.value = r.connections_max ?? null
    }
    seriesByMetric.value = next
  } finally {
    loadingSeries.value = false
  }
}

async function reload() {
  await Promise.all([store.fetchLatest(props.serverId), loadSeries()])
}

onMounted(reload)
watch(() => props.serverId, reload)
watch(range, loadSeries)

// --- Stat-card derived values ---------------------------------------------
const connCardAccent = computed<'success' | 'warning' | 'danger'>(() => {
  const p = store.connectionPct(props.serverId)
  if (p > 80) return 'danger'
  if (p > 60) return 'warning'
  return 'success'
})
const bufferAccent = computed<'success' | 'danger' | 'warning'>(() => {
  const v = latest.value.innodb_buffer_pool_hit_rate
  if (v == null) return 'success'
  if (v < 90) return 'danger'
  if (v < 95) return 'warning'
  return 'success'
})

function fmt(v: number | null, suffix = ''): string {
  if (v == null) return '—'
  return `${Number.isInteger(v) ? v : v.toFixed(1)}${suffix}`
}

const connValue = computed(() => {
  const l = latest.value
  if (l.connections_active == null) return '—'
  return `${l.connections_active} / ${l.connections_max ?? '?'}`
})
const connSub = computed(() => {
  const p = store.connectionPct(props.serverId)
  return latest.value.connections_active == null ? 'no data' : `${p}% of max`
})

// Connections gauge centre + value
const connGaugeValue = computed(() => store.connectionPct(props.serverId) || (latest.value.connections_active == null ? null : 0))
const bufferGaugeValue = computed(() => latest.value.innodb_buffer_pool_hit_rate)

// --- Replication banner ----------------------------------------------------
type BannerTone = 'ok' | 'warn' | 'down' | 'nodata'
const replicationBanner = computed<{ tone: BannerTone; text: string }>(() => {
  const l = latest.value
  if (l.replication_running == null) return { tone: 'nodata', text: 'Replication status not yet collected' }
  if (l.replication_running === false) return { tone: 'down', text: 'Replication Stopped — alert fired' }
  const lag = l.replication_lag_sec ?? 0
  if (lag > 30) return { tone: 'warn', text: `Replication Lag: ${lag}s behind master` }
  return { tone: 'ok', text: `Replication Running · ${lag}s behind master` }
})

function lastCheckedLabel(): string {
  const t = props.status.last_checked
  if (!t) return 'awaiting first collection'
  const secs = Math.floor((Date.now() - Date.parse(t)) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  return `${Math.floor(secs / 3600)}h ago`
}
const connected = computed(() => props.status.last_check_ok === true)
const connError = computed(() => props.status.last_check_ok === false)
</script>

<template>
  <div class="health">
    <!-- Header -->
    <div class="hd-header">
      <div class="hd-id">
        <h2 class="hd-name">
          {{ serverName }}
          <span class="hd-ver">{{ props.dbType === 'postgres' ? 'PostgreSQL' : (latest.mariadb_version ? `MariaDB ${latest.mariadb_version}` : 'MariaDB') }}</span>
        </h2>
        <div class="hd-meta">
          <span>{{ status.host }}:{{ status.port }}</span>
          <span class="dot">·</span>
          <span>Last checked: {{ lastCheckedLabel() }}</span>
          <span class="dot">·</span>
          <span v-if="connected" class="conn ok">Connected</span>
          <span v-else-if="connError" class="conn err">Connection Error</span>
          <span v-else class="conn pending">Deploying…</span>
        </div>
      </div>
      <div class="hd-actions" v-if="canEdit">
        <button class="btn ghost" type="button" @click="emit('edit')">Edit Credentials</button>
        <div class="menu-wrap">
          <button class="kebab" type="button" aria-label="Database actions" @click="menuOpen = !menuOpen">⋮</button>
          <div v-if="menuOpen" class="menu" @click="menuOpen = false">
            <button class="menu-item danger" type="button" @click="emit('remove')">Remove DB Monitoring</button>
          </div>
        </div>
      </div>
    </div>

    <!-- No-data hint when Telegraf connected but nothing flowing -->
    <div v-if="!latest.last_collected_at" class="flow-hint">
      No DB metrics received yet — verify the monitoring user has the required grants
      (PROCESS, REPLICATION CLIENT, SELECT) and that MariaDB is reachable at {{ status.host }}:{{ status.port }}.
    </div>

    <!-- MySQL / MariaDB panels -->
    <template v-if="dbType !== 'postgres'">
      <!-- Stat cards -->
      <div class="cards">
        <StatCard label="Connections" :value="connValue" :accent="connCardAccent" />
        <StatCard label="Queries / sec" :value="latest.queries_per_sec == null ? '—' : `${fmt(latest.queries_per_sec)} qps`" accent="info" />
        <StatCard label="Buffer Pool Hit" :value="fmt(latest.innodb_buffer_pool_hit_rate, '%')" :accent="bufferAccent" />
        <StatCard label="Slow Queries" :value="latest.slow_queries_per_min == null ? '—' : `${fmt(latest.slow_queries_per_min)} /min`" accent="warning" />
      </div>
      <div class="cards-sub">
        <span>Nearing 100% means new app connections will be rejected — alert fires at 80%.</span>
        <span>Traffic baseline — sudden spikes reveal runaway loops or unexpected load.</span>
        <span>Reads served from RAM vs disk. Below 95% means your DB needs more memory.</span>
        <span>Rising values mean missing indexes or queries exceeding the slow query threshold.</span>
      </div>

      <!-- Range tabs -->
      <div class="ranges">
        <button
          v-for="r in RANGES" :key="r"
          class="range" :class="{ active: range === r }"
          type="button" @click="range = r"
        >{{ r }}</button>
      </div>

      <!-- Connections row: gauge + line -->
      <div class="grid grid-2-1">
        <DbGaugePanel
          title="Connections"
          :value="connGaugeValue"
          :center-label="connValue"
          :sub-label="latest.connections_max ? '' : 'max_connections not available'"
          :warn-at="60"
          :danger-at="80"
          :loading="store.loadingLatest"
        />
        <DbChartPanel
          title="Active Connections"
          subtitle="Rising count means more concurrent app load. Alert fires at 80% of max."
          type="line"
          :series="seriesByMetric.connections_active ?? []"
          :has-data="hasPoints('connections_active')"
          unit="count"
          :loading="loadingSeries"
        />
      </div>

      <!-- QPS area -->
      <DbChartPanel
        title="Queries Per Second"
        subtitle="Sudden spikes reveal traffic bursts or runaway background jobs."
        type="area"
        :series="seriesByMetric.queries_per_sec ?? []"
        :has-data="hasPoints('queries_per_sec')"
        unit="count"
        :loading="loadingSeries"
      />

      <!-- Slow queries + buffer pool gauge -->
      <div class="grid grid-2-1">
        <DbChartPanel
          title="Slow Queries"
          subtitle="Persistently high means a query needs optimization or an index is missing."
          type="bar"
          :series="seriesByMetric.slow_queries_per_min ?? []"
          :has-data="hasPoints('slow_queries_per_min')"
          unit="count"
          :colors="['#f59e0b']"
          :loading="loadingSeries"
        />
        <DbGaugePanel
          title="Buffer Pool Hit"
          :value="bufferGaugeValue"
          :center-label="fmt(latest.innodb_buffer_pool_hit_rate, '%')"
          sub-label="Target ≥ 95%"
          :low-is-bad="true"
          :loading="store.loadingLatest"
        />
      </div>

      <!-- Deadlocks -->
      <DbChartPanel
        title="Deadlocks"
        subtitle="Any deadlock means two transactions blocked each other — one silently failed."
        type="bar"
        :series="seriesByMetric.innodb_deadlocks ?? []"
        :has-data="hasPoints('innodb_deadlocks')"
        unit="count"
        :colors="['#ef4444']"
        :loading="loadingSeries"
      />

      <!-- Replication (replica only) -->
      <section v-if="isReplica" class="collapsible">
        <button class="collapse-hdr" type="button" @click="replicationOpen = !replicationOpen">
          <span class="caret" :class="{ open: replicationOpen }">▸</span>
          Replication Status
        </button>
        <div v-show="replicationOpen" class="collapse-body">
          <div class="repl-banner" :class="replicationBanner.tone">{{ replicationBanner.text }}</div>
          <DbChartPanel
            title="Replication Lag"
            subtitle="Over 30s means reads from the replica return stale data."
            type="line"
            :series="seriesByMetric.replication_lag_sec ?? []"
            :has-data="hasPoints('replication_lag_sec')"
            unit="count"
            :thresholds="[{ value: 30, color: '#ef4444', label: '30s' }]"
            :loading="loadingSeries"
          />
        </div>
      </section>

      <!-- Advanced -->
      <section class="collapsible">
        <button class="collapse-hdr" type="button" @click="advancedOpen = !advancedOpen">
          <span class="caret" :class="{ open: advancedOpen }">▸</span>
          Advanced Metrics
        </button>
        <div v-show="advancedOpen" class="collapse-body grid grid-2">
          <DbChartPanel
            title="Table Lock Waits"
            subtitle="High waits mean queries are blocking each other — often from missing indexes."
            type="line"
            :series="seriesByMetric.table_locks_waited ?? []"
            :has-data="hasPoints('table_locks_waited')"
            unit="count"
            :thresholds="[{ value: 10, color: '#f59e0b', label: '10/min' }]"
            :loading="loadingSeries"
            empty-message="No table-lock data for this period — not all MariaDB versions emit it."
          />
          <DbChartPanel
            title="Aborted Connections"
            subtitle="Clients failing to connect — check credentials, firewall, or app config."
            type="line"
            :series="seriesByMetric.aborted_connections ?? []"
            :has-data="hasPoints('aborted_connections')"
            unit="count"
            :thresholds="[{ value: 5, color: '#f59e0b', label: '5/min' }]"
            :loading="loadingSeries"
            empty-message="No aborted-connection data for this period."
          />
        </div>
      </section>
    </template>

    <!-- PostgreSQL panels -->
    <template v-else>
      <!-- PostgreSQL stat cards -->
      <div class="cards">
        <StatCard label="Active Connections" :value="fmt(latest.connections_active)" accent="info" />
        <StatCard label="Transactions/sec" :value="fmt(latest.transactions_per_sec)" accent="info" />
        <StatCard label="Cache Hit Rate" :value="fmt(latest.cache_hit_rate, '%')" :accent="latest.cache_hit_rate != null && latest.cache_hit_rate < 99 ? 'danger' : 'success'" />
        <StatCard label="Deadlocks" :value="fmt(latest.deadlocks)" accent="warning" />
      </div>
      <div class="cards-sub">
        <span>Nearing max_connections means new app connections will be rejected.</span>
        <span>Sudden drops reveal connection failures or application errors.</span>
        <span>Below 99% means frequent disk reads — tune shared_buffers or add RAM.</span>
        <span>Any deadlock means two transactions blocked each other — one silently failed.</span>
      </div>

      <!-- Range tabs (reuse existing) -->
      <div class="ranges">
        <button v-for="r in RANGES" :key="r" class="range" :class="{ active: range === r }" type="button" @click="range = r">{{ r }}</button>
      </div>

      <!-- Tuple Ops + Temp Files -->
      <div class="grid grid-2">
        <DbChartPanel
          title="Tuple Operations/sec"
          subtitle="Combined inserts + updates + deletes — reflects write load on the database."
          type="area"
          :series="seriesByMetric.tuple_ops_per_sec ?? []"
          :has-data="hasPoints('tuple_ops_per_sec')"
          unit="count"
          :loading="loadingSeries"
        />
        <DbChartPanel
          title="Temp Files/min"
          subtitle="Spilling to disk means queries need more work_mem or indexes are missing."
          type="bar"
          :colors="['#f59e0b']"
          :series="seriesByMetric.temp_files_per_min ?? []"
          :has-data="hasPoints('temp_files_per_min')"
          unit="count"
          :loading="loadingSeries"
        />
      </div>

      <!-- Checkpoints + Transactions -->
      <div class="grid grid-2">
        <DbChartPanel
          title="Checkpoints/min"
          subtitle="Frequent checkpoints mean heavy write load — consider tuning checkpoint_timeout."
          type="line"
          :series="seriesByMetric.checkpoints_per_min ?? []"
          :has-data="hasPoints('checkpoints_per_min')"
          unit="count"
          :loading="loadingSeries"
        />
        <DbChartPanel
          title="Transactions/sec"
          subtitle="Sudden drops reveal connection failures or application errors."
          type="area"
          :series="seriesByMetric.transactions_per_sec ?? []"
          :has-data="hasPoints('transactions_per_sec')"
          unit="count"
          :loading="loadingSeries"
        />
      </div>

      <!-- Replication (replica only) -->
      <section v-if="isReplica" class="collapsible">
        <button class="collapse-hdr" type="button" @click="replicationOpen = !replicationOpen">
          <span class="caret" :class="{ open: replicationOpen }">▸</span>
          Replication Status
        </button>
        <div v-show="replicationOpen" class="collapse-body">
          <div class="repl-banner" :class="replicationBanner.tone">{{ replicationBanner.text }}</div>
          <DbChartPanel
            title="Replication Lag"
            subtitle="Over a few seconds means reads from the replica return stale data."
            type="line"
            :series="seriesByMetric.replication_lag_sec ?? []"
            :has-data="hasPoints('replication_lag_sec')"
            unit="count"
            :thresholds="[{ value: 30, color: '#ef4444', label: '30s' }]"
            :loading="loadingSeries"
          />
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.health { display: flex; flex-direction: column; gap: 16px; }
.hd-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.hd-name { font-size: 18px; color: #fff; display: flex; align-items: baseline; gap: 10px; }
.hd-ver { font-size: 12px; color: var(--muted); font-weight: 500; }
.hd-meta { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted); margin-top: 4px; flex-wrap: wrap; }
.dot { opacity: 0.5; }
.conn.ok { color: var(--green); }
.conn.err { color: var(--red); }
.conn.pending { color: var(--amber); }
.hd-actions { display: flex; align-items: center; gap: 8px; }
.btn { border-radius: 8px; font-size: 12px; font-weight: 600; padding: 8px 14px; cursor: pointer; border: 1px solid transparent; min-height: 36px; }
.btn.ghost { background: var(--surface-2); border-color: var(--border); color: var(--text); }
.btn.ghost:hover { border-color: var(--accent); color: var(--accent-2); }
.menu-wrap { position: relative; }
.kebab { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; width: 36px; height: 36px; color: var(--text); cursor: pointer; font-size: 16px; }
.menu { position: absolute; right: 0; top: calc(100% + 6px); background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 4px; min-width: 190px; z-index: 20; box-shadow: 0 12px 30px rgba(0,0,0,0.4); }
.menu-item { display: block; width: 100%; text-align: left; background: none; border: none; color: var(--text); font-size: 13px; padding: 9px 10px; border-radius: 6px; cursor: pointer; }
.menu-item.danger { color: var(--red); }
.menu-item.danger:hover { background: rgba(239,68,68,0.12); }
.flow-hint { background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.25); border-radius: 8px; padding: 10px 14px; font-size: 12px; color: var(--amber); line-height: 1.5; }
.cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.cards-sub { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; font-size: 11px; color: var(--muted); margin-top: -8px; padding: 0 4px; }
.ranges { display: flex; gap: 4px; }
.range { background: var(--surface-2); border: 1px solid var(--border); color: var(--muted); font-size: 12px; padding: 6px 12px; border-radius: 6px; cursor: pointer; min-height: 32px; }
.range.active { background: rgba(99,102,241,0.15); color: var(--accent-2); border-color: var(--accent); }
.grid { display: grid; gap: 14px; }
.grid-2 { grid-template-columns: 1fr 1fr; }
.grid-2-1 { grid-template-columns: 320px 1fr; }
.collapsible { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
.collapse-hdr { width: 100%; text-align: left; background: none; border: none; color: var(--text); font-size: 13px; font-weight: 600; padding: 14px 18px; cursor: pointer; display: flex; align-items: center; gap: 8px; }
.caret { display: inline-block; transition: transform 0.15s; color: var(--muted); }
.caret.open { transform: rotate(90deg); }
.collapse-body { padding: 0 18px 18px; }
.repl-banner { border-radius: 8px; padding: 12px 16px; font-size: 13px; font-weight: 500; margin-bottom: 14px; }
.repl-banner.ok { background: rgba(34,197,94,0.12); color: var(--green); border: 1px solid rgba(34,197,94,0.3); }
.repl-banner.warn { background: rgba(245,158,11,0.12); color: var(--amber); border: 1px solid rgba(245,158,11,0.3); }
.repl-banner.down { background: rgba(239,68,68,0.12); color: var(--red); border: 1px solid rgba(239,68,68,0.3); }
.repl-banner.nodata { background: var(--surface-2); color: var(--muted); border: 1px solid var(--border); }
@media (max-width: 900px) {
  .cards, .cards-sub { grid-template-columns: repeat(2, 1fr); }
  .grid-2, .grid-2-1 { grid-template-columns: 1fr; }
}
</style>
