<script setup lang="ts">
import { computed } from 'vue'
import MetricChart from '@/components/charts/MetricChart.vue'
import type { MetricChartType, MetricThreshold, MetricUnit } from '@/components/charts/MetricChart.vue'

/**
 * Shared panel wrapper for every DB chart: title, optional sub-label, and a
 * graceful "no data yet" state when the series is empty (the test VM has no
 * MariaDB, so this is the default path). Wraps the app-wide MetricChart.
 */
const props = withDefaults(
  defineProps<{
    title: string
    subtitle?: string
    type: MetricChartType
    /** ApexAxisChartSeries-shaped data. Empty → show no-data state. */
    series: unknown[]
    /** true when at least one series has data points. */
    hasData: boolean
    unit?: MetricUnit
    thresholds?: MetricThreshold[]
    colors?: string[]
    height?: number
    loading?: boolean
    /** Custom empty message (e.g. grants hint). */
    emptyMessage?: string
  }>(),
  { height: 240 },
)

const empty = computed(() => !props.loading && !props.hasData)
</script>

<template>
  <div class="panel">
    <div class="panel-hdr">
      <h3 class="panel-title">{{ title }}</h3>
      <span v-if="subtitle" class="panel-sub">{{ subtitle }}</span>
    </div>

    <div class="panel-body" :style="{ minHeight: `${height}px` }">
      <div v-if="loading" class="state">
        <div class="skeleton" :style="{ height: `${height - 20}px` }"></div>
      </div>

      <div v-else-if="empty" class="state no-data">
        <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M3 3v18h18" />
          <path d="M7 14l3-3 3 3 4-5" stroke-dasharray="3 3" />
        </svg>
        <span class="nd-title">No data yet</span>
        <span class="nd-msg">{{ emptyMessage || 'Metrics will appear once Telegraf starts collecting from MariaDB.' }}</span>
      </div>

      <MetricChart
        v-else
        :type="type"
        :series="series as never"
        :unit="unit"
        :thresholds="thresholds"
        :colors="colors"
        :height="height"
      />
    </div>
  </div>
</template>

<style scoped>
.panel {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 16px 18px; display: flex; flex-direction: column;
}
.panel-hdr { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 6px; gap: 8px; }
.panel-title { font-size: 13px; font-weight: 600; color: var(--text); }
.panel-sub { font-size: 11px; color: var(--muted); }
.panel-body { display: flex; flex-direction: column; justify-content: center; }
.state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 6px; flex: 1; color: var(--muted); text-align: center; padding: 16px;
}
.no-data .nd-title { font-size: 13px; color: var(--text); font-weight: 500; }
.no-data .nd-msg { font-size: 11.5px; color: var(--muted); max-width: 280px; line-height: 1.5; }
.skeleton {
  width: 100%; border-radius: 8px;
  background: linear-gradient(90deg, var(--surface-2) 25%, rgba(255,255,255,0.04) 37%, var(--surface-2) 63%);
  background-size: 400% 100%; animation: shimmer 1.4s ease infinite;
}
@keyframes shimmer { 0% { background-position: 100% 0; } 100% { background-position: -100% 0; } }
@media (prefers-reduced-motion: reduce) { .skeleton { animation: none; } }
</style>
