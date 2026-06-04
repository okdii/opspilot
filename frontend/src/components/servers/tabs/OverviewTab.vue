<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import MetricChart from '@/components/charts/MetricChart.vue'
import { MetricBar, StatusBadge } from '@/components/ui'
import { getServerMonitoring } from '@/services/api'
import { useMetricsStore } from '@/stores/metrics'
import { labeledList, realMounts, toApexSeries } from '@/utils/metrics'
import type { MetricRange, MonitoringService } from '@/types'

const props = defineProps<{ range: MetricRange }>()
const metrics = useMetricsStore()

const monitoringChecks = ref<MonitoringService[]>([])
const monitoringLoaded = ref(false)

async function loadMonitoring() {
  const id = metrics.activeServerId
  if (!id) return
  try {
    monitoringChecks.value = await getServerMonitoring(id)
  } catch {
    // non-critical — silently skip
  } finally {
    monitoringLoaded.value = true
  }
}

const KEY = {
  cpu: 'overview.cpu',
  mem: 'overview.mem',
  net: 'overview.net',
  load: 'overview.load',
}

async function loadAll(range: MetricRange) {
  await Promise.all([
    metrics.loadChartData(['cpu.usage_active'], range, KEY.cpu),
    metrics.loadChartData(['mem.used_percent', 'mem.available_percent'], range, KEY.mem),
    metrics.loadChartData(['net.bytes_recv', 'net.bytes_sent'], range, KEY.net),
    metrics.loadChartData(['system.load1', 'system.load5', 'system.load15'], range, KEY.load),
  ])
}

onMounted(() => { loadMonitoring(); loadAll(props.range) })
watch(() => props.range, (r) => loadAll(r))

const cpuSeries = computed(() =>
  toApexSeries(metrics.chartData[KEY.cpu]?.series ?? [], {
    filter: (s) => s.labels.cpu === 'cpu-total',
    name: () => 'CPU',
  }),
)
const memSeries = computed(() =>
  toApexSeries(metrics.chartData[KEY.mem]?.series ?? [], {
    name: (s) => (s.metric_name === 'mem.used_percent' ? 'Used' : 'Available'),
  }),
)
const netSeries = computed(() =>
  toApexSeries(metrics.chartData[KEY.net]?.series ?? [], {
    name: (s) => (s.metric_name === 'net.bytes_recv' ? '↓ In' : '↑ Out'),
  }),
)
const loadSeries = computed(() =>
  toApexSeries(metrics.chartData[KEY.load]?.series ?? [], {
    name: (s) => s.metric_name.replace('system.load', '') + 'm',
  }),
)

const disks = computed(() => realMounts(labeledList(metrics.latestValues, 'disk.used_percent')))
</script>

<template>
  <div class="ov">
    <section v-if="monitoringLoaded" class="card mon-card">
      <h3>Monitoring Checks</h3>
      <p v-if="!monitoringChecks.length" class="empty">No monitoring checks registered for this server.</p>
      <div v-else class="mon-list">
        <div class="mon-row" v-for="svc in monitoringChecks" :key="svc.id">
          <StatusBadge :status="svc.last_status ?? 'unknown'" kind="service" />
          <span class="mon-name">{{ svc.name }}</span>
          <span class="mon-type" :class="`type-${svc.type}`">{{ svc.type.toUpperCase() }}</span>
          <span class="mon-url">{{ svc.type === 'http' ? svc.url : `${svc.url}:${svc.port}` }}</span>
          <span v-if="svc.uptime_24h != null" class="mon-uptime">{{ svc.uptime_24h.toFixed(1) }}% 24h</span>
        </div>
      </div>
    </section>

    <section class="card">
      <h3>CPU Usage</h3>
      <MetricChart type="area" unit="%" :series="cpuSeries" :height="240" />
    </section>

    <section class="card">
      <h3>Memory Usage</h3>
      <MetricChart type="line" unit="%" :series="memSeries" :height="240" />
    </section>

    <section class="card">
      <h3>Disk Space</h3>
      <div v-if="disks.length" class="disk-bars">
        <MetricBar
          v-for="d in disks"
          :key="d.labels.path"
          :label="d.labels.path ?? 'disk'"
          :value="d.value"
        />
      </div>
      <p v-else class="empty">No disk data.</p>
    </section>

    <section class="card">
      <h3>Network Throughput</h3>
      <MetricChart type="line" unit="bytes/s" :series="netSeries" :height="240" />
    </section>

    <section class="card">
      <h3>Load Average</h3>
      <MetricChart type="line" unit="count" :series="loadSeries" :height="240" />
    </section>
  </div>
</template>

<style scoped>
.ov { display: flex; flex-direction: column; gap: 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }
.card h3 { font-size: 13px; color: var(--text); margin-bottom: 12px; font-weight: 600; }
.disk-bars { display: flex; flex-direction: column; gap: 12px; }
.empty { color: var(--muted); font-size: 13px; margin: 0; }

.mon-list { display: flex; flex-direction: column; gap: 8px; }
.mon-row { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.mon-name { font-weight: 500; min-width: 100px; }
.mon-type { font-size: 11px; font-weight: 700; padding: 2px 6px; border-radius: 4px; letter-spacing: 0.04em; }
.type-http { background: rgba(59,130,246,0.15); color: #60a5fa; }
.type-tcp  { background: rgba(168,85,247,0.15); color: #c084fc; }
.type-db   { background: rgba(234,179,8,0.15);  color: #facc15; }
.mon-url { color: var(--muted); font-family: monospace; font-size: 12px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mon-uptime { color: var(--muted); font-size: 12px; white-space: nowrap; }
</style>
