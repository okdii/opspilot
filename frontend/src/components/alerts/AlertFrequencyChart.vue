<script setup lang="ts">
import { computed } from 'vue'
import MetricChart from '@/components/charts/MetricChart.vue'
import type { FrequencyBucket } from '@/types'

const props = defineProps<{ buckets: FrequencyBucket[] }>()

const categories = computed(() =>
  props.buckets.map((b) => {
    const d = new Date(b.date + 'T00:00:00')
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }),
)

const series = computed(() => [
  { name: 'Critical', data: props.buckets.map((b) => b.critical) },
  { name: 'Warning', data: props.buckets.map((b) => b.warning) },
])

const hasData = computed(() => props.buckets.some((b) => b.critical > 0 || b.warning > 0))
</script>

<template>
  <section class="freq-card">
    <header class="fc-head">
      <h2 class="fc-title">Alert Frequency</h2>
      <span class="fc-sub">Last 30 days</span>
    </header>
    <MetricChart
      type="bar"
      unit="count"
      :series="series"
      :categories="categories"
      :stacked="true"
      :height="200"
      :colors="['#ef4444', '#f59e0b']"
    />
    <p v-if="!hasData" class="fc-empty">No alerts fired in the last 30 days.</p>
  </section>
</template>

<style scoped>
.freq-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px 18px;
  margin-bottom: 16px;
  position: relative;
}
.fc-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; }
.fc-title { font-size: 13px; font-weight: 600; color: #fff; }
.fc-sub { font-size: 11px; color: var(--muted); }
.fc-empty {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  color: var(--muted); font-size: 13px; pointer-events: none;
}
</style>
