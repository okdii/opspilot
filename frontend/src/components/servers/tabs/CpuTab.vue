<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import MetricChart from '@/components/charts/MetricChart.vue'
import { MetricBar } from '@/components/ui'
import { useMetricsStore } from '@/stores/metrics'
import { labeledList, toApexSeries } from '@/utils/metrics'
import type { MetricRange } from '@/types'

const props = defineProps<{ range: MetricRange }>()
const metrics = useMetricsStore()

const KEY = {
  usage: 'cpu.usage',
  breakdown: 'cpu.breakdown',
}

async function loadAll(range: MetricRange) {
  await Promise.all([
    metrics.loadChartData(['cpu.usage_active'], range, KEY.usage),
    metrics.loadChartData(
      ['cpu.usage_user', 'cpu.usage_system', 'cpu.usage_iowait', 'cpu.usage_steal'],
      range,
      KEY.breakdown,
    ),
  ])
}

onMounted(() => loadAll(props.range))
watch(() => props.range, (r) => loadAll(r))

// CPU Usage — total only (cpu='cpu-total').
// NOTE: AlertRule threshold overlay (spec §3.5) deferred to Phase 8 (AlertRules not built yet).
const usageSeries = computed(() =>
  toApexSeries(metrics.chartData[KEY.usage]?.series ?? [], {
    filter: (s) => s.labels.cpu === 'cpu-total',
    name: () => 'CPU',
  }),
)

// CPU Breakdown — stacked user/system/iowait/steal for cpu-total.
const BREAKDOWN_LABELS: Record<string, string> = {
  'cpu.usage_user': 'User',
  'cpu.usage_system': 'System',
  'cpu.usage_iowait': 'IO Wait',
  'cpu.usage_steal': 'Steal',
}
const breakdownSeries = computed(() =>
  toApexSeries(metrics.chartData[KEY.breakdown]?.series ?? [], {
    filter: (s) => s.labels.cpu === 'cpu-total',
    name: (s) => BREAKDOWN_LABELS[s.metric_name] ?? s.metric_name,
  }),
)

// Per-Core — live from latestValues; exclude the cpu-total aggregate.
const cores = computed(() =>
  labeledList(metrics.latestValues, 'cpu.usage_active').filter(
    (e) => e.labels.cpu !== 'cpu-total',
  ),
)
function coreLabel(cpu: string | undefined): string {
  return `Core ${(cpu ?? 'cpu').replace('cpu', '')}`
}
</script>

<template>
  <div class="cpu">
    <section class="card">
      <h3>CPU Usage</h3>
      <MetricChart type="area" unit="%" :series="usageSeries" :height="240" />
    </section>

    <section class="card">
      <h3>CPU Breakdown</h3>
      <MetricChart type="area" unit="%" stacked :series="breakdownSeries" :height="240" />
    </section>

    <section class="card">
      <h3>Per-Core Usage (current)</h3>
      <div v-if="cores.length" class="core-bars">
        <MetricBar
          v-for="c in cores"
          :key="c.labels.cpu"
          :label="coreLabel(c.labels.cpu)"
          :value="c.value"
        />
      </div>
      <p v-else class="empty">No per-core data.</p>
    </section>
  </div>
</template>

<style scoped>
.cpu { display: flex; flex-direction: column; gap: 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }
.card h3 { font-size: 13px; color: var(--text); margin-bottom: 12px; font-weight: 600; }
.core-bars { display: flex; flex-direction: column; gap: 12px; }
.empty { color: var(--muted); font-size: 13px; }
</style>
