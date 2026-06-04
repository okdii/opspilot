<script setup lang="ts">
import { computed } from 'vue'
import VueApexCharts from 'vue3-apexcharts'
import type { ApexOptions } from 'apexcharts'
import type { TimelineDot } from '@/stores/sslDomains'

/**
 * Expiry timeline (spec 07 §4) — ApexCharts scatter. X-axis = calendar date
 * from today to +365d; each item is a dot at its expiry date, coloured by
 * status. Theme tokens mirror MetricChart.vue (the single chart source of
 * truth) since ApexCharts cannot resolve CSS var() at draw time.
 */
const props = defineProps<{ dots: TimelineDot[] }>()
const emit = defineEmits<{ (e: 'dot-click', id: string): void }>()

const THEME = {
  muted: '#94a3b8',
  border: '#2e3354',
  green: '#22c55e',
  amber: '#f59e0b',
  red: '#ef4444',
  grey: '#6b7280',
}

const DAY = 86_400_000

function colorFor(status: string): string {
  if (status === 'critical' || status === 'expired') return THEME.red
  if (status === 'expiring_soon') return THEME.amber
  if (status === 'unreachable') return THEME.grey
  return THEME.green
}

const today = computed(() => {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d.getTime()
})
const maxDate = computed(() => today.value + 365 * DAY)

// One scatter series so a single dataset carries per-point colours + meta.
const series = computed(() => {
  const data = props.dots
    .map((dot) => {
      let x = new Date(dot.expiryDate).getTime()
      if (Number.isNaN(x)) return null
      if (x > maxDate.value) return null // beyond +365d not plotted
      if (x < today.value) x = today.value // expired pinned at "Today"
      return { x, y: 1, meta: dot }
    })
    .filter((p): p is { x: number; y: number; meta: TimelineDot } => p !== null)
  return [{ name: 'Expiry', data }]
})

const pointColors = computed(() =>
  (series.value[0].data as { meta: TimelineDot }[]).map((p) => colorFor(p.meta.status)),
)

const options = computed<ApexOptions>(() => ({
  chart: {
    type: 'scatter',
    height: 160,
    background: 'transparent',
    foreColor: THEME.muted,
    toolbar: { show: false },
    zoom: { enabled: false },
    fontFamily: 'inherit',
    events: {
      dataPointSelection: (_e: unknown, _ctx: unknown, cfg?: { dataPointIndex: number }) => {
        if (!cfg) return
        const p = series.value[0].data[cfg.dataPointIndex] as { meta: TimelineDot } | undefined
        if (p?.meta) emit('dot-click', p.meta.id)
      },
    },
  },
  theme: { mode: 'dark' },
  colors: pointColors.value,
  markers: { size: 9, strokeWidth: 0, hover: { sizeOffset: 3 } },
  grid: { borderColor: THEME.border, strokeDashArray: 3, padding: { left: 10, right: 10 } },
  xaxis: {
    type: 'datetime',
    min: today.value,
    max: maxDate.value,
    tickAmount: 6,
    labels: { style: { colors: THEME.muted, fontSize: '11px' }, datetimeUTC: false, format: 'dd MMM' },
    axisBorder: { color: THEME.border },
    axisTicks: { color: THEME.border },
  },
  yaxis: { show: false, min: 0, max: 2 },
  annotations: {
    xaxis: [
      {
        x: today.value,
        borderColor: THEME.muted,
        strokeDashArray: 4,
        label: {
          text: 'Today',
          borderColor: THEME.muted,
          style: { color: '#0f1117', background: THEME.muted, fontSize: '10px' },
        },
      },
    ],
  },
  tooltip: {
    custom: ({ dataPointIndex }) => {
      const p = series.value[0].data[dataPointIndex] as { meta: TimelineDot } | undefined
      if (!p) return ''
      const m = p.meta
      const kind = m.type === 'ssl' ? 'SSL Certificate' : m.type === 'service' ? 'Service SSL' : 'Domain Registration'
      const exp = m.expiryDate?.slice(0, 10) ?? '—'
      const days = m.daysRemaining == null ? '—' : `${m.daysRemaining}`
      const issuerLine = m.type === 'ssl' || m.type === 'service'
        ? `<div class="tl-row">Issuer: ${escapeHtml(m.issuer ?? '—')}</div>`
        : `<div class="tl-row">Registrar: ${escapeHtml(m.registrar ?? '—')}</div>`
      return (
        `<div class="tl-tip">` +
        `<div class="tl-title">${escapeHtml(m.label)} — ${kind}</div>` +
        `<div class="tl-row">Expires: ${exp}</div>` +
        `<div class="tl-row">Days remaining: ${days}</div>` +
        issuerLine +
        `<div class="tl-row">Status: ${escapeHtml(m.status)}</div>` +
        `</div>`
      )
    },
  },
}))

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  )
}
</script>

<template>
  <div class="timeline">
    <VueApexCharts type="scatter" :height="160" :options="options" :series="series" />
  </div>
</template>

<style scoped>
.timeline { width: 100%; }
:deep(.tl-tip) {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 11px;
  color: var(--text);
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.5);
}
:deep(.tl-title) { font-weight: 600; color: #fff; margin-bottom: 4px; }
:deep(.tl-row) { color: var(--muted); line-height: 1.5; }
</style>
