import axios, { AxiosError } from 'axios'
import type {
  ApiError,
  DashboardData,
  LatestValues,
  MaintenanceState,
  MetricRange,
  MetricsResponse,
  RecentAlert,
  StartMaintenancePayload,
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
