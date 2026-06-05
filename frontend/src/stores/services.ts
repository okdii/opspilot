import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/services/api'

// ── Types (co-located; mirror spec 06 §10 + live API responses) ──────────────

export type ServiceType = 'http' | 'tcp' | 'db'
export type ServiceStatus = 'up' | 'down' | 'timeout' | null

export interface Service {
  id: string
  server_id: string
  server_name: string
  name: string
  type: ServiceType
  url: string | null
  port: number | null
  expected_status: number | null
  interval_sec: number
  timeout_sec: number
  is_active: boolean
  is_public: boolean
  ignore_ssl_errors: boolean
  last_status: ServiceStatus
  last_checked: string | null
  consecutive_failures: number
  uptime_24h: number | null
  uptime_7d: number | null
  avg_response_ms_24h: number | null
  open_incident_id: string | null
  ssl_enabled: boolean
  ssl_warn_days: number
  ssl_critical_days: number
  ssl_expiry_date: string | null
  ssl_days_remaining: number | null
  ssl_status: string | null
  ssl_issuer: string | null
  ssl_last_checked: string | null
}

export interface ServiceCreatePayload {
  server_id: string
  name: string
  type: ServiceType
  url?: string | null
  port?: number | null
  expected_status?: number | null
  interval_sec: number
  timeout_sec: number
  is_active: boolean
  is_public: boolean
  ignore_ssl_errors: boolean
  ssl_warn_days?: number
  ssl_critical_days?: number
}

export type ServiceUpdatePayload = Partial<Omit<ServiceCreatePayload, 'server_id' | 'type'>>

export interface ServiceCheck {
  time: string
  status: string
  response_time_ms: number | null
}

export interface ChecksPage {
  checks: ServiceCheck[]
  next_cursor: string | null
}

export interface Incident {
  id: string
  started_at: string | null
  resolved_at: string | null
  duration_sec: number | null
}

export interface IncidentsPage {
  page: number
  page_size: number
  incidents: Incident[]
}

export interface SecurityTls {
  version: string | null
  ok: boolean | null
  cipher_suite: string | null
  cipher_ok: boolean | null
  pfs: boolean | null
  key_size: number | null
  key_size_ok: boolean | null
  self_signed: boolean | null
  ocsp: boolean | null
}

export interface SecurityHeaders {
  https_redirect: boolean | null
  hsts: boolean | null
  hsts_max_age: number | null
  csp: boolean | null
  x_frame_options: boolean | null
  x_content_type: boolean | null
  referrer_policy: boolean | null
  permissions_policy: boolean | null
  server_disclosure: boolean | null
  x_powered_by: string | null
}

export interface SecurityFinding {
  check: string
  severity: string
  passed: boolean
  detail: string
}

export interface SecurityScan {
  grade: string
  score: number
  scanned_at: string
  tls: SecurityTls
  headers: SecurityHeaders
  findings: SecurityFinding[]
}

export interface UptimePoint {
  date: string
  uptime_pct: number
  down_minutes: number
}

export interface ResponsePoint {
  time: string
  avg_ms: number | null
  p95_ms: number | null
}

export interface ResponseTimeData {
  range: string
  data: ResponsePoint[]
}

export type ResponseRange = '1h' | '6h' | '24h' | '7d' | '30d'

// ── WS event shapes (spec 06 §7) ─────────────────────────────────────────────

export interface ServiceCheckEvent {
  service_id: string
  status: string
  response_time_ms: number | null
  checked_at: string
  consecutive_failures: number
  last_status: string
}

export interface IncidentOpenedEvent {
  incident_id: string
  service_id: string
  started_at: string
  cause?: string
}

export interface IncidentResolvedEvent {
  incident_id: string
  service_id: string
  resolved_at: string
  duration_sec: number
}

// ── Store ────────────────────────────────────────────────────────────────────

