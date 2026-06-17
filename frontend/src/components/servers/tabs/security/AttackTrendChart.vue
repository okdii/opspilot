<script setup lang="ts">
import { computed } from 'vue'
import MetricChart from '@/components/charts/MetricChart.vue'
import type { TrendBucket } from '@/stores/attackers'

const props = defineProps<{ trend: TrendBucket[] }>()

const hasData = computed(() => props.trend.some(b => b.critical > 0 || b.warning > 0))

// Stacked-by-severity daily bars. MetricChart takes {name, data:[{x: epoch ms, y}]}
// per-series (same shape Fail2banChart.vue feeds it); `stacked` stacks the two
// severities into one bar per day.
const series = computed(() => [
  {
    name: 'Critical',
    data: props.trend.map(b => ({ x: new Date(b.date).getTime(), y: b.critical })),
  },
  {
    name: 'Warning',
    data: props.trend.map(b => ({ x: new Date(b.date).getTime(), y: b.warning })),
  },
])
</script>

<template>
  <section class="card">
    <h3>Attack volume (last 30 days)</h3>
    <div v-if="!hasData" class="no-data">No attacks recorded in this window</div>
    <MetricChart
      v-else
      type="bar"
      unit="count"
      :series="series"
      :height="200"
      :stacked="true"
      :colors="['#ef4444', '#f59e0b']"
    />
  </section>
</template>

<style scoped>
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
h3 { font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 12px; }
.no-data { color: var(--muted); font-size: 13px; padding: 24px 0; text-align: center; }
</style>
