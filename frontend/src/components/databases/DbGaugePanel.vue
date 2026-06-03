<script setup lang="ts">
import { computed } from 'vue'
import MetricChart from '@/components/charts/MetricChart.vue'

/**
 * Radial gauge panel used by the Connections and Buffer-Pool-Hit gauges.
 * Renders a graceful "no data" state when `value` is null (no MariaDB).
 */
const props = defineProps<{
  title: string
  /** 0–100 percentage to plot, or null when no data. */
  value: number | null
  /** Big centre label, e.g. "24 / 151" or "98.4%". */
  centerLabel: string
  subLabel?: string
  /** [amber, red] thresholds on the percentage; used to colour the ring. */
  warnAt?: number
  dangerAt?: number
  /** true → low values are bad (buffer pool); false → high values are bad. */
  lowIsBad?: boolean
  loading?: boolean
}>()

const pct = computed(() => (props.value == null ? 0 : Math.max(0, Math.min(100, props.value))))
const hasData = computed(() => props.value != null)

const ringColor = computed<string[]>(() => {
  const v = props.value
  if (v == null) return ['#6366f1']
  // Buffer-pool style: low values are bad (red < 90, amber 90–94, green ≥ 95).
  if (props.lowIsBad) {
    if (v >= 95) return ['#22c55e']
    if (v >= 90) return ['#f59e0b']
    return ['#ef4444']
  }
  // Utilisation style: high values are bad.
  const warn = props.warnAt ?? 60
  const danger = props.dangerAt ?? 80
  if (v >= danger) return ['#ef4444']
  if (v >= warn) return ['#f59e0b']
  return ['#22c55e']
})
</script>

<template>
  <div class="gauge-panel">
    <h3 class="g-title">{{ title }}</h3>

    <div v-if="loading" class="g-empty">
      <div class="g-skeleton"></div>
    </div>

    <template v-else-if="hasData">
      <div class="g-chart">
        <MetricChart
          type="radialBar"
          :series="[pct]"
          :labels="[title]"
          :colors="ringColor"
          :height="170"
        />
        <div class="g-center">{{ centerLabel }}</div>
      </div>
      <span v-if="subLabel" class="g-sub">{{ subLabel }}</span>
    </template>

    <div v-else class="g-empty">
      <div class="g-ring-empty">
        <span class="g-na">—</span>
      </div>
      <span class="g-sub muted">No data yet</span>
    </div>
  </div>
</template>

<style scoped>
.gauge-panel {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 16px 18px; display: flex; flex-direction: column; align-items: center;
}
.g-title { font-size: 13px; font-weight: 600; color: var(--text); align-self: flex-start; margin-bottom: 4px; }
.g-chart { position: relative; width: 100%; display: flex; justify-content: center; }
.g-center {
  position: absolute; top: 50%; left: 50%; transform: translate(-50%, -40%);
  font-size: 18px; font-weight: 700; color: #fff; font-variant-numeric: tabular-nums; pointer-events: none;
}
.g-sub { font-size: 11px; color: var(--muted); margin-top: 2px; }
.g-sub.muted { color: var(--muted); }
.g-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 178px; gap: 8px; }
.g-ring-empty {
  width: 110px; height: 110px; border-radius: 50%; border: 8px solid var(--surface-2);
  display: flex; align-items: center; justify-content: center;
}
.g-na { font-size: 22px; color: var(--muted); font-weight: 700; }
.g-skeleton {
  width: 110px; height: 110px; border-radius: 50%;
  background: linear-gradient(90deg, var(--surface-2) 25%, rgba(255,255,255,0.05) 37%, var(--surface-2) 63%);
  background-size: 400% 100%; animation: shimmer 1.4s ease infinite;
}
@keyframes shimmer { 0% { background-position: 100% 0; } 100% { background-position: -100% 0; } }
@media (prefers-reduced-motion: reduce) { .g-skeleton { animation: none; } }
</style>
