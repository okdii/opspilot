<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import MetricChart from '@/components/charts/MetricChart.vue'
import { useMetricsStore } from '@/stores/metrics'
import { humanBytes, scalarValue, toApexSeries } from '@/utils/metrics'

function fmtPct(v: number | null) { return v == null ? '—' : v.toFixed(1) + '%' }
import type { MetricRange } from '@/types'
import RangePicker from './RangePicker.vue'

const metrics = useMetricsStore()

const KEY = {
  usage: 'mem.usage',
  swap: 'mem.swap',
}

async function loadAll(range: MetricRange) {
  await Promise.all([
    metrics.loadChartData(['mem.used_percent'], range, KEY.usage),
    metrics.loadChartData(['swap.used_percent'], range, KEY.swap),
  ])
}

onMounted(() => loadAll(metrics.rangeFor('Memory')))
watch(() => metrics.rangeFor('Memory'), (r) => loadAll(r))

const usageSeries = computed(() =>
  toApexSeries(metrics.chartData[KEY.usage]?.series ?? [], { name: () => 'Used' }),
)
const swapSeries = computed(() =>
  toApexSeries(metrics.chartData[KEY.swap]?.series ?? [], { name: () => 'Swap' }),
)

// --- RAM breakdown (current) ----------------------------------------------
// Local helper: convert a byte count to gigabytes for the breakdown bar.
const GB = 1024 ** 3
function toGB(bytes: number | null): number {
  return bytes == null ? 0 : bytes / GB
}

// Stat cards
const stats = computed(() => {
  const latest = metrics.latestValues
  return {
    usedPct:      scalarValue(latest, 'mem.used_percent'),
    availablePct: scalarValue(latest, 'mem.available_percent'),
    used:         scalarValue(latest, 'mem.used'),
    free:         scalarValue(latest, 'mem.free'),
    total:        scalarValue(latest, 'mem.total'),
  }
})

const breakdown = computed(() => {
  const latest = metrics.latestValues
  return {
    used:     scalarValue(latest, 'mem.used'),
    cached:   scalarValue(latest, 'mem.cached'),
    buffered: scalarValue(latest, 'mem.buffered'),
    free:     scalarValue(latest, 'mem.free'),
  }
})

const hasBreakdown = computed(() => {
  const b = breakdown.value
  return b.used != null || b.cached != null || b.buffered != null || b.free != null
})

// --- Swap ------------------------------------------------------------------
const swapTotal = computed(() => scalarValue(metrics.latestValues, 'swap.total'))
const hasSwap   = computed(() => (swapTotal.value ?? 0) > 0)

const swapBreakdown = computed(() => {
  const latest = metrics.latestValues
  return {
    used: scalarValue(latest, 'swap.used'),
    free: scalarValue(latest, 'swap.free'),
  }
})

// Horizontal stacked bar — one series per memory segment.
// When swap is present a second row "Swap" is appended; Cached/Buffers are
// 0 for that row so only Used and Free segments render.
const breakdownCategories = computed(() => hasSwap.value ? ['RAM', 'Swap'] : ['Memory'])

const breakdownSeries = computed(() => {
  const b = breakdown.value
  const s = swapBreakdown.value
  const withSwap = hasSwap.value
  return [
    { name: 'Used',    data: withSwap ? [toGB(b.used),     toGB(s.used)] : [toGB(b.used)] },
    { name: 'Cached',  data: withSwap ? [toGB(b.cached),   0]            : [toGB(b.cached)] },
    { name: 'Buffers', data: withSwap ? [toGB(b.buffered), 0]            : [toGB(b.buffered)] },
    { name: 'Free',    data: withSwap ? [toGB(b.free),     toGB(s.free)] : [toGB(b.free)] },
  ]
})

const breakdownLegend = computed(() => {
  const b = breakdown.value
  const s = swapBreakdown.value
  const base = [
    { label: 'Used',    text: humanBytes(b.used) },
    { label: 'Cached',  text: humanBytes(b.cached) },
    { label: 'Buffers', text: humanBytes(b.buffered) },
    { label: 'Free',    text: humanBytes(b.free) },
  ]
  if (!hasSwap.value) return base
  return [
    ...base,
    { label: 'Swap used', text: humanBytes(s.used) },
    { label: 'Swap free', text: humanBytes(s.free) },
  ]
})

const breakdownHeight = computed(() => hasSwap.value ? 140 : 100)
</script>

<template>
  <div class="mem">
    <RangePicker tab-key="Memory" />

    <!-- Stat cards -->
    <div class="stat-row">
      <div class="stat-card available">
        <span class="stat-label">Available</span>
        <span class="stat-value">{{ fmtPct(stats.availablePct) }}</span>
      </div>
      <div class="stat-card used">
        <span class="stat-label">Used</span>
        <span class="stat-value">{{ fmtPct(stats.usedPct) }}</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">Used</span>
        <span class="stat-value sm">{{ humanBytes(stats.used) }}</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">Free</span>
        <span class="stat-value sm">{{ humanBytes(stats.free) }}</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">Total</span>
        <span class="stat-value sm">{{ humanBytes(stats.total) }}</span>
      </div>
    </div>

    <section class="card">
      <h3>RAM Usage History</h3>
      <MetricChart type="area" unit="%" :series="usageSeries" :height="240" />
    </section>

    <section class="card">
      <h3>RAM Breakdown (current)</h3>
      <template v-if="hasBreakdown">
        <MetricChart
          type="bar"
          stacked
          horizontal
          unit="GB"
          :series="breakdownSeries"
          :categories="breakdownCategories"
          :height="breakdownHeight"
        />
        <div class="legend">
          <span v-for="seg in breakdownLegend" :key="seg.label" class="legend-item">
            <strong>{{ seg.text }}</strong> {{ seg.label }}
          </span>
        </div>
      </template>
      <p v-else class="empty">No memory data.</p>
    </section>

    <section class="card">
      <h3>Swap Usage History</h3>
      <template v-if="hasSwap">
        <MetricChart type="area" unit="%" :series="swapSeries" :height="240" />
        <p class="note">High swap usage = RAM pressure, risk of slowdown.</p>
      </template>
      <p v-else class="empty">No swap configured on this server.</p>
    </section>
  </div>
</template>

<style scoped>
.mem { display: flex; flex-direction: column; gap: 16px; }

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
.stat-card.available { border-color: rgba(34,197,94,0.3); }
.stat-card.used      { border-color: rgba(239,68,68,0.25); }
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
.stat-value.sm { font-size: 18px; }
.stat-card.available .stat-value { color: var(--green); }
.stat-card.used      .stat-value { color: var(--red); }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }
.card h3 { font-size: 13px; color: var(--text); margin-bottom: 12px; font-weight: 600; }
.legend { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 6px; font-size: 12px; color: var(--muted); }
.legend-item strong { color: var(--text); font-weight: 600; }
.note { color: var(--muted); font-size: 12px; margin-top: 8px; }
.empty { color: var(--muted); font-size: 13px; }
</style>
