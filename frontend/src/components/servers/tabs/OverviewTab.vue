<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import MetricChart from '@/components/charts/MetricChart.vue'
import { MetricBar } from '@/components/ui'
import { useMetricsStore } from '@/stores/metrics'
import { labeledList, realMounts, toApexSeries } from '@/utils/metrics'
import type { MetricRange } from '@/types'

const props = defineProps<{ range: MetricRange }>()
const metrics = useMetricsStore()

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

onMounted(() => loadAll(props.range))
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
.empty { color: var(--muted); font-size: 13px; }
</style>
