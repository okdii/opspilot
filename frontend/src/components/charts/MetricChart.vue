<script setup lang="ts">
import { computed } from 'vue'
import VueApexCharts from 'vue3-apexcharts'
import type { ApexOptions, ApexAxisChartSeries, ApexNonAxisChartSeries } from 'apexcharts'

/**
 * Single shared ApexCharts wrapper for the whole app (first + only chart use).
 * Every Server Detail tab renders through this component so chart colors,
 * spacing, tooltip, grid and axis formatting come from one source of truth
 * (the dark-dashboard theme tokens in App.vue :root), never hardcoded per tab.
 */

export type MetricChartType = 'area' | 'line' | 'bar' | 'donut' | 'radialBar'
export type MetricUnit = '%' | 'bytes/s' | 'count' | 'ms' | 'GB'

export interface MetricThreshold {
  value: number
  color: string
  label?: string
}

const props = withDefaults(
  defineProps<{
    type: MetricChartType
    series: ApexAxisChartSeries | ApexNonAxisChartSeries
    categories?: (string | number)[]
    unit?: MetricUnit
    thresholds?: MetricThreshold[]
    height?: number
    stacked?: boolean
    /** donut/radialBar slice/series labels */
    labels?: string[]
    /** Optional explicit per-series colors (overrides the brand palette).
     *  Used by callers with fixed semantic colors, e.g. log-severity stacks. */
    colors?: string[]
    /** Render bar chart with horizontal bars (categories on y-axis, values on x-axis). */
    horizontal?: boolean
  }>(),
  {
    height: 300,
    stacked: false,
    horizontal: false,
  },
)

// --- Dark-dashboard theme tokens (mirror of App.vue :root) -----------------
// Kept in lockstep with the CSS custom properties + plugins/vuestic.ts. These
// must be concrete hex (ApexCharts cannot resolve CSS var() at draw time), so
// this component is the single place charts read brand colors from.
const THEME = {
  text: '#e2e8f0',
  muted: '#94a3b8',
  border: '#2e3354',
  surface: '#1a1d27',
  surface2: '#22263a',
  // Categorical palette derived from the brand tokens (accent, green, blue,
  // amber, secondary, red) — used in declaration order for multi-series charts.
  palette: ['#6366f1', '#22c55e', '#3b82f6', '#f59e0b', '#818cf8', '#ef4444'],
} as const

// --- Unit-aware value formatting -------------------------------------------
function formatBytesPerSec(v: number): string {
  if (v == null || Number.isNaN(v)) return '—'
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s', 'TB/s']
  let n = v
  let i = 0
  while (Math.abs(n) >= 1024 && i < units.length - 1) {
    n /= 1024
    i += 1
  }
  const digits = i === 0 ? 0 : n >= 100 ? 0 : n >= 10 ? 1 : 2
  return `${n.toFixed(digits)} ${units[i]}`
}

function formatValue(v: number): string {
  if (v == null || Number.isNaN(v)) return '—'
  switch (props.unit) {
    case '%':
      return `${v >= 10 ? Math.round(v) : v.toFixed(1)}%`
    case 'bytes/s':
      return formatBytesPerSec(v)
    case 'ms':
      return `${v >= 10 ? Math.round(v) : v.toFixed(1)} ms`
    case 'GB':
      return v < 0.1 ? `${(v * 1024).toFixed(0)} MB` : `${v.toFixed(1)} GB`
    case 'count':
    default:
      return Number.isInteger(v) ? String(v) : v.toFixed(2)
  }
}

const isAxisChart = computed(() => props.type === 'area' || props.type === 'line' || props.type === 'bar')

const yMax = computed<number | undefined>(() => (props.unit === '%' ? 100 : undefined))