export const useServiceStore = defineStore('services', () => {
  const services = ref<Service[]>([])
  const activeService = ref<Service | null>(null)
  const incidents = ref<Incident[]>([])
  const checkHistory = ref<ServiceCheck[]>([])
  const checksCursor = ref<string | null>(null)
  const uptimeTimeline = ref<UptimePoint[]>([])

  const isLoadingList = ref(false)
  const isLoadingDetail = ref(false)
  const error = ref<string | null>(null)

  // Down services float to the top, then server name → service name.
  const sortedServices = computed(() =>
    [...services.value].sort((a, b) => {
      const ad = a.last_status === 'down' ? 0 : 1
      const bd = b.last_status === 'down' ? 0 : 1
      if (ad !== bd) return ad - bd
      const sn = (a.server_name || '').localeCompare(b.server_name || '')
      if (sn !== 0) return sn
      return a.name.localeCompare(b.name)
    }),
  )

  const downServices = computed(() => services.value.filter((s) => s.last_status === 'down'))
  const allPaused = computed(
    () => services.value.length > 0 && services.value.every((s) => !s.is_active),
  )

  function servicesByServer(serverId: string): Service[] {
    return services.value.filter((s) => s.server_id === serverId)
  }

  // ── List / detail fetch ────────────────────────────────────────────────────

  async function fetchServices(orgId: string): Promise<void> {
    isLoadingList.value = true
    error.value = null
    try {
      const { data } = await api.get<Service[]>(`/api/organizations/${orgId}/services`)
      services.value = data
    } catch {
      error.value = 'Could not load services.'
    } finally {
      isLoadingList.value = false
    }
  }

  async function fetchService(serviceId: string): Promise<Service> {
    isLoadingDetail.value = true
    error.value = null
    try {
      const { data } = await api.get<Service>(`/api/services/${serviceId}`)
      activeService.value = data
      return data
    } finally {
      isLoadingDetail.value = false
    }
  }

  async function fetchUptimeTimeline(serviceId: string, days = 90): Promise<void> {
    const { data } = await api.get<UptimePoint[]>(
      `/api/services/${serviceId}/uptime-timeline`,
      { params: { days } },
    )
    uptimeTimeline.value = data
  }

  async function fetchResponseTime(serviceId: string, range: ResponseRange): Promise<ResponseTimeData> {
    const { data } = await api.get<ResponseTimeData>(
      `/api/services/${serviceId}/response-time`,
      { params: { range } },
    )
    return data
  }

  async function fetchIncidents(serviceId: string, page = 1): Promise<IncidentsPage> {
    const { data } = await api.get<IncidentsPage>(
      `/api/services/${serviceId}/incidents`,
      { params: { page } },
    )
    incidents.value = data.incidents
    return data
  }

  async function fetchChecks(serviceId: string, cursor?: string | null): Promise<ChecksPage> {
    const params: Record<string, string> = {}
    if (cursor) params.cursor = cursor
    const { data } = await api.get<ChecksPage>(
      `/api/services/${serviceId}/checks`,
      { params },
    )
    if (cursor) checkHistory.value = [...checkHistory.value, ...data.checks]
    else checkHistory.value = data.checks
    checksCursor.value = data.next_cursor
    return data
  }

  async function fetchSecurityScan(orgId: string, serviceId: string): Promise<SecurityScan | null> {
    try {
      const { data } = await api.get<SecurityScan>(
        `/api/organizations/${orgId}/services/${serviceId}/security`
      )
      return data
    } catch {
      return null
    }
  }

  // ── Mutations (Admin) ──────────────────────────────────────────────────────

  async function createService(payload: ServiceCreatePayload): Promise<Service> {
    const { data } = await api.post<Service>('/api/services', payload)
    services.value.unshift(data)
    return data
  }

  async function updateService(id: string, payload: ServiceUpdatePayload): Promise<Service> {
    const { data } = await api.patch<Service>(`/api/services/${id}`, payload)
    const idx = services.value.findIndex((s) => s.id === id)
    if (idx >= 0) services.value[idx] = data
    if (activeService.value?.id === id) activeService.value = data
    return data
  }

  async function deleteService(id: string): Promise<void> {
    await api.delete(`/api/services/${id}`)
    services.value = services.value.filter((s) => s.id !== id)
    if (activeService.value?.id === id) activeService.value = null
  }

  async function toggleActive(id: string): Promise<Service> {
    const svc = services.value.find((s) => s.id === id) ?? activeService.value
    const next = !(svc?.is_active ?? true)
    return updateService(id, { is_active: next })
  }

  // ── WS handlers (spec 06 §7.4) ──────────────────────────────────────────────

  function applyToService(serviceId: string, mutate: (s: Service) => void): void {
    const listed = services.value.find((s) => s.id === serviceId)
    if (listed) mutate(listed)
    if (activeService.value?.id === serviceId) mutate(activeService.value)
  }

  function handleCheckEvent(ev: ServiceCheckEvent): void {
    applyToService(ev.service_id, (s) => {
      s.last_status = ev.last_status as ServiceStatus
      s.last_checked = ev.checked_at
      s.consecutive_failures = ev.consecutive_failures
      if (ev.status === 'up' && ev.response_time_ms != null) {
        s.avg_response_ms_24h = ev.response_time_ms
      }
    })
  }

  function handleIncidentOpened(ev: IncidentOpenedEvent): void {
    applyToService(ev.service_id, (s) => {
      s.open_incident_id = ev.incident_id
      s.last_status = 'down'
    })
  }

  function handleSslEvent(ev: { service_id: string; ssl_status: string; ssl_expiry_date: string; ssl_days_remaining: number; ssl_issuer: string; ssl_last_checked: string }): void {
    applyToService(ev.service_id, (s) => {
      s.ssl_status = ev.ssl_status
      s.ssl_expiry_date = ev.ssl_expiry_date
      s.ssl_days_remaining = ev.ssl_days_remaining
      s.ssl_issuer = ev.ssl_issuer
      s.ssl_last_checked = ev.ssl_last_checked
    })
  }

  function handleIncidentResolved(ev: IncidentResolvedEvent): void {
    applyToService(ev.service_id, (s) => {
      s.open_incident_id = null
    })
    // Reflect resolution in the open detail-page incident list if present.
    const inc = incidents.value.find((i) => i.id === ev.incident_id)
    if (inc) {
      inc.resolved_at = ev.resolved_at
      inc.duration_sec = ev.duration_sec
    }
  }

  function reset(): void {
    services.value = []
    activeService.value = null
    incidents.value = []
    checkHistory.value = []
    checksCursor.value = null
    uptimeTimeline.value = []
    isLoadingList.value = false
    isLoadingDetail.value = false
    error.value = null
  }

  return {
    services,
    activeService,
    incidents,
    checkHistory,
    checksCursor,
    uptimeTimeline,
    isLoadingList,
    isLoadingDetail,
    error,
    sortedServices,
    downServices,
    allPaused,
    servicesByServer,
    fetchServices,
    fetchService,
    fetchUptimeTimeline,
    fetchResponseTime,
    fetchIncidents,
    fetchChecks,
    fetchSecurityScan,
    createService,
    updateService,
    deleteService,
    toggleActive,
    handleCheckEvent,
    handleSslEvent,
    handleIncidentOpened,
    handleIncidentResolved,
    reset,
  }
})
