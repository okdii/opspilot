import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/services/api'
import type { MetricRange } from '@/types'

// ---------------------------------------------------------------------------
// Co-located types + API calls for Database Monitoring (Phase 6, spec 08).
// Per the task constraint these live in the store, NOT in services/api.ts —
// only the shared axios `api` instance is imported.
// ---------------------------------------------------------------------------

/** One row from GET /api/organizations/:org_id/db-credentials.
 *  Fields beyond has_credentials are only present when has_credentials = true. */
export interface DbCredentialStatus {
  server_id: string
  server_name: string
  has_credentials: boolean
  host?: string
  port?: number
  username?: string
  is_replica?: boolean
  /** null = no successful check yet (e.g. re-deploy just queued). */
  last_check_ok?: boolean | null
  last_checked?: string | null
}

/** Latest DB metric snapshot (GET …/db-metrics/latest). All numbers are null
 *  when no data has been collected (the test VM has no MySQL/MariaDB). */
export interface DbMetricsLatest {
  connections_active: number | null
  connections_max: number | null
  queries_per_sec: number | null
  slow_queries_per_min: number | null
  innodb_buffer_pool_hit_rate: number | null
  innodb_deadlocks: number | null
  replication_lag_sec: number | null
  replication_running: boolean | null
  table_locks_waited: number | null
  aborted_connections: number | null
  mariadb_version: string | null
  last_collected_at: string | null
}

export interface DbSeriesPoint {
  time: string
  value: number | null
}

/** Time-series response (GET …/db-metrics?metric=&range=). */
export interface DbSeriesResponse {
  metric: string
  range: string
  resolution?: string
  data: DbSeriesPoint[]
  /** Only present for metric = 'connections_active' (ceiling line). */
  connections_max?: number | null
}

/** Create/update payload. `password` optional on PATCH (blank = keep existing). */
export interface DbCredentialPayload {
  host: string
  port: number
  username: string
  password?: string
  is_replica: boolean
}

export type DbMetricName =
  | 'connections_active'
  | 'queries_per_sec'
  | 'slow_queries_per_min'
  | 'innodb_buffer_pool_hit_rate'
  | 'innodb_deadlocks'
  | 'replication_lag_sec'
  | 'table_locks_waited'
  | 'aborted_connections'

const EMPTY_LATEST: DbMetricsLatest = {
  connections_active: null,
  connections_max: null,
  queries_per_sec: null,
  slow_queries_per_min: null,
  innodb_buffer_pool_hit_rate: null,
  innodb_deadlocks: null,
  replication_lag_sec: null,
  replication_running: null,
  table_locks_waited: null,
  aborted_connections: null,
  mariadb_version: null,
  last_collected_at: null,
}

export const useDatabaseStore = defineStore('databases', () => {
  // server_id → credential status (null while not yet loaded for that server)
  const credentials = ref<DbCredentialStatus[]>([])
  // server_id → latest snapshot
  const latest = ref<Record<string, DbMetricsLatest>>({})
  const loadingCredentials = ref(false)
  const loadingLatest = ref(false)
  const error = ref<string | null>(null)

  // --- Getters (function-style for arg passing) ----------------------------
  function statusFor(serverId: string): DbCredentialStatus | null {
    return credentials.value.find((c) => c.server_id === serverId) ?? null
  }

  function hasCredentials(serverId: string): boolean {
    return statusFor(serverId)?.has_credentials ?? false
  }

  function latestFor(serverId: string): DbMetricsLatest {
    return latest.value[serverId] ?? EMPTY_LATEST
  }

  function connectionPct(serverId: string): number {
    const l = latestFor(serverId)
    if (!l.connections_active || !l.connections_max) return 0
    return Math.round((l.connections_active / l.connections_max) * 100)
  }

  function isReplicationEnabled(serverId: string): boolean {
    return statusFor(serverId)?.is_replica ?? false
  }

  // --- Actions -------------------------------------------------------------
  async function fetchCredentials(orgId: string): Promise<void> {
    loadingCredentials.value = true
    error.value = null
    try {
      const { data } = await api.get<DbCredentialStatus[]>(
        `/api/organizations/${orgId}/db-credentials`,
      )
      credentials.value = data
    } catch {
      error.value = 'Could not load database credential status.'
    } finally {
      loadingCredentials.value = false
    }
  }

  async function saveCredentials(
    serverId: string,
    payload: DbCredentialPayload,
    edit: boolean,
  ): Promise<void> {
    const url = `/api/servers/${serverId}/db-credentials`
    if (edit) await api.patch(url, payload)
    else await api.post(url, payload)
    // Reflect optimistically; the badge will show "deploying" until re-check.
    const existing = statusFor(serverId)
    if (existing) {
      existing.has_credentials = true
      existing.host = payload.host
      existing.port = payload.port
      existing.username = payload.username
      existing.is_replica = payload.is_replica
      existing.last_check_ok = null
      existing.last_checked = null
    }
  }

  async function deleteCredentials(serverId: string): Promise<void> {
    await api.delete(`/api/servers/${serverId}/db-credentials`)
    const existing = statusFor(serverId)
    if (existing) {
      existing.has_credentials = false
      existing.last_check_ok = undefined
      existing.last_checked = undefined
    }
    delete latest.value[serverId]
  }

  async function fetchLatest(serverId: string): Promise<void> {
    loadingLatest.value = true
    try {
      const { data } = await api.get<DbMetricsLatest>(
        `/api/servers/${serverId}/db-metrics/latest`,
      )
      latest.value = { ...latest.value, [serverId]: data }
    } catch {
      latest.value = { ...latest.value, [serverId]: { ...EMPTY_LATEST } }
    } finally {
      loadingLatest.value = false
    }
  }

  async function fetchSeries(
    serverId: string,
    metric: DbMetricName,
    range: MetricRange,
  ): Promise<DbSeriesResponse> {
    const { data } = await api.get<DbSeriesResponse>(
      `/api/servers/${serverId}/db-metrics`,
      { params: { metric, range } },
    )
    return data
  }

  function reset(): void {
    credentials.value = []
    latest.value = {}
    loadingCredentials.value = false
    loadingLatest.value = false
    error.value = null
  }

  return {
    credentials,
    latest,
    loadingCredentials,
    loadingLatest,
    error,
    statusFor,
    hasCredentials,
    latestFor,
    connectionPct,
    isReplicationEnabled,
    fetchCredentials,
    saveCredentials,
    deleteCredentials,
    fetchLatest,
    fetchSeries,
    reset,
  }
})
