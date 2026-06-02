<script setup lang="ts">
// STUB — filled in by Slice Disk (see docs/superpowers/plans/2026-06-02-server-detail-metrics.md).
// Receives the active range from ServerDetail; reads useMetricsStore like OverviewTab.
import type { MetricRange } from '@/types'
defineProps<{ range: MetricRange }>()
</script>

<template>
  <div class="tab-stub">
    <p>Disk metrics — coming in this slice.</p>
  </div>
</template>

<style scoped>
.tab-stub { background: var(--surface); border: 1px dashed var(--border); border-radius: 12px; padding: 40px; text-align: center; color: var(--muted); font-size: 13px; }
</style>
