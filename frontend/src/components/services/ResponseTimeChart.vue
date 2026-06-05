<script setup lang="ts">
import { use, graphic } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  MarkAreaComponent,
  LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import { ref, computed, watch } from 'vue'
import type { ResponseRange, ResponseTimeData } from '@/stores/services'

use([
  LineChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  MarkAreaComponent,
  LegendComponent,
  CanvasRenderer,
])

const props = defineProps<{
  data: ResponseTimeData | null
  range: ResponseRange
  downPeriods: Array<{ start: number; end: number }>
  loading?: boolean
  title?: string
}>()

const emit = defineEmits<{
  'range-change': [r: ResponseRange]
}>()

const RANGES: ResponseRange[] = ['1h', '6h', '24h', '7d', '30d']
const TWO_HOURS = 2 * 3600_000

type Point = [number, number | null, number | null]

const rawPoints = computed<Point[]>(() =>
  (props.data?.data ?? []).map((p): Point => [
    new Date(p.time).getTime(),
    p.avg_ms,
    p.p95_ms,
  ])
)

const displayPoints = ref<Point[]>([])

const zoomStart = ref<number | null>(null)
const zoomEnd = ref<number | null>(null)
// true after user explicitly clicks a range button — show full range instead of last-2h default
const showFullRange = ref(false)

const effectiveZoomStart = computed(() => {
  if (zoomStart.value !== null) return zoomStart.value
  const pts = rawPoints.value
  if (!pts.length) return Date.now() - TWO_HOURS
  return showFullRange.value ? pts[0][0] : pts[pts.length - 1][0] - TWO_HOURS
})
const effectiveZoomEnd = computed(() => {
  if (zoomEnd.value !== null) return zoomEnd.value
  const pts = rawPoints.value
  return pts.length ? pts[pts.length - 1][0] : Date.now()
})

function aggregate(pts: Point[], bucketMs: number): Point[] {
  const buckets = new Map<number, { sumAvg: number; sumP95: number; count: number; countP95: number }>()
  for (const [t, avg, p95] of pts) {
    const key = Math.floor(t / bucketMs) * bucketMs
    if (!buckets.has(key)) buckets.set(key, { sumAvg: 0, sumP95: 0, count: 0, countP95: 0 })
    const b = buckets.get(key)!
    if (avg != null) { b.sumAvg += avg; b.count++ }
    if (p95 != null) { b.sumP95 += p95; b.countP95++ }
  }
  return [...buckets.entries()]
    .sort(([a], [b]) => a - b)
    .map(([t, b]): Point => [
      t,
      b.count ? parseFloat((b.sumAvg / b.count).toFixed(2)) : null,
      b.countP95 ? parseFloat((b.sumP95 / b.countP95).toFixed(2)) : null,
    ])
}

function applyAggregation(spanMs: number) {
  if (props.range === '7d' || props.range === '30d') {
    displayPoints.value = [...rawPoints.value]
    return
  }
  const bucketMs =
    spanMs > 6 * 3600_000 ? 30 * 60_000
    : spanMs > 1 * 3600_000 ? 5 * 60_000
    : 60_000
  displayPoints.value = aggregate(rawPoints.value, bucketMs)
}

watch(() => props.range, () => {
  zoomStart.value = null
  zoomEnd.value = null
  showFullRange.value = true
})

watch(rawPoints, (pts) => {
  if (!pts.length) { displayPoints.value = []; return }
  // On initial load (page open): aggregate for 2h default view.
  // After explicit range click: aggregate for full loaded span.
  const span = showFullRange.value && pts.length > 1
    ? pts[pts.length - 1][0] - pts[0][0]
    : TWO_HOURS
  applyAggregation(Math.max(span, TWO_HOURS))
}, { immediate: true })

const chartRef = ref()

function onDataZoom() {
  try {
    const opt = chartRef.value?.getOption()
    const dz = opt?.dataZoom?.[0]
    if (!dz) return
    zoomStart.value = dz.startValue as number
    zoomEnd.value = dz.endValue as number
    const spanMs = (dz.endValue as number) - (dz.startValue as number)
    if (spanMs > 0) applyAggregation(spanMs)
  } catch { /* chart not ready */ }
}

function formatMs(v: number | null): string {
  if (v == null) return '—'
  if (v === 0) return '0 ms'
  if (v < 1) return `${v.toFixed(2)} ms`
  if (v < 10) return `${v.toFixed(1)} ms`
  return `${Math.round(v)} ms`
}

// Inject null breakpoints at down-period boundaries so ECharts shows gaps
// instead of connecting through outages with a straight line.
const displayPointsWithBreaks = computed<Point[]>(() => {
  const pts: Point[] = [...displayPoints.value]
  for (const period of props.downPeriods) {
    pts.push([period.start, null, null])
    pts.push([period.end, null, null])
  }
  return pts.sort(([a], [b]) => a - b)
})

const avgData = computed(() =>
  displayPointsWithBreaks.value.map(([t, avg]): [number, number | string] => [t, avg ?? '-'])
)
const spreadData = computed(() =>
  displayPointsWithBreaks.value.map(([t, avg, p95]): [number, number | string] => {
    if (avg == null || p95 == null) return [t, '-']
    return [t, Math.max(0, p95 - avg)]
  })
)
const p95Data = computed(() =>
  displayPointsWithBreaks.value.map(([t, , p95]): [number, number | string] => [t, p95 ?? '-'])
)

const hasData = computed(() => displayPoints.value.some(([, avg]) => avg != null))

