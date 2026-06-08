<script setup lang="ts">
import { computed } from 'vue'
import type { JobRun } from '@/stores/jobs'

/**
 * 30-day calendar heatmap (spec 09 §7.3).
 * One cell per day; colour = worst outcome that day.
 *   green  = success   ·  red = missed/failed  ·  grey = no data
 * Reuses run rows already loaded for the detail view — no extra fetch.
 */
const props = defineProps<{
  runs: JobRun[]
  /** When true, show byte size in the tooltip (backup jobs). */
  showSize?: boolean
}>()

const DAYS = 30

interface Cell {
  key: string
  date: Date
  state: 'success' | 'bad' | 'empty'
  count: number
  tip: string
  isToday: boolean
}

function dayKey(d: Date): string {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}

function fmtDate(d: Date): string {
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

const cells = computed<Cell[]>(() => {
  // Bucket runs by local day.
  const byDay = new Map<string, JobRun[]>()
  for (const r of props.runs) {
    const d = new Date(r.ran_at)
    const k = dayKey(d)
    const arr = byDay.get(k)
    if (arr) arr.push(r)
    else byDay.set(k, [r])
  }

  const today = new Date()
  const out: Cell[] = []
  for (let i = DAYS - 1; i >= 0; i--) {
    const d = new Date(today)
    d.setDate(today.getDate() - i)
    const k = dayKey(d)
    const runs = byDay.get(k) ?? []

    let state: Cell['state'] = 'empty'
    let tip = `${fmtDate(d)} — no data`
    if (runs.length) {
      // Worst outcome wins: any non-success → bad.
      const anyBad = runs.some((r) => r.outcome !== 'success')
      state = anyBad ? 'bad' : 'success'
      const last = runs[0]
      const parts = [fmtDate(d), `${runs.length} run${runs.length > 1 ? 's' : ''}`, last.outcome]
      if (props.showSize && last.size_formatted) parts.push(last.size_formatted)
      else if (!props.showSize && last.duration_sec != null) parts.push(`${last.duration_sec}s`)
      tip = parts.join(' · ')
    }

    out.push({
      key: k,
      date: d,
      state,
      count: runs.length,
      tip,
      isToday: i === 0,
    })
  }
  return out
})
</script>

<template>
  <div class="heatmap">
    <div
      v-for="c in cells"
      :key="c.key"
      class="hm-cell"
      :class="[`hm-${c.state}`, { 'hm-today': c.isToday }]"
      :title="c.tip"
    ></div>
  </div>
  <div class="hm-legend">
    <span class="hm-swatch hm-success"></span> Success
    <span class="hm-swatch hm-bad"></span> Missed / Failed
    <span class="hm-swatch hm-empty"></span> No data
  </div>
</template>

<style scoped>
.heatmap {
  display: grid;
  grid-template-columns: repeat(15, 1fr);
  gap: 5px;
}
.hm-cell {
  aspect-ratio: 1;
  border-radius: 3px;
  border: 1px solid transparent;
  cursor: default;
}
.hm-success { background: rgba(34, 197, 94, 0.85); }
.hm-bad { background: rgba(239, 68, 68, 0.85); }
.hm-empty { background: var(--surface-2); border-color: var(--border); }
.hm-today { outline: 2px solid var(--accent-2); outline-offset: 1px; }
.hm-legend {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  font-size: 11px;
  color: var(--muted);
  flex-wrap: wrap;
}
.hm-swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  display: inline-block;
}
.hm-swatch.hm-empty { border: 1px solid var(--border); }
.hm-swatch:not(:first-child) { margin-left: 10px; }
</style>
