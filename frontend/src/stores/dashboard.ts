import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getDashboard } from '@/services/api'
import type { DashboardData, DashboardServer, DashboardSummary } from '@/types'

const EMPTY_SUMMARY: DashboardSummary = {
  servers: { total: 0, online: 0, offline: 0, maintenance: 0 },
  services: { up: 0, down: 0 },
  alerts: { firing: 0, snoozed: 0, acknowledged: 0 },
  ssl_domains: { expiring: 0, expired: 0 },
}

// WS push metric_name → DashboardServer.metrics key
const CPU_METRIC = 'cpu.usage_active'
const RAM_METRIC = 'mem.used_percent'
const DISK_METRIC = 'disk.used_percent'

interface PushRow {
  metric_name: string
  value: number | null
  labels: Record<string, unknown>
  time: string
}

export const useDashboardStore = defineStore('dashboard', () => {
  const summary = ref<DashboardSummary>({ ...EMPTY_SUMMARY })
  const servers = ref<DashboardServer[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchDashboard(orgId: string): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const data: DashboardData = await getDashboard(orgId)
      summary.value = data.summary
      servers.value = data.servers
    } catch {
      error.value = 'Could not load dashboard data.'
    } finally {
      loading.value = false
    }
  }

  // Apply a live server_metrics batch in place (no re-fetch).
  function applyMetricPush(serverId: string, rows: PushRow[]): void {
    const server = servers.value.find((s) => s.id === serverId)
    if (!server) return
    for (const row of rows) {
      if (row.value == null) continue
      if (row.metric_name === CPU_METRIC) server.metrics.cpu = row.value
      else if (row.metric_name === RAM_METRIC) server.metrics.ram = row.value
      else if (row.metric_name === DISK_METRIC && row.labels?.path === '/') server.metrics.disk = row.value
    }
  }

  function reset(): void {
    summary.value = { ...EMPTY_SUMMARY }
    servers.value = []
    loading.value = false
    error.value = null
  }

  return { summary, servers, loading, error, fetchDashboard, applyMetricPush, reset }
})
