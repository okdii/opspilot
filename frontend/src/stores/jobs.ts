import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/services/api'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface MonitoredJob {
  id: string
  server_id: string
  server_name: string
  name: string
  description: string | null
  schedule: string
  grace_period_min: number
  ping_url: string
  status: string
  last_ping_at: string | null
  start_ping_at: string | null
  last_duration_sec: number | null
  last_size_bytes: number | null
  last_size_formatted: string | null
  last_files_count: number | null
  last_exit_code: number | null
  last_label: string | null
  next_expected_at: string | null
}

export interface JobRun {
  id: string
  ran_at: string
  outcome: string
  duration_sec: number | null
  size_bytes: number | null
  size_formatted: string | null
  files_count: number | null
  exit_code: number | null
  label: string | null
  started_at: string | null
}

export interface TodayRun {
  id: string
  ran_at: string
  started_at: string | null
  outcome: string
  duration_sec: number | null
  size_bytes: number | null
  size_formatted: string | null
  files_count: number | null
  exit_code: number | null
  label: string | null
  job_id: string
  job_name: string
  server_name: string
}

export interface JobPayload {
  server_id: string
  name: string
  schedule: string
  grace_period_min: number
  description?: string | null
}

interface RunsResponse {
  runs: JobRun[]
  next_cursor: string | null
}

// Sort: missing → late → healthy, then server name, then job name
const STATUS_ORDER: Record<string, number> = { missing: 0, late: 1, healthy: 2 }

function bySeverityThenName(a: MonitoredJob, b: MonitoredJob): number {
  const so = (STATUS_ORDER[a.status] ?? 99) - (STATUS_ORDER[b.status] ?? 99)
  if (so !== 0) return so
  const sv = a.server_name.localeCompare(b.server_name)
  if (sv !== 0) return sv
  return a.name.localeCompare(b.name)
}

export const useJobsStore = defineStore('jobs', () => {
  const jobs = ref<MonitoredJob[]>([])
  const isLoadingList = ref(false)
  const isLoadingDetail = ref(false)
  const error = ref<string | null>(null)
  const todayRuns = ref<TodayRun[]>([])

  // ── Getters ──────────────────────────────────────────────────────────────
  const sortedJobs = computed(() => [...jobs.value].sort(bySeverityThenName))

  const jobsByServer = computed(() => (serverId: string) =>
    jobs.value.filter((j) => j.server_id === serverId)
  )

  const missingCount = computed(() => jobs.value.filter((j) => j.status === 'missing').length)

  // ── Actions ──────────────────────────────────────────────────────────────
  async function fetchJobs(orgId: string): Promise<void> {
    isLoadingList.value = true
    error.value = null
    try {
      const { data } = await api.get<MonitoredJob[]>(`/api/organizations/${orgId}/jobs`)
      jobs.value = data
    } catch {
      error.value = 'Could not load jobs.'
    } finally {
      isLoadingList.value = false
    }
  }

  async function fetchTodayRuns(orgId: string): Promise<void> {
    try {
      const { data } = await api.get<TodayRun[]>(`/api/organizations/${orgId}/runs/today`)
      todayRuns.value = data
    } catch {
      todayRuns.value = []
    }
  }

  async function createJob(payload: JobPayload): Promise<MonitoredJob> {
    const { data } = await api.post<MonitoredJob>('/api/jobs', payload)
    jobs.value.unshift(data)
    return data
  }

  async function updateJob(id: string, payload: Partial<JobPayload>): Promise<MonitoredJob> {
    const { data } = await api.patch<MonitoredJob>(`/api/jobs/${id}`, payload)
    const idx = jobs.value.findIndex((j) => j.id === id)
    if (idx >= 0) jobs.value[idx] = data
    return data
  }

  async function deleteJob(id: string): Promise<void> {
    await api.delete(`/api/jobs/${id}`)
    jobs.value = jobs.value.filter((j) => j.id !== id)
  }

  async function fetchRuns(jobId: string, cursor?: string | null): Promise<RunsResponse> {
    isLoadingDetail.value = true
    try {
      const params: Record<string, string> = {}
      if (cursor) params.cursor = cursor
      const { data } = await api.get<RunsResponse>(`/api/jobs/${jobId}/runs`, { params })
      return data
    } finally {
      isLoadingDetail.value = false
    }
  }

  async function regenerateToken(id: string): Promise<string> {
    const { data } = await api.post<MonitoredJob>(`/api/jobs/${id}/regenerate-token`)
    const idx = jobs.value.findIndex((j) => j.id === id)
    if (idx >= 0) jobs.value[idx] = data
    return data.ping_url
  }

  function reset(): void {
    jobs.value = []
    todayRuns.value = []
    error.value = null
  }

  return {
    jobs,
    isLoadingList,
    isLoadingDetail,
    error,
    todayRuns,
    sortedJobs,
    jobsByServer,
    missingCount,
    fetchJobs,
    fetchTodayRuns,
    createJob,
    updateJob,
    deleteJob,
    fetchRuns,
    regenerateToken,
    reset,
  }
})
