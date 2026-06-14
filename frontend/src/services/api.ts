import axios, { AxiosError } from 'axios'
import type {
  ApiError,
  DashboardData,
  LatestValues,
  MaintenanceState,
  MetricRange,
  MetricsResponse,
  MonitoringService,
  ProcessSnapshot,
  RecentAlert,
  Server,
  ServerServiceEntry,
  StartMaintenancePayload,
  LogsResponse,
  VolumeResponse,
  LogSummary,
  Alert,
  AlertHistoryPage,
  AlertHistoryFilters,
  FrequencyBucket,
  SnoozePayload,
  AlertRules,
  MetricRule,
  LogRule,
  MetricRulePayload,
  LogRulePayload,
  VhostEntry,
  DailyReport,
} from '@/types'

export const api = axios.create({
  baseURL: '/',
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

// Global 401 interceptor → redirect to login
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ detail?: ApiError }>) => {
    if (error.response?.status === 401) {
      const path = window.location.pathname
      const isAuthRoute =
        path === '/login' ||
        path === '/setup' ||
        path.startsWith('/invite/')
      if (!isAuthRoute) {
        // Lazy import to avoid circular dep
        import('@/stores/auth').then(({ useAuthStore }) => {
          useAuthStore().clearLocal()
        })
        window.location.href = '/login?reason=expired'
      }
    }
    return Promise.reject(error)
  },
)

export function getApiError(err: unknown): ApiError | null {
  if (axios.isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: ApiError } | undefined)?.detail
    if (detail && typeof detail === 'object') return detail
  }
  return null
}

export async function getDashboard(orgId: string): Promise<DashboardData> {
  const { data } = await api.get<DashboardData>(`/api/organizations/${orgId}/dashboard`)
  return data
}

export async function getRecentAlerts(orgId: string): Promise<RecentAlert[]> {
  const { data } = await api.get<RecentAlert[]>(`/api/organizations/${orgId}/alerts/recent`)
  return data
}

// --- Server Detail metrics + maintenance (Phase 2) -------------------------

export async function getServer(serverId: string): Promise<Server> {
  const { data } = await api.get<Server>(`/api/servers/${serverId}`)
  return data
}

export async function getMetrics(
  serverId: string,
  range: MetricRange,
  metrics: string[],
  labelFilter?: string,
): Promise<MetricsResponse> {
  const params: Record<string, string> = { range, metrics: metrics.join(',') }
  if (labelFilter) params.label_filter = labelFilter
  const { data } = await api.get<MetricsResponse>(`/api/servers/${serverId}/metrics`, { params })
  return data
}

export async function getLatest(serverId: string): Promise<LatestValues> {
  const { data } = await api.get<LatestValues>(`/api/servers/${serverId}/metrics/latest`)
  return data
}

export async function getMaintenance(serverId: string): Promise<MaintenanceState> {
  const { data } = await api.get<MaintenanceState>(`/api/servers/${serverId}/maintenance`)
  return data
}

export async function startMaintenance(
  serverId: string,
  payload: StartMaintenancePayload = {},
): Promise<MaintenanceState> {
  const { data } = await api.post<MaintenanceState>(`/api/servers/${serverId}/maintenance`, payload)
  return data
}

export async function endMaintenance(serverId: string): Promise<void> {
  await api.delete(`/api/servers/${serverId}/maintenance`)
}

export async function getProcesses(serverId: string): Promise<ProcessSnapshot> {
  const { data } = await api.get<ProcessSnapshot>(`/api/servers/${serverId}/processes`)
  return data
}

export async function getServerServices(
  serverId: string,
  includeNotInstalled = false,
): Promise<ServerServiceEntry[]> {
  const params: Record<string, string> = {}
  if (includeNotInstalled) params.include_not_installed = 'true'
  const { data } = await api.get<ServerServiceEntry[]>(
    `/api/servers/${serverId}/services`,
    { params },
  )
  return data
}

export async function muteServerService(
  serverId: string,
  serviceName: string,
): Promise<void> {
  await api.put(`/api/servers/${serverId}/services/${encodeURIComponent(serviceName)}/mute`)
}

export async function unmuteServerService(
  serverId: string,
  serviceName: string,
): Promise<void> {
  await api.delete(`/api/servers/${serverId}/services/${encodeURIComponent(serviceName)}/mute`)
}

export async function getServerMonitoring(serverId: string): Promise<MonitoringService[]> {
  const { data } = await api.get<MonitoringService[]>(`/api/servers/${serverId}/monitoring`)
  return data
}

// --- Log Viewer (Phase 3, spec 05) -----------------------------------------

export interface LogIntelligenceData {
  summary: { error: number; warn: number; info: number; debug: number }
  top_errors: { message: string; count: number; source: string; last_seen: string }[]
  http_errors: {
    total_5xx: number
    total_4xx: number
    top_urls: { url: string; count: number; status: number }[]
  } | null
  slow_queries: {
    total: number
    worst_duration_ms: number
    worst_query: string
    server_name: string
  } | null
  auth_events: {
    failed_logins: number
    top_ips: { ip: string; count: number }[]
    successful_logins: number
    successful_top: { user: string; ip: string; count: number }[]
  } | null
  per_server: {
    server_id: string
    server_name: string
    error: number
    warn: number
    sparkline: number[]
  }[]
}

