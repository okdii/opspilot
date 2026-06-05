<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    grade: string | null
    score: number | null
    size?: 'sm' | 'md' | 'lg'
  }>(),
  { size: 'md' }
)

const COLOR_MAP: Record<string, string> = {
  'A+': '#22c55e',
  A:   '#22c55e',
  B:   '#14b8a6',
  C:   '#eab308',
  D:   '#f97316',
  E:   '#ef4444',
  F:   '#ef4444',
}

const color = computed(() => (props.grade ? COLOR_MAP[props.grade] ?? '#6b7280' : '#6b7280'))
const label = computed(() => props.grade ?? '—')
const tooltip = computed(() =>
  props.grade && props.score != null
    ? `Security grade: ${props.grade} (${props.score}/100)`
    : 'Not scanned yet',
)
</script>

<template>
  <span
    class="grade-badge"
    :class="[`grade-${size}`]"
    :style="{ '--grade-color': color }"
    :title="tooltip"
  >{{ label }}</span>
</template>

<style scoped>
.grade-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  border-radius: 6px;
  border: 1.5px solid var(--grade-color);
  color: var(--grade-color);
  background: transparent;
  font-family: ui-monospace, monospace;
  cursor: default;
  user-select: none;
}
.grade-sm { font-size: 11px; padding: 1px 6px; }
.grade-md { font-size: 13px; padding: 3px 9px; }
.grade-lg { font-size: 18px; padding: 6px 14px; min-width: 42px; }
</style>
