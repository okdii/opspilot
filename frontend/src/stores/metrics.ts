import { defineStore } from 'pinia'
import { reactive, ref } from 'vue'
import {
  endMaintenance as apiEndMaintenance,
  getLatest,
  getMaintenance,
  getMetrics,
  startMaintenance as apiStartMaintenance,
} from '@/services/api'
import type {
  LatestLabeled,
  LatestScalar,
  LatestValues,
  MaintenanceState,
  MetricRange,
  MetricSeries,
  StartMaintenancePayload,
} from '@/types'

const RANGE_KEY = 'opspilot.metricsRange'
const DEFAULT_RANGE: MetricRange = '1h'

/** Tab name → MetricRange, persisted to localStorage so each tab remembers
 *  its last range across reloads. */
function loadRanges(): Record<string, MetricRange> {
  try {
    const raw = localStorage.getItem(RANGE_KEY)
    if (raw) return JSON.parse(raw) as Record<string, MetricRange>
  } catch {
    /* ignore malformed persisted value */
  }
  return {}
}

// Raw ranges receive live appends; 24h is recomputed in-place; 7d/30d are static.
const RAW_RANGES: ReadonlySet<MetricRange> = new Set<MetricRange>(['1h', '6h'])

// Lookback window (ms) used to trim raw datasets after each live push.
const RANGE_WINDOW_MS: Record<MetricRange, number> = {
  '1h': 60 * 60 * 1000,
  '6h': 6 * 60 * 60 * 1000,
  '24h': 24 * 60 * 60 * 1000,
  '7d': 7 * 24 * 60 * 60 * 1000,
  '30d': 30 * 24 * 60 * 60 * 1000,
}

/** A single chart payload plus the range it was loaded at, so applyLivePush
 *  knows whether to append (raw), recompute the hour bucket (24h), or no-op. */
interface ChartEntry {
  range: MetricRange
  series: MetricSeries[]
  // 24h only: per-series running avg of the current (rightmost) hour bucket,
  // keyed by seriesKey → { bucketStart(ms), sum, count }.
  _buckets?: Record<string, { bucketStartMs: number; sum: number; count: number }>
}

/** A WS metric push row (matches the dashboard store's PushRow shape). */
export interface MetricPushRow {
  metric_name: string
  value: number | null
  labels: Record<string, string>
  time: string
}

function seriesKey(metricName: string, labels: Record<string, string>): string {
  const flat = Object.keys(labels)
    .sort()
    .map((k) => `${k}=${labels[k]}`)
    .join(',')
  return `${metricName}|${flat}`
}

function hourBucketStart(ms: number): number {
  return Math.floor(ms / 3_600_000) * 3_600_000
}

