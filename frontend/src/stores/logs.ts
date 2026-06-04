import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { getLogs, getLogVolume, getLogSummary } from '@/services/api'
import type {
  LogEntry, LogFilters, LogSeverity, LogSource, LogSummary, LogTimeRange, VolumeBucket,
} from '@/types'

export const ALL_SOURCES: LogSource[] = [
  'syslog', 'auth', 'kernel',
  'nginx_access', 'nginx_error',
  'php_fpm', 'php_app',
  'mariadb_error', 'mariadb_slow',
]

export const ALL_SEVERITIES: LogSeverity[] = ['debug', 'info', 'warn', 'error', 'fatal']

const RANGE_OFFSET_MS: Record<Exclude<LogTimeRange, 'custom'>, number> = {
  '15m': 15 * 60_000,
  '1h': 60 * 60_000,
  '6h': 6 * 60 * 60_000,
  '24h': 24 * 60 * 60_000,
  '7d': 7 * 24 * 60 * 60_000,
}

function defaultFilters(): LogFilters {
  return {
    serverIds: [],
    sources: [...ALL_SOURCES],
    severities: [...ALL_SEVERITIES],
    search: '',
    range: '1h',
    from: null,
    to: null,
  }
}

export const useLogStore = defineStore('logs', () => {
  const entries = ref<LogEntry[]>([])
  const nextCursor = ref<string | null>(null)
  const limitReached = ref(false)
  const loading = ref(false)
  const loadingMore = ref(false)
  const error = ref<string | null>(null)
  const liveTailActive = ref(false)
  const newEntryCount = ref(0)
  const filters = ref<LogFilters>(defaultFilters())
  const volumeData = ref<VolumeBucket[]>([])
  const summary = ref<LogSummary | null>(null)

  const orgId = ref<string | null>(null)

  const filtersActive = computed(() => {
    const f = filters.value
    return (
      f.serverIds.length > 0 ||
      f.sources.length !== ALL_SOURCES.length ||
      f.severities.length !== ALL_SEVERITIES.length ||
      f.search.trim().length >= 2 ||
      f.range !== '1h'
    )
  })

  /** Resolve from/to from the active range (or explicit custom values). */
  function resolveRange(): { from: string; to: string } {
    const f = filters.value
    if (f.range === 'custom' && f.from && f.to) {
      return { from: f.from, to: f.to }
    }
    const now = Date.now()
    const offset = RANGE_OFFSET_MS[(f.range === 'custom' ? '1h' : f.range)]
    return { from: new Date(now - offset).toISOString(), to: new Date(now).toISOString() }
  }

  function buildParams(): Record<string, string> {
    const f = filters.value
    const { from, to } = resolveRange()
    const p: Record<string, string> = { from, to }
    if (orgId.value) p.org_id = orgId.value
    if (f.serverIds.length) p.server_ids = f.serverIds.join(',')
    if (f.sources.length && f.sources.length < ALL_SOURCES.length) p.sources = f.sources.join(',')
    if (f.severities.length && f.severities.length < ALL_SEVERITIES.length) {
      p.severities = f.severities.join(',')
    }
    if (f.search.trim().length >= 2) p.search = f.search.trim()
    return p
  }

  function setOrg(id: string | null): void {
    orgId.value = id
  }

  async function fetchLogs(): Promise<void> {
    if (!orgId.value && !filters.value.serverIds.length) return
    loading.value = true
    error.value = null
    newEntryCount.value = 0
    try {
      const params = buildParams()
      params.limit = '100'
      const res = await getLogs(params)
      entries.value = res.entries
      nextCursor.value = res.next_cursor
      limitReached.value = res.limit_reached
    } catch {
      error.value = 'Could not load logs.'
      entries.value = []
      nextCursor.value = null
    } finally {
      loading.value = false
    }
  }

  async function fetchMore(): Promise<void> {
    if (!nextCursor.value || loadingMore.value || limitReached.value) return
    loadingMore.value = true
    try {
      const params = buildParams()
      params.limit = '100'
      params.cursor = nextCursor.value
      const res = await getLogs(params)
      entries.value = [...entries.value, ...res.entries]
      nextCursor.value = res.next_cursor
      limitReached.value = res.limit_reached
    } catch {
      // keep existing entries; surface nothing fatal on a page fetch
    } finally {
      loadingMore.value = false
    }
  }

  async function fetchVolume(): Promise<void> {
    if (!orgId.value && !filters.value.serverIds.length) return
    try {
      const res = await getLogVolume(buildParams())
      volumeData.value = res.buckets
    } catch {
      volumeData.value = []
    }
  }

  async function fetchSummary(): Promise<void> {
    if (!orgId.value && !filters.value.serverIds.length) return
    try {
      const params = buildParams()
      delete params.severities  // summary always covers all severities
      const res = await getLogSummary(params)
      summary.value = res
    } catch {
      summary.value = null
    }
  }

  async function refresh(): Promise<void> {
    await Promise.all([fetchLogs(), fetchVolume(), fetchSummary()])
  }

  /** True when an incoming live entry passes the active filters (spec §8.4). */
  function matchesFilters(e: LogEntry): boolean {
    const f = filters.value
    if (f.serverIds.length && !f.serverIds.includes(e.server_id)) return false
    if (f.sources.length < ALL_SOURCES.length && !f.sources.includes(e.source as LogSource)) {
      return false
    }
    // Severity filter never excludes access logs (they carry no severity).
    if (
      f.severities.length < ALL_SEVERITIES.length &&
      e.severity != null &&
      e.source !== 'nginx_access' &&
      !f.severities.includes(e.severity)
    ) {
      return false
    }
    const q = f.search.trim().toLowerCase()
    if (q.length >= 2 && !e.message.toLowerCase().includes(q)) return false
    return true
  }

  /** Prepend a live WS entry if it passes filters. Returns true if added. */
  function appendLiveEntry(e: LogEntry): boolean {
    if (!liveTailActive.value) return false
    if (!matchesFilters(e)) return false
    if (entries.value.some((x) => x.id === e.id)) return false
    entries.value = [e, ...entries.value]
    newEntryCount.value += 1
    return true
  }

  function setLiveTail(active: boolean): void {
    liveTailActive.value = active
    newEntryCount.value = 0
  }

  function resetNewCount(): void {
    newEntryCount.value = 0
  }

  function setFilter<K extends keyof LogFilters>(key: K, value: LogFilters[K]): void {
    filters.value[key] = value
  }

  function clearFilters(): void {
    filters.value = defaultFilters()
  }

  function reset(): void {
    entries.value = []
    nextCursor.value = null
    limitReached.value = false
    loading.value = false
    loadingMore.value = false
    error.value = null
    liveTailActive.value = false
    newEntryCount.value = 0
    volumeData.value = []
    summary.value = null
    filters.value = defaultFilters()
  }

  return {
    entries, nextCursor, limitReached, loading, loadingMore, error,
    liveTailActive, newEntryCount, filters, volumeData, summary, orgId,
    filtersActive,
    setOrg, fetchLogs, fetchMore, fetchVolume, fetchSummary, refresh,
    matchesFilters, appendLiveEntry, setLiveTail, resetNewCount,
    setFilter, clearFilters, reset, resolveRange,
  }
})
