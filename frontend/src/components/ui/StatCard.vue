<script setup lang="ts">
defineProps<{
  label: string
  value: string | number
  icon?: string
  delta?: { value: string; direction: 'up' | 'down' | 'flat' }
  accent?: 'primary' | 'success' | 'danger' | 'warning' | 'info'
}>()
</script>

<template>
  <div class="stat-card">
    <div class="sc-top">
      <span class="sc-label">{{ label }}</span>
      <span v-if="icon" class="sc-icon" :class="accent ? `ac-${accent}` : ''" v-html="icon"></span>
    </div>
    <div class="sc-value">{{ value }}</div>
    <div v-if="delta" class="sc-delta" :class="`d-${delta.direction}`">
      <span class="d-arrow">{{ delta.direction === 'up' ? '↑' : delta.direction === 'down' ? '↓' : '→' }}</span>
      {{ delta.value }}
    </div>
  </div>
</template>

<style scoped>
.stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px; min-width: 200px; }
.sc-top { display: flex; justify-content: space-between; align-items: center; }
.sc-label { font-size: 12px; color: var(--muted); }
.sc-icon { color: var(--muted); display: flex; }
.sc-icon.ac-primary { color: var(--accent-2); }
.sc-icon.ac-success { color: var(--green); }
.sc-icon.ac-danger { color: var(--red); }
.sc-icon.ac-warning { color: var(--amber); }
.sc-icon.ac-info { color: var(--blue); }
.sc-value { font-size: 26px; font-weight: 700; color: #fff; margin-top: 8px; font-variant-numeric: tabular-nums; }
.sc-delta { font-size: 12px; margin-top: 6px; display: inline-flex; align-items: center; gap: 4px; }
.d-up { color: var(--green); }
.d-down { color: var(--red); }
.d-flat { color: var(--muted); }
</style>
