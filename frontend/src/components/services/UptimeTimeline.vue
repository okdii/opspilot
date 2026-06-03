<script setup lang="ts">
import { computed } from 'vue'
import type { UptimePoint } from '@/stores/services'

const props = withDefaults(
  defineProps<{ points: UptimePoint[]; days?: number }>(),
  { days: 90 },
)

interface Seg {
  date: string
  pct: number | null
  down: number
  tone: 'up' | 'partial' | 'down' | 'none'
}

// Build a dense day strip so gaps render as grey "no data" segments.
const segments = computed<Seg[]>(() => {
  const byDate = new Map(props.points.map((p) => [p.date, p]))
  const out: Seg[] = []
  const today = new Date()
  for (let i = props.days - 1; i >= 0; i--) {
    const d = new Date(today)
    d.setDate(d.getDate() - i)
    const key = d.toISOString().slice(0, 10)
    const p = byDate.get(key)
    if (!p) {
      out.push({ date: key, pct: null, down: 0, tone: 'none' })
      continue
    }
    const tone: Seg['tone'] = p.uptime_pct >= 99.9 ? 'up' : p.uptime_pct >= 95 ? 'partial' : 'down'
    out.push({ date: key, pct: p.uptime_pct, down: p.down_minutes, tone })
  }
  return out
})

const firstDate = computed(() => segments.value[0]?.date ?? '')

function tip(s: Seg): string {
  if (s.pct == null) return `${s.date} · no data`
  return `${s.date} · ${s.pct}% uptime${s.down ? ` · ${s.down}m down` : ''}`
}
</script>

<template>
  <div class="timeline">
    <div class="bar">
      <span
        v-for="s in segments"
        :key="s.date"
        class="seg"
        :class="`t-${s.tone}`"
        :title="tip(s)"
      ></span>
    </div>
    <div class="axis">
      <span>{{ firstDate }}</span>
      <span>Today</span>
    </div>
  </div>
</template>

<style scoped>
.timeline { width: 100%; }
.bar { display: flex; gap: 1px; height: 32px; align-items: stretch; }
.seg { flex: 1 1 0; min-width: 0; border-radius: 1px; transition: opacity 0.1s; }
.seg:hover { opacity: 0.7; }
.t-up { background: var(--green); }
.t-partial { background: var(--amber); }
.t-down { background: var(--red); }
.t-none { background: var(--surface-2); }
.axis { display: flex; justify-content: space-between; margin-top: 6px; font-size: 10px; color: var(--muted); font-variant-numeric: tabular-nums; }
</style>
