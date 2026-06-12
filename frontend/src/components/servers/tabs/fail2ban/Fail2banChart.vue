<script setup lang="ts">
import { computed } from 'vue'
import MetricChart from '@/components/charts/MetricChart.vue'
import type { Fail2banEvent } from '@/stores/fail2ban'

const props = defineProps<{ events: Fail2banEvent[] }>()

const series = computed(() => [
  {
    name: 'Bans',
    data: props.events.map(e => ({
      x: new Date(e.hour).getTime(),
      y: e.ban_count,
    })),
  },
])
</script>

<template>
  <section class="card">
    <h3>Bans (last 24h)</h3>
    <div v-if="events.length === 0" class="no-data">No ban events recorded yet</div>
    <MetricChart
      v-else
      type="bar"
      unit="count"
      :series="series"
      :height="200"
      :colors="['#ef4444']"
    />
  </section>
</template>

<style scoped>
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
h3 { font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 12px; }
.no-data { color: var(--muted); font-size: 13px; padding: 24px 0; text-align: center; }
</style>
