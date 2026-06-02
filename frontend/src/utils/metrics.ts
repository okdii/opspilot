/** Shared helpers for reading the metrics store's latest-value map and
 *  formatting metric values. Used by the gauges and every server-detail tab,
 *  so accessor logic lives in one place (CLAUDE.md Rule 3). */
import type { LatestLabeled, LatestScalar, LatestValues, MetricSeries } from '@/types'

/** Convert metrics-store series into ApexCharts datetime series
 *  (`[{ name, data: [[ms, value], …] }]`). `name` derives a legend label per
 *  series; `filter` optionally selects which series to include. Shape is
 *  assignable to ApexAxisChartSeries without coupling this util to apex types. */
export function toApexSeries(
  series: MetricSeries[],
  opts?: { name?: (s: MetricSeries) => string; filter?: (s: MetricSeries) => boolean },
): { name: string; data: [number, number | null][] }[] {
  const name = opts?.name ?? ((s: MetricSeries) => s.metric_name)
  return series
    .filter((s) => (opts?.filter ? opts.filter(s) : true))
    .map((s) => ({
      name: name(s),
      data: s.data.map((p) => [Date.parse(p.time), p.value] as [number, number | null]),
    }))
}

/** A scalar latest value (no per-label split). Returns null if absent or labeled. */
export function scalarValue(latest: LatestValues, name: string): number | null {
  const v = latest[name]
  if (v && !Array.isArray(v)) return (v as LatestScalar).value
  return null
}

/** All per-label latest readings for a metric (disk per path, net per iface). */
export function labeledList(latest: LatestValues, name: string): LatestLabeled[] {
  const v = latest[name]
  return Array.isArray(v) ? v : []
}

/** The labeled reading whose label[key] === val (e.g. cpu=cpu-total). */
export function pickLabel(
  latest: LatestValues,
  name: string,
  key: string,
  val: string,
): number | null {
  const hit = labeledList(latest, name).find((e) => e.labels[key] === val)
  return hit ? hit.value : null
}

/** Highest value across all labels for a metric (e.g. max disk usage %). */
export function maxLabeled(latest: LatestValues, name: string): number | null {
  const vals = labeledList(latest, name)
    .map((e) => e.value)
    .filter((v): v is number => v != null)
  return vals.length ? Math.max(...vals) : null
}

/** CPU total: cpu.usage_active is labeled by `cpu`; pick the cpu-total entry. */
export function cpuTotal(latest: LatestValues, name = 'cpu.usage_active'): number | null {
  return pickLabel(latest, name, 'cpu', 'cpu-total')
}

/** Format bytes/second into human units (B/s, KB/s, MB/s, GB/s). */
export function humanRate(bytesPerSec: number | null): string {
  if (bytesPerSec == null) return '—'
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s', 'TB/s']
  let v = Math.max(0, bytesPerSec)
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`
}

/** Format a count of bytes into human units (B, KB, MB, GB). */
export function humanBytes(bytes: number | null): string {
  if (bytes == null) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = Math.max(0, bytes)
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`
}

/** Seconds → "X days Y hours" (or "Y hours Z min" when < 1 day). */
export function formatUptime(seconds: number | null): string {
  if (seconds == null) return '—'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d} day${d === 1 ? '' : 's'} ${h} hr${h === 1 ? '' : 's'}`
  if (h > 0) return `${h} hr${h === 1 ? '' : 's'} ${m} min`
  return `${m} min`
}

/** Relative "X min ago" style timestamp. */
export function relativeTime(iso: string | null): string {
  if (!iso) return 'never'
  const diff = Date.now() - Date.parse(iso)
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} hr ago`
  return `${Math.floor(h / 24)} d ago`
}

/** Pseudo/virtual filesystem types excluded from disk views (mirrors the
 *  backend REAL_FS_DENYLIST so /metrics/latest disk entries match /metrics). */
const PSEUDO_FS = new Set([
  'tmpfs', 'devtmpfs', 'efivarfs', 'squashfs', 'overlay', 'proc', 'sysfs',
  'cgroup', 'cgroup2', 'devpts', 'mqueue', 'debugfs', 'tracefs', 'ramfs',
  'fusectl', 'configfs', 'pstore', 'bpf', 'autofs', 'binfmt_misc', 'hugetlbfs',
])

/** Keep only real-filesystem mounts from a labeled disk reading list. */
export function realMounts(list: LatestLabeled[]): LatestLabeled[] {
  return list.filter((e) => !PSEUDO_FS.has(e.labels.fstype ?? ''))
}

/** Threshold color for a 0–100 % usage value (green/amber/red). */
export function usageColor(pct: number | null): string {
  if (pct == null) return 'var(--muted)'
  if (pct >= 85) return 'var(--red)'
  if (pct >= 70) return 'var(--amber, #f59e0b)'
  return 'var(--green, #22c55e)'
}
