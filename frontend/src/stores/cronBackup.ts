import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/services/api'

// ── Co-located types (spec 09 §10/§11) ──────────────────────────────────────

export interface CronJob {
  id: string
  server_id: string
  server_name: string
  name: string
  schedule: string
  grace_period_min: number
  ping_url: string
  last_ping_at: string | null
  start_ping_at: string | null
  last_duration_sec: number | null
  status: string
  next_expected_at: string | null
}

export interface BackupJob {
  id: string
  server_id: string
  server_name: string
  name: string
  description: string | null
  expected_interval_hours: number
  ping_url: string
  last_ping_at: string | null
  last_size_bytes: number | null
  last_size_formatted: string | null
  last_status_text: string | null
  previous_size_bytes: number | null
  last_files_count: number | null
  status: string
  next_expected_at: string | null
}

/** Unified run shape for both job types. Cron runs carry duration; backup runs carry size/exit. */
export interface JobRun {
  id: string
  ran_at: string
  outcome: string
  duration_sec?: number | null
  size_bytes?: number | null
  size_formatted?: string | null
  exit_code?: number | null
  files_count?: number | null
}

interface RunsResponse {
  runs: JobRun[]
  next_cursor: string | null
}

export interface CronJobPayload {
  server_id: string
  name: string
  schedule: string
  grace_period_min: number
}

export interface BackupJobPayload {
  server_id: string
  name: string
  expected_interval_hours: number
  description?: string | null
}

export type JobType = 'cron' | 'backup'

// Sort weight: Missing floats to top, then Late, then Healthy.
const STATUS_ORDER: Record<string, number> = { missing: 0, late: 1, healthy: 2 }

function bySeverityThenName<T extends { status: string; server_name: string; name: string }>(a: T, b: T): number {
  const so = (STATUS_ORDER[a.status] ?? 99) - (STATUS_ORDER[b.status] ?? 99)
  if (so !== 0) return so
  const sv = a.server_name.localeCompare(b.server_name)
  if (sv !== 0) return sv
  return a.name.localeCompare(b.name)
}

export const useCronBackupStore = defineStore('cronBackup', () => {
  const cronJobs = ref<CronJob[]>([])
  const backupJobs = ref<BackupJob[]>([])
  const isLoadingList = ref(false)
  const isLoadingDetail = ref(false)
  const error = ref<string | null>(null)

  // ── Getters ────────────────────────────────────────────────────────────
  const sortedCronJobs = computed(() => [...cronJobs.value].sort(bySeverityThenName))
  const sortedBackupJobs = computed(() => [...backupJobs.value].sort(bySeverityThenName))
  const missingCronCount = computed(() => cronJobs.value.filter((j) => j.status === 'missing').length)
  const missingBackupCount = computed(() => backupJobs.value.filter((j) => j.status === 'missing').length)
  const totalMissingCount = computed(() => missingCronCount.value + missingBackupCount.value)

  // ── List ──────────────────────────────────────────────────────────────
  async function fetchCronJobs(orgId: string): Promise<void> {
    isLoadingList.value = true
    error.value = null
    try {
      const { data } = await api.get<CronJob[]>(`/api/organizations/${orgId}/cron-jobs`)
      cronJobs.value = data
    } catch {
      error.value = 'Could not load cron jobs.'
    } finally {
      isLoadingList.value = false
    }
  }

  async function fetchBackupJobs(orgId: string): Promise<void> {
    isLoadingList.value = true
    error.value = null
    try {
      const { data } = await api.get<BackupJob[]>(`/api/organizations/${orgId}/backup-jobs`)
      backupJobs.value = data
    } catch {
      error.value = 'Could not load backup jobs.'
    } finally {
      isLoadingList.value = false
    }
  }

  // ── Cron CRUD ───────────────────────────────────────────────────────────
  async function createCronJob(payload: CronJobPayload): Promise<CronJob> {
    const { data } = await api.post<CronJob>('/api/cron-jobs', payload)
    cronJobs.value.unshift(data)
    return data
  }

  async function updateCronJob(id: string, payload: Partial<CronJobPayload>): Promise<CronJob> {
    const { data } = await api.patch<CronJob>(`/api/cron-jobs/${id}`, payload)
    const idx = cronJobs.value.findIndex((j) => j.id === id)
    if (idx >= 0) cronJobs.value[idx] = data
    return data
  }

  async function deleteCronJob(id: string): Promise<void> {
    await api.delete(`/api/cron-jobs/${id}`)
    cronJobs.value = cronJobs.value.filter((j) => j.id !== id)
  }

  // ── Backup CRUD ─────────────────────────────────────────────────────────
  async function createBackupJob(payload: BackupJobPayload): Promise<BackupJob> {
    const { data } = await api.post<BackupJob>('/api/backup-jobs', payload)
    backupJobs.value.unshift(data)
    return data
  }

  async function updateBackupJob(id: string, payload: Partial<BackupJobPayload>): Promise<BackupJob> {
    const { data } = await api.patch<BackupJob>(`/api/backup-jobs/${id}`, payload)
    const idx = backupJobs.value.findIndex((j) => j.id === id)
    if (idx >= 0) backupJobs.value[idx] = data
    return data
  }

  async function deleteBackupJob(id: string): Promise<void> {
    await api.delete(`/api/backup-jobs/${id}`)
    backupJobs.value = backupJobs.value.filter((j) => j.id !== id)
  }

  // ── Runs (cursor-paginated) ──────────────────────────────────────────────
  async function fetchRuns(type: JobType, jobId: string, cursor?: string | null): Promise<RunsResponse> {
    isLoadingDetail.value = true
    try {
      const base = type === 'cron' ? 'cron-jobs' : 'backup-jobs'
      const params: Record<string, string> = {}
      if (cursor) params.cursor = cursor
      const { data } = await api.get<RunsResponse>(`/api/${base}/${jobId}/runs`, { params })
      return data
    } finally {
      isLoadingDetail.value = false
    }
  }

  // ── Regenerate token → returns updated job (with new ping_url) ─────────────
  async function regenerateToken(type: JobType, id: string): Promise<string> {
    if (type === 'cron') {
      const { data } = await api.post<CronJob>(`/api/cron-jobs/${id}/regenerate-token`)
      const idx = cronJobs.value.findIndex((j) => j.id === id)
      if (idx >= 0) cronJobs.value[idx] = data
      return data.ping_url
    }
    const { data } = await api.post<BackupJob>(`/api/backup-jobs/${id}/regenerate-token`)
    const idx = backupJobs.value.findIndex((j) => j.id === id)
    if (idx >= 0) backupJobs.value[idx] = data
    return data.ping_url
  }

  function reset(): void {
    cronJobs.value = []
    backupJobs.value = []
    error.value = null
  }

  return {
    cronJobs,
    backupJobs,
    isLoadingList,
    isLoadingDetail,
    error,
    sortedCronJobs,
    sortedBackupJobs,
    missingCronCount,
    missingBackupCount,
    totalMissingCount,
    fetchCronJobs,
    fetchBackupJobs,
    createCronJob,
    updateCronJob,
    deleteCronJob,
    createBackupJob,
    updateBackupJob,
    deleteBackupJob,
    fetchRuns,
    regenerateToken,
    reset,
  }
})