export async function getLogIntelligence(orgId: string | null, range: string, serverId?: string): Promise<LogIntelligenceData> {
  const params: Record<string, string> = { range }
  if (orgId) params.org_id = orgId
  if (serverId) params.server_id = serverId
  const { data } = await api.get<LogIntelligenceData>('/api/logs/intelligence', { params })
  return data
}

export async function getLogs(params: Record<string, string>): Promise<LogsResponse> {
  const { data } = await api.get<LogsResponse>('/api/logs', { params })
  return data
}

export async function getLogVolume(params: Record<string, string>): Promise<VolumeResponse> {
  const { data } = await api.get<VolumeResponse>('/api/logs/volume', { params })
  return data
}

export async function getLogSummary(params: Record<string, string>): Promise<LogSummary> {
  const { data } = await api.get<LogSummary>('/api/logs/summary', { params })
  return data
}

// --- Alerting (Phase 8, spec 10) -------------------------------------------

export async function getActiveAlerts(orgId: string): Promise<Alert[]> {
  const { data } = await api.get<Alert[]>(`/api/organizations/${orgId}/alerts`)
  return data
}

export async function getAlertHistory(
  orgId: string,
  filters: AlertHistoryFilters = {},
  cursor?: string | null,
  limit = 50,
): Promise<AlertHistoryPage> {
  const params: Record<string, string> = { limit: String(limit) }
  if (cursor) params.cursor = cursor
  if (filters.server_id) params.server_id = filters.server_id
  if (filters.type) params.type = filters.type
  if (filters.start) params.start = filters.start
  if (filters.end) params.end = filters.end
  if (filters.search) params.search = filters.search
  const { data } = await api.get<AlertHistoryPage>(`/api/organizations/${orgId}/alerts/history`, { params })
  return data
}

export async function getAlertFrequency(orgId: string): Promise<FrequencyBucket[]> {
  const { data } = await api.get<FrequencyBucket[]>(`/api/organizations/${orgId}/alerts/frequency`)
  return data
}

export async function acknowledgeAlert(alertId: string): Promise<Alert> {
  const { data } = await api.post<Alert>(`/api/alerts/${alertId}/acknowledge`)
  return data
}

export async function snoozeAlert(alertId: string, payload: SnoozePayload): Promise<Alert> {
  const { data } = await api.post<Alert>(`/api/alerts/${alertId}/snooze`, payload)
  return data
}

export async function getAlertRules(orgId: string): Promise<AlertRules> {
  const { data } = await api.get<AlertRules>(`/api/organizations/${orgId}/alert-rules`)
  return data
}

export async function createMetricRule(payload: MetricRulePayload): Promise<MetricRule> {
  const { data } = await api.post<MetricRule>('/api/alert-rules', payload)
  return data
}

export async function patchMetricRule(id: string, payload: MetricRulePayload): Promise<MetricRule> {
  const { data } = await api.patch<MetricRule>(`/api/alert-rules/${id}`, payload)
  return data
}

export async function deleteMetricRule(id: string): Promise<void> {
  await api.delete(`/api/alert-rules/${id}`)
}

export async function createLogRule(payload: LogRulePayload): Promise<LogRule> {
  const { data } = await api.post<LogRule>('/api/log-alert-rules', payload)
  return data
}

export async function patchLogRule(id: string, payload: LogRulePayload): Promise<LogRule> {
  const { data } = await api.patch<LogRule>(`/api/log-alert-rules/${id}`, payload)
  return data
}

export async function deleteLogRule(id: string): Promise<void> {
  await api.delete(`/api/log-alert-rules/${id}`)
}

export async function scanVhosts(serverId: string): Promise<VhostEntry[]> {
  const { data } = await api.post<VhostEntry[]>(`/api/servers/${serverId}/scan-vhosts`)
  return data
}

// --- Daily Report ----------------------------------------------------------

export async function getDailyReport(
  serverId: string,
  reportDate?: string,
): Promise<DailyReport> {
  const params: Record<string, string> = {}
  if (reportDate) params.report_date = reportDate
  const { data } = await api.get<DailyReport>(
    `/api/servers/${serverId}/daily-report`,
    { params },
  )
  return data
}

export async function regenerateDailyReport(
  serverId: string,
  reportDate: string,
): Promise<DailyReport> {
  const { data } = await api.post<DailyReport>(
    `/api/servers/${serverId}/daily-report/regenerate`,
    { date: reportDate },
  )
  return data
}

// --- Kernel Events -----------------------------------------------------------

export interface KernelEventsResponse {
  counts: { emerg: number; alert: number; crit: number; err: number; warn: number }
  events: Array<{ ts: string; severity: string; message: string }>
}

export async function getKernelEvents(
  serverId: string,
  range: string,
): Promise<KernelEventsResponse> {
  const { data } = await api.get<KernelEventsResponse>(
    `/api/servers/${serverId}/kernel-events`,
    { params: { range } },
  )
  return data
}