export const useMetricsStore = defineStore('metrics', () => {
  const activeServerId = ref<string | null>(null)
  const selectedRange = ref<Record<string, MetricRange>>(loadRanges())
  // Keyed by a caller-supplied key (e.g. 'overview.cpu', 'cpu.breakdown').
  const chartData = reactive<Record<string, ChartEntry>>({})
  const latestValues = ref<LatestValues>({})
  const maintenance = ref<MaintenanceState>({ active: false })
  const loading = ref(false)

  function setRange(tab: string, range: MetricRange): void {
    selectedRange.value = { ...selectedRange.value, [tab]: range }
    try {
      localStorage.setItem(RANGE_KEY, JSON.stringify(selectedRange.value))
    } catch {
      /* storage unavailable — keep in-memory only */
    }
  }

  function rangeFor(tab: string): MetricRange {
    return selectedRange.value[tab] ?? DEFAULT_RANGE
  }

  /** Set the active server and load its gauge (latest) values + maintenance. */
  async function loadServer(id: string): Promise<void> {
    activeServerId.value = id
    // Clear any prior server's cached charts.
    for (const k of Object.keys(chartData)) delete chartData[k]
    latestValues.value = {}
    loading.value = true
    try {
      const [latest, maint] = await Promise.all([getLatest(id), getMaintenance(id)])
      latestValues.value = latest
      maintenance.value = maint
    } finally {
      loading.value = false
    }
  }

  /** Fetch a metric series set and cache it under `key`. */
  async function loadChartData(metrics: string[], range: MetricRange, key: string): Promise<void> {
    const id = activeServerId.value
    if (!id) return
    const resp = await getMetrics(id, range, metrics)
    const entry: ChartEntry = { range, series: resp.series }
    if (range === '24h') {
      entry._buckets = {}
      for (const s of entry.series) {
        const last = s.data[s.data.length - 1]
        if (last && last.value != null) {
          entry._buckets[seriesKey(s.metric_name, s.labels)] = {
            bucketStartMs: hourBucketStart(Date.parse(last.time)),
            sum: last.value,
            count: 1,
          }
        }
      }
    }
    chartData[key] = entry
  }

  /** Apply a live WS metric batch. Updates gauges always; for charts: raw
   *  ranges append, 24h recomputes the rightmost hour bucket via running avg,
   *  7d/30d no-op. (Design §4.3) */
  function applyLivePush(rows: MetricPushRow[]): void {
    if (!rows.length) return

    // 1) latestValues (gauges) — always update in place.
    const latest = { ...latestValues.value }
    for (const row of rows) {
      if (row.value == null) continue
      const labels = row.labels ?? {}
      const isLabeled = Object.keys(labels).length > 0
      const existing = latest[row.metric_name]
      if (isLabeled && (Array.isArray(existing) || existing === undefined)) {
        const arr: LatestLabeled[] = Array.isArray(existing) ? [...existing] : []
        const idx = arr.findIndex((e) => seriesKey(row.metric_name, e.labels) === seriesKey(row.metric_name, labels))
        const next: LatestLabeled = { value: row.value, labels, time: row.time }
        if (idx >= 0) arr[idx] = next
        else arr.push(next)
        latest[row.metric_name] = arr
      } else if (!isLabeled) {
        latest[row.metric_name] = { value: row.value, time: row.time } as LatestScalar
      }
    }
    latestValues.value = latest

    // 2) chartData — per cached chart, by its load range.
    for (const key of Object.keys(chartData)) {
      const entry = chartData[key]
      if (entry.range !== '24h' && !RAW_RANGES.has(entry.range)) continue // 7d/30d no-op

      for (const row of rows) {
        if (row.value == null) continue
        const k = seriesKey(row.metric_name, row.labels ?? {})
        const s = entry.series.find((ser) => seriesKey(ser.metric_name, ser.labels) === k)
        if (!s) continue

        if (RAW_RANGES.has(entry.range)) {
          // Append a new point.
          s.data.push({ time: row.time, value: row.value })
        } else {
          // 24h — running average of the rightmost hour bucket, replaced in place.
          entry._buckets = entry._buckets ?? {}
          const bStart = hourBucketStart(Date.parse(row.time))
          const acc = entry._buckets[k]
          if (acc && acc.bucketStartMs === bStart) {
            acc.sum += row.value
            acc.count += 1
          } else {
            entry._buckets[k] = { bucketStartMs: bStart, sum: row.value, count: 1 }
          }
          const cur = entry._buckets[k]
          const avg = cur.sum / cur.count
          const bucketIso = new Date(bStart).toISOString()
          const tail = s.data[s.data.length - 1]
          if (tail && hourBucketStart(Date.parse(tail.time)) === bStart) {
            // Replace the rightmost bucket in place.
            s.data[s.data.length - 1] = { time: bucketIso, value: avg }
          } else {
            s.data.push({ time: bucketIso, value: avg })
          }
        }
      }
    }

    // Trim raw datasets to their visible window.
    trimChartData()
  }

  /** Drop points older than each cached chart's range window (raw ranges). */
  function trimChartData(range?: MetricRange): void {
    const now = Date.now()
    for (const key of Object.keys(chartData)) {
      const entry = chartData[key]
      if (range && entry.range !== range) continue
      if (!RAW_RANGES.has(entry.range)) continue
      const cutoff = now - RANGE_WINDOW_MS[entry.range]
      for (const s of entry.series) {
        s.data = s.data.filter((p) => Date.parse(p.time) >= cutoff)
      }
    }
  }

  async function startMaintenance(payload: StartMaintenancePayload = {}): Promise<void> {
    const id = activeServerId.value
    if (!id) return
    await apiStartMaintenance(id, payload)
    maintenance.value = await getMaintenance(id)
  }

  async function endMaintenance(): Promise<void> {
    const id = activeServerId.value
    if (!id) return
    await apiEndMaintenance(id)
    maintenance.value = await getMaintenance(id)
  }

  function reset(): void {
    activeServerId.value = null
    for (const k of Object.keys(chartData)) delete chartData[k]
    latestValues.value = {}
    maintenance.value = { active: false }
    loading.value = false
  }

  return {
    activeServerId,
    selectedRange,
    chartData,
    latestValues,
    maintenance,
    loading,
    setRange,
    rangeFor,
    loadServer,
    loadChartData,
    applyLivePush,
    trimChartData,
    startMaintenance,
    endMaintenance,
    reset,
  }
})
