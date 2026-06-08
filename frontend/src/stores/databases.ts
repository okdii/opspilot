import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/services/api'
import type { MetricRange } from '@/types'

// ---------------------------------------------------------------------------
// Co-located types + API calls for Database Monitoring (Phase 6, spec 08).
// Per the task constraint these live in the store, NOT in services/api.ts —
// only the shared axios `api` instance is imported.
// ---------------------------------------------------------------------------

export type DbType = 'mysql' | 'postgres'

export interface DbInstanceStatus {
  credential_id: string
  label: string
  host: string
  port: number
  username?: string
  is_replica?: boolean
  db_type: DbType
  last_check_ok: boolean | null
  last_checked: string | null
}

export interface DbServerStatus {
  server_id: string
  server_name: string
  instances: DbInstanceStatus[]
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
  // PostgreSQL-specific (null for MySQL servers)
  deadlocks: number | null
  transactions_per_sec: number | null
  cache_hit_rate: number | null
  tuple_ops_per_sec: number | null
  temp_files_per_min: number | null
  checkpoints_per_min: number | null
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
  db_type: DbType
  label?: string
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

export type DbPgMetricName =
  | 'connections_active'
  | 'transactions_per_sec'
  | 'cache_hit_rate'
  | 'deadlocks'
  | 'tuple_ops_per_sec'
  | 'temp_files_per_min'
  | 'checkpoints_per_min'
  | 'replication_lag_sec'

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
  deadlocks: null,
  transactions_per_sec: null,
  cache_hit_rate: null,
  tuple_ops_per_sec: null,
  temp_files_per_min: null,
  checkpoints_per_min: null,
  mariadb_version: null,
  last_collected_at: null,
}

export const useDatabaseStore = defineStore('databases', () => {
  const servers = ref<DbServerStatus[]>([])
  const latest = ref<Record<string, DbMetricsLatest>>({})
  const loadingCredentials = ref(false)
  const loadingLatest = ref(false)
  const error = ref<string | null>(null)

  function serverFor(serverId: string): DbServerStatus | null {
    return servers.value.find((s) => s.server_id === serverId) ?? null
  }

  function instanceFor(serverId: string, credentialId: string): DbInstanceStatus | null {
    return serverFor(serverId)?.instances.find((i) => i.credential_id === credentialId) ?? null
  }

  function latestFor(serverId: string): DbMetricsLatest {
    return latest.value[serverId] ?? EMPTY_LATEST
  }

  function connectionPct(serverId: string): number {
    const l = latestFor(serverId)
    if (!l.connections_active || !l.connections_max) return 0
    return Math.round((l.connections_active / l.connections_max) * 100)
  }

  // --- Actions ---------------------------------------------------------------

  async function fetchCredentials(orgId: string): Promise<void> {
    loadingCredentials.value = true
    error.value = null
    try {
      const { data } = await api.get<DbServerStatus[]>(
        `/api/organizations/${orgId}/db-credentials`,
      )
      servers.value = data
    } catch {
      error.value = 'Could not load database credential status.'
    } finally {
      loadingCredentials.value = false
    }
  }

  async function saveCredentials(
    serverId: string,
    payload: DbCredentialPayload,
    credentialId: string | null,
  ): Promise<void> {
    const base = `/api/servers/${serverId}/db-credentials`
    if (credentialId) {
      await api.patch(`${base}/${credentialId}`, payload)
    } else {
      await api.post(base, payload)
    }
  }

  async function deleteCredentials(serverId: string, credentialId: string): Promise<void> {
    await api.delete(`/api/servers/${serverId}/db-credentials/${credentialId}`)
    const server = serverFor(serverId)
    if (server) {
      server.instances = server.instances.filter((i) => i.credential_id !== credentialId)
    }
    delete latest.value[`${serverId}:${credentialId}`]
  }

  async function fetchLatest(serverId: string, credentialId: string): Promise<void> {
    loadingLatest.value = true
    try {
      const { data } = await api.get<DbMetricsLatest>(
        `/api/servers/${serverId}/db-metrics/latest`,
        { params: { credential_id: credentialId } },
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
    credentialId: string,
  ): Promise<DbSeriesResponse> {
    const { data } = await api.get<DbSeriesResponse>(
      `/api/servers/${serverId}/db-metrics`,
      { params: { metric, range, credential_id: credentialId } },
    )
    return data
  }

  async function fetchPassword(serverId: string, credentialId: string): Promise<string> {
    const { data } = await api.get<{ password: string }>(
      `/api/servers/${serverId}/db-credentials/${credentialId}/password`,
    )
    return data.password
  }

  function reset(): void {
    servers.value = []
    latest.value = {}
    loadingCredentials.value = false
    loadingLatest.value = false
    error.value = null
  }

  return {
    servers,
    // legacy alias so DatabasesView can use store.credentials until fully migrated
    credentials: servers,
    latest,
    loadingCredentials,
    loadingLatest,
    error,
    serverFor,
    instanceFor,
    latestFor,
    connectionPct,
    fetchCredentials,
    saveCredentials,
    deleteCredentials,
    fetchLatest,
    fetchSeries,
    fetchPassword,
    reset,
  }
})
