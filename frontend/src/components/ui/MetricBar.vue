<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ label: string; value: number | null }>()

// spec 04 §2.3 + spec 5.16.2 colour language
const GREEN = '#22c55e'
const AMBER = '#f59e0b'
const RED = '#ef4444'

const pct = computed(() => (props.value == null ? 0 : Math.max(0, Math.min(100, props.value))))
const hasValue = computed(() => props.value != null)
const color = computed(() => {
  const v = props.value ?? 0
  if (v >= 85) return RED
  if (v >= 70) return AMBER
  return GREEN
})
const warn = computed(() => (props.value ?? 0) > 80)
</script>

<template>
  <div class="metric-bar">
    <span class="mb-label">{{ label }}</span>
    <div
      class="mb-track"
      role="meter"
      :aria-valuenow="hasValue ? Math.round(pct) : undefined"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-label="`${label} usage${hasValue ? ': ' + Math.round(pct) + '%' : ': unavailable'}`"
    >
      <div class="mb-fill" :style="{ width: pct + '%', background: color }"></div>
    </div>
    <span class="mb-value" :class="{ 'mb-value--warn': warn }">
      <template v-if="hasValue">{{ Math.round(pct) }}%</template>
      <template v-else>&mdash;</template>
      <svg
        v-if="warn"
        class="mb-warn-icon"
        viewBox="0 0 16 16"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-label="High usage warning"
        role="img"
      >
        <path
          d="M8 2L14.5 13H1.5L8 2Z"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linejoin="round"
        />
        <path d="M8 6.5V9.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
        <circle cx="8" cy="11.5" r="0.75" fill="currentColor" />
      </svg>
    </span>
  </div>
</template>

<style scoped>
.metric-bar {
  display: grid;
  grid-template-columns: 64px 1fr 52px;
  align-items: center;
  gap: 10px;
}

.mb-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mb-track {
  height: 6px;
  background: var(--surface-2);
  border-radius: 3px;
  overflow: hidden;
  /* Subtle inner shadow for depth on dark surfaces */
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.4);
}

.mb-fill {
  height: 100%;
  border-radius: 3px;
  /* ease-out for enter (growing fill), respects motion preference */
  transition: width 0.3s ease-out, background 0.3s ease-out;
}

@media (prefers-reduced-motion: reduce) {
  .mb-fill {
    transition: none;
  }
}

.mb-value {
  font-size: 12px;
  font-weight: 500;
  color: var(--text);
  text-align: right;
  font-variant-numeric: tabular-nums;
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 3px;
  white-space: nowrap;
}

.mb-warn-icon {
  width: 12px;
  height: 12px;
  color: var(--amber);
  flex-shrink: 0;
  /* Subtle pulse to draw attention without being distracting */
  animation: warn-pulse 2.5s ease-in-out infinite;
}

@media (prefers-reduced-motion: reduce) {
  .mb-warn-icon {
    animation: none;
  }
}

@keyframes warn-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}
</style>
