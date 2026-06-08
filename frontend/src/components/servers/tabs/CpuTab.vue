<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import MetricChart from '@/components/charts/MetricChart.vue'
import { MetricBar } from '@/components/ui'
import { useMetricsStore } from '@/stores/metrics'
import { labeledList, pickLabel, toApexSeries } from '@/utils/metrics'
import type { MetricRange } from '@/types'
import RangePicker from './RangePicker.vue'

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

onMounted(() => loadAll(metrics.rangeFor('CPU')))
watch(() => metrics.rangeFor('CPU'), (r) => loadAll(r))

const usageSeries = computed(() =>
  toApexSeries(metrics.chartData[KEY.usage]?.series ?? [], {
    filter: (s) => s.labels.cpu === 'cpu-total',
    name: () => 'CPU',
  }),
)

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

// Stat cards — live from latestValues
const idle   = computed(() => pickLabel(metrics.latestValues, 'cpu.usage_idle',   'cpu', 'cpu-total'))
const active = computed(() => pickLabel(metrics.latestValues, 'cpu.usage_active', 'cpu', 'cpu-total'))
const user   = computed(() => pickLabel(metrics.latestValues, 'cpu.usage_user',   'cpu', 'cpu-total'))
const system = computed(() => pickLabel(metrics.latestValues, 'cpu.usage_system', 'cpu', 'cpu-total'))
const iowait = computed(() => pickLabel(metrics.latestValues, 'cpu.usage_iowait', 'cpu', 'cpu-total'))

function fmt(v: number | null) {
  return v == null ? '—' : v.toFixed(1) + '%'
}

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
    <RangePicker tab-key="CPU" />

    <!-- Stat cards -->
    <div class="stat-row">
      <div class="stat-card idle">
        <span class="stat-label">Idle</span>
        <span class="stat-value">{{ fmt(idle) }}</span>
      </div>
      <div class="stat-card active">
        <span class="stat-label">Active</span>
        <span class="stat-value">{{ fmt(active) }}</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">User</span>
        <span class="stat-value">{{ fmt(user) }}</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">System</span>
        <span class="stat-value">{{ fmt(system) }}</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">IO Wait</span>
        <span class="stat-value">{{ fmt(iowait) }}</span>
      </div>
    </div>

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

.stat-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}
.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.stat-card.idle  { border-color: rgba(34,197,94,0.3); }
.stat-card.active { border-color: rgba(239,68,68,0.25); }

.stat-label {
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
}
.stat-value {
  font-size: 24px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--text);
}
.stat-card.idle  .stat-value { color: var(--green); }
.stat-card.active .stat-value { color: var(--red); }

.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }
.card h3 { font-size: 13px; color: var(--text); margin-bottom: 12px; font-weight: 600; }
.core-bars { display: flex; flex-direction: column; gap: 12px; }
.empty { color: var(--muted); font-size: 13px; }
</style>