const annotations = computed<ApexOptions['annotations']>(() => {
  if (!props.thresholds?.length || !isAxisChart.value) return {}
  return {
    yaxis: props.thresholds.map((t) => ({
      y: t.value,
      borderColor: t.color,
      strokeDashArray: 4,
      label: {
        text: t.label ?? formatValue(t.value),
        borderColor: t.color,
        style: { color: '#0f1117', background: t.color, fontSize: '10px' },
      },
    })),
  }
})

const options = computed<ApexOptions>(() => {
  const base: ApexOptions = {
    chart: {
      type: props.type,
      height: props.height,
      stacked: props.stacked,
      background: 'transparent',
      foreColor: THEME.muted,
      toolbar: { show: false },
      zoom: { enabled: false },
      animations: { enabled: true, speed: 300 },
      fontFamily: 'inherit',
    },
    theme: { mode: 'dark' },
    colors: props.colors?.length ? [...props.colors] : [...THEME.palette],
    dataLabels: { enabled: false },
    grid: {
      borderColor: THEME.border,
      strokeDashArray: 3,
      padding: { left: 8, right: 8 },
    },
    stroke: {
      curve: 'smooth',
      width: props.type === 'bar' ? 0 : 2,
    },
    legend: {
      labels: { colors: THEME.muted },
      fontSize: '12px',
      markers: { strokeWidth: 0 },
    },
    tooltip: {
      theme: 'dark',
      y: { formatter: (v: number) => formatValue(v) },
    },
    annotations: annotations.value,
  }

  // Axis charts (area / line / bar) get an x-axis + formatted y-axis.
  if (isAxisChart.value) {
    base.xaxis = {
      type: props.categories ? 'category' : 'datetime',
      // Default to [] — ApexCharts calls xaxis.categories.slice() unconditionally
      // for axis charts, so an undefined value crashes parseDataAxisCharts.
      categories: props.categories ?? [],
      labels: {
        style: { colors: THEME.muted, fontSize: '11px' },
        datetimeUTC: false,
      },
      axisBorder: { color: THEME.border },
      axisTicks: { color: THEME.border },
    }
    base.yaxis = {
      min: 0,
      max: yMax.value,
      labels: {
        style: { colors: THEME.muted, fontSize: '11px' },
        formatter: (v: number) => formatValue(v),
      },
    }
    if (props.type === 'area') {
      base.fill = {
        type: 'gradient',
        gradient: { shadeIntensity: 1, opacityFrom: 0.35, opacityTo: 0.05, stops: [0, 90, 100] },
      }
    }
    if (props.type === 'bar') {
      base.plotOptions = { bar: { borderRadius: 3, columnWidth: '60%', horizontal: props.horizontal } }
      if (props.horizontal) {
        // Swap: categories go on y-axis (left), values go on x-axis (bottom)
        base.xaxis = { ...base.xaxis, labels: { ...base.xaxis?.labels, formatter: (v: string) => formatValue(Number(v)) } }
        base.yaxis = { labels: { style: { colors: THEME.muted, fontSize: '11px' } } }
      }
    }
  }

  // Radial gauge (single % value) styling.
  if (props.type === 'radialBar') {
    base.plotOptions = {
      radialBar: {
        hollow: { size: '62%' },
        track: { background: THEME.surface2 },
        dataLabels: {
          name: { color: THEME.muted, fontSize: '12px' },
          value: {
            color: THEME.text,
            fontSize: '22px',
            fontWeight: 600,
            formatter: (v: number) => `${Math.round(v)}%`,
          },
        },
      },
    }
    base.labels = props.labels
  }

  if (props.type === 'donut') {
    base.labels = props.labels
    base.plotOptions = {
      pie: {
        donut: {
          size: '68%',
          labels: {
            show: true,
            value: { color: THEME.text, formatter: (v: string) => formatValue(Number(v)) },
            total: { show: true, color: THEME.muted },
          },
        },
      },
    }
    base.legend = { ...base.legend, position: 'bottom' }
  }

  return base
})
</script>

<template>
  <VueApexCharts
    :type="props.type"
    :height="props.height"
    :options="options"
    :series="props.series"
  />
</template>
