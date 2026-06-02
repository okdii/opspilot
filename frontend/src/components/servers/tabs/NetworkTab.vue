<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import MetricChart from '@/components/charts/MetricChart.vue'
import { useMetricsStore } from '@/stores/metrics'
import { labeledList, toApexSeries } from '@/utils/metrics'
import type { MetricRange, MetricSeries } from '@/types'

const props = defineProps<{ range: MetricRange }>()
const metrics = useMetricsStore()

const KEY = {
  throughput: 'network.throughput',
  packets: 'network.packets',
  errors: 'network.errors',
}

async function loadAll(range: MetricRange) {
  await Promise.all([
    metrics.loadChartData(['net.bytes_recv', 'net.bytes_sent'], range, KEY.throughput),
    metrics.loadChartData(['net.packets_recv', 'net.packets_sent'], range, KEY.packets),
    metrics.loadChartData(
      ['net.err_in', 'net.err_out', 'net.drop_in', 'net.drop_out'],
      range,
      KEY.errors,
    ),
  ])
}

onMounted(() => loadAll(props.range))
watch(() => props.range, (r) => loadAll(r))

// Distinct interface names come from the always-labeled latest values, so the
// selector works regardless of range (24h/7d/30d collapse chart-series labels).
const interfaces = computed<string[]>(() => {
  const names = labeledList(metrics.latestValues, 'net.bytes_recv')
    .map((e) => e.labels.interface)
    .filter((n): n is string => !!n)
  return Array.from(new Set(names)).sort()
})

const selected = ref<string | null>(null)

// Default to the first interface once it is known; keep selection valid.
watch(
  interfaces,
  (list) => {
    if (!list.length) return
    if (!selected.value || !list.includes(selected.value)) selected.value = list[0]
  },
  { immediate: true },
)

// When chart series carry an `interface` label, filter to the selected one;
// when labels are collapsed (no interface label), keep the series as-is.
function ifaceFilter(s: MetricSeries): boolean {
  if (!selected.value) return true
  if (!('interface' in s.labels)) return true
  return s.labels.interface === selected.value
}

const throughputSeries = computed(() =>
  toApexSeries(metrics.chartData[KEY.throughput]?.series ?? [], {
    filter: ifaceFilter,
    name: (s) => (s.metric_name === 'net.bytes_recv' ? '↓ In' : '↑ Out'),
  }),
)

const packetsSeries = computed(() =>
  toApexSeries(metrics.chartData[KEY.packets]?.series ?? [], {
    filter: ifaceFilter,
    name: (s) => (s.metric_name === 'net.packets_recv' ? 'In' : 'Out'),
  }),
)

const ERR_NAMES: Record<string, string> = {
  'net.err_in': 'Err In',
  'net.err_out': 'Err Out',
  'net.drop_in': 'Drop In',
  'net.drop_out': 'Drop Out',
}

const errorsSeries = computed(() =>
  toApexSeries(metrics.chartData[KEY.errors]?.series ?? [], {
    filter: ifaceFilter,
    name: (s) => ERR_NAMES[s.metric_name] ?? s.metric_name,
  }),
)
</script>

<template>
  <div class="net">
    <section class="card iface-bar">
      <span class="iface-label">Interface</span>
      <select v-if="interfaces.length > 1" v-model="selected" class="iface-select">
        <option v-for="iface in interfaces" :key="iface" :value="iface">{{ iface }}</option>
      </select>
      <span v-else-if="interfaces.length === 1" class="iface-name">{{ interfaces[0] }}</span>
      <span v-else class="iface-name empty">No interface data</span>
    </section>

    <section class="card">
      <h3>Throughput</h3>
      <MetricChart type="line" unit="bytes/s" :series="throughputSeries" :height="240" />
    </section>

    <section class="card">
      <h3>Packets/sec</h3>
      <MetricChart type="line" unit="count" :series="packetsSeries" :height="240" />
    </section>

    <section class="card">
      <h3>Errors &amp; Drops</h3>
      <MetricChart type="bar" unit="count" :series="errorsSeries" :height="240" />
    </section>
  </div>
</template>

<style scoped>
.net { display: flex; flex-direction: column; gap: 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }
.card h3 { font-size: 13px; color: var(--text); margin-bottom: 12px; font-weight: 600; }
.iface-bar { display: flex; align-items: center; gap: 12px; }
.iface-label { font-size: 13px; color: var(--muted); font-weight: 600; }
.iface-select {
  background: var(--surface2, #22263a);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 13px;
}
.iface-name { font-size: 13px; color: var(--text); font-weight: 600; }
.iface-name.empty { color: var(--muted); font-weight: 400; }
</style>
