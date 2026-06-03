<script setup lang="ts">
import { computed } from 'vue'

/**
 * Expiry progress bar (spec 07 §5.3). The fill represents how much of the
 * "warning window" of life remains: full when days_remaining >= warnThreshold,
 * shrinking toward 0 as expiry nears. Colour is keyed off days_remaining
 * thresholds, not the usage thresholds in the shared MetricBar — hence a
 * dedicated component for the SSL/Domain domain language.
 */
const props = defineProps<{
  daysRemaining: number | null
  warnThreshold: number
  status: string
}>()

const GREEN = '#22c55e'
const AMBER = '#f59e0b'
const RED = '#ef4444'

const unreachable = computed(
  () => props.daysRemaining == null || props.status === 'unreachable',
)
const expired = computed(
  () => props.status === 'expired' || (props.daysRemaining != null && props.daysRemaining <= 0),
)

const pct = computed(() => {
  if (unreachable.value) return 0
  const d = props.daysRemaining ?? 0
  if (d <= 0) return 100 // expired → full red solid bar
  const window = Math.max(props.warnThreshold, 1)
  return Math.max(6, Math.min(100, Math.round((d / window) * 100)))
})

const color = computed(() => {
  if (unreachable.value) return 'var(--surface-2)'
  const d = props.daysRemaining ?? 0
  if (d <= 0) return RED
  if (d <= 7) return RED
  if (d <= 30) return AMBER
  return GREEN
})

const pulsing = computed(() => expired.value)
</script>

<template>
  <div class="expiry-bar" :title="unreachable ? 'Unreachable — no expiry data' : `${daysRemaining} days remaining`">
    <div class="eb-track">
      <div
        class="eb-fill"
        :class="{ 'eb-pulse': pulsing, 'eb-empty': unreachable }"
        :style="{ width: pct + '%', background: color }"
      ></div>
    </div>
  </div>
</template>

<style scoped>
.expiry-bar { width: 100%; }
.eb-track {
  height: 6px;
  background: var(--surface-2);
  border-radius: 3px;
  overflow: hidden;
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.4);
}
.eb-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease-out, background 0.3s ease-out;
}
.eb-empty { opacity: 0; }
.eb-pulse { animation: eb-pulse 1.4s ease-in-out infinite; }
@keyframes eb-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}
@media (prefers-reduced-motion: reduce) {
  .eb-fill { transition: none; }
  .eb-pulse { animation: none; }
}
</style>