const option = computed(() => ({
  backgroundColor: 'transparent',
  grid: { top: 16, right: 16, bottom: 32, left: 60, containLabel: false },
  xAxis: {
    type: 'time',
    axisLine: { lineStyle: { color: '#2e3354' } },
    axisTick: { lineStyle: { color: '#2e3354' } },
    axisLabel: {
      color: '#64748b',
      fontSize: 11,
      hideOverlap: true,
      formatter: {
        year: '{yyyy}',
        month: '{MMM} {d}',
        day: '{d} {MMM}',
        hour: '{HH}:{mm}',
        minute: '{HH}:{mm}',
      },
    },
    splitLine: { lineStyle: { color: '#2e3354', type: 'dashed' } },
  },
  yAxis: {
    type: 'value',
    min: 0,
    minInterval: 0.1,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: '#64748b',
      fontSize: 11,
      formatter: (v: number) => {
        if (v === 0) return '0'
        if (v < 1) return v.toFixed(2)
        if (v < 10) return v.toFixed(1)
        return String(Math.round(v))
      },
    },
    name: 'ms',
    nameLocation: 'end' as const,
    nameTextStyle: { color: '#64748b', fontSize: 10 },
    splitLine: { lineStyle: { color: '#2e3354', type: 'dashed' } },
  },
  tooltip: {
    trigger: 'axis',
    backgroundColor: '#1e2235',
    borderColor: '#2e3354',
    borderWidth: 1,
    textStyle: { color: '#e2e8f0', fontSize: 12 },
    axisPointer: { type: 'cross', crossStyle: { color: '#475569', width: 1 } },
    formatter: (params: any[]) => {
      const visible = params.filter((p: any) => !p.seriesName.startsWith('_'))
      if (!visible.length) return ''
      const t = new Date(visible[0].value[0])
      const hh = String(t.getHours()).padStart(2, '0')
      const mm = String(t.getMinutes()).padStart(2, '0')
      const rows = visible.map((p: any) => {
        const raw = p.value[1]
        const val = raw === '-' ? null : (raw as number)
        return `<div style="margin-top:3px">${p.marker} ${p.seriesName}: <strong>${formatMs(val)}</strong></div>`
      })
      return `<div style="color:#94a3b8;font-size:11px;margin-bottom:2px">${hh}:${mm}</div>${rows.join('')}`
    },
  },
  dataZoom: [
    {
      type: 'inside',
      startValue: effectiveZoomStart.value,
      endValue: effectiveZoomEnd.value,
      minValueSpan: 15 * 60_000,
    },
  ],
  legend: {
    data: ['Avg', 'P95'],
    bottom: 0,
    textStyle: { color: '#94a3b8', fontSize: 12 },
    itemHeight: 8,
  },
  series: [
    {
      name: '_baseline',
      type: 'line',
      data: avgData.value,
      stack: 'band',
      lineStyle: { opacity: 0 },
      areaStyle: { opacity: 0 },
      symbol: 'none',
      silent: true,
      legendHoverLink: false,
    },
    {
      name: '_spread',
      type: 'line',
      data: spreadData.value,
      stack: 'band',
      lineStyle: { opacity: 0 },
      areaStyle: {
        color: new graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(99,102,241,0.30)' },
          { offset: 1, color: 'rgba(99,102,241,0.06)' },
        ]),
      },
      symbol: 'none',
      silent: true,
      legendHoverLink: false,
    },
    {
      name: 'Avg',
      type: 'line',
      data: avgData.value,
      smooth: true,
      lineStyle: { color: '#22c55e', width: 2 },
      itemStyle: { color: '#22c55e' },
      symbol: 'none',
      markArea: {
        silent: true,
        itemStyle: { color: 'rgba(239,68,68,0.10)' },
        label: { show: true, color: '#ef4444', fontSize: 10, formatter: () => 'Down' },
        data: props.downPeriods.map((p) => [{ xAxis: p.start }, { xAxis: p.end }]),
      },
    },
    {
      name: 'P95',
      type: 'line',
      data: p95Data.value,
      smooth: true,
      lineStyle: { color: '#6366f1', width: 1, type: 'dashed' },
      itemStyle: { color: '#6366f1' },
      symbol: 'none',
    },
  ],
}))
</script>

<template>
  <div class="resp-chart">
    <div class="resp-chart__header">
      <span v-if="title" class="resp-chart__title">{{ title }}</span>
      <div class="ranges">
        <button
          v-for="r in RANGES"
          :key="r"
          class="range"
          :class="{ active: range === r }"
          @click="emit('range-change', r)"
        >{{ r }}</button>
      </div>
    </div>
    <div v-if="loading" class="placeholder">Loading…</div>
    <VChart
      v-else-if="hasData"
      ref="chartRef"
      class="chart"
      :option="option"
      :autoresize="true"
      :update-options="{ notMerge: false }"
      @datazoom="onDataZoom"
    />
    <p v-else class="placeholder">No response time data for this period.</p>
  </div>
</template>

<style scoped>
.resp-chart { display: flex; flex-direction: column; gap: 8px; }
.resp-chart__header { display: flex; justify-content: space-between; align-items: center; }
.resp-chart__title { font-size: 14px; font-weight: 600; color: var(--text); }
.ranges { display: flex; gap: 4px; }
.range {
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--muted);
  font-size: 12px;
  padding: 5px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.range:hover { border-color: var(--accent); color: var(--accent-2); }
.range.active { background: rgba(99,102,241,0.15); color: var(--accent-2); border-color: var(--accent); }
.chart { height: 280px; }
.placeholder { color: var(--muted); font-size: 13px; text-align: center; padding: 40px 0; margin: 0; }
</style>
