<script setup lang="ts">
import { computed } from 'vue'
import { useMetricsStore } from '@/stores/metrics'
import type { MetricRange } from '@/types'

const props = defineProps<{ tabKey: string }>()
const metrics = useMetricsStore()

const RANGES: MetricRange[] = ['1h', '6h', '24h', '7d', '30d']
const current = computed(() => metrics.rangeFor(props.tabKey))
</script>

<template>
  <div class="ranges">
    <button
      v-for="r in RANGES" :key="r"
      class="range" :class="{ active: current === r }"
      @click="metrics.setRange(props.tabKey, r)"
    >{{ r }}</button>
  </div>
</template>

<style scoped>
.ranges { display: flex; gap: 4px; margin-bottom: 16px; }
.range {
  background: var(--surface-2); border: 1px solid var(--border); color: var(--muted);
  font-size: 12px; padding: 5px 10px; border-radius: 6px; cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.range.active { background: rgba(99,102,241,0.15); color: var(--accent-2); border-color: var(--accent); }
.range:hover:not(.active) { border-color: var(--accent); color: var(--text); }
</style>
