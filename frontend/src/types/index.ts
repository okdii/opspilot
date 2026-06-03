export interface OrgRef {
  id: string
  name: string
  slug: string
  my_role: 'admin' | 'operator' | 'viewer'
}

export interface User {
  id: string
  username: string
  role: 'admin' | 'member'
  created_at?: string
  orgs: OrgRef[]
}

export interface Organization {
  id: string
  name: string
  slug: string
  description: string | null
  created_at: string
}

export interface OrgStats {
  server_count: number
  domain_count: number
  member_count: number
}

export interface Server {
  id: string
  org_id: string
  name: string
  host: string
  ssh_port: number
  ssh_user: string
  ssh_auth_type: 'key' | 'password'
  os_distro: string | null
  kernel_version: string | null
  tags: string[]
  is_active: boolean
  status: 'pending' | 'online' | 'offline' | 'maintenance'
  last_seen_at: string | null
  active_alert_count: number
  created_at: string
}

export type OnboardingStatus = 'pending' | 'running' | 'done' | 'failed' | 'skipped'
export type OnboardingOutcome = 'pending' | 'running' | 'success' | 'failed'

export interface OnboardingStep {
  step: string
  step_number: number | null
  status: OnboardingStatus
  message: string | null
  ssh_output: string | null
  duration_ms: number | null
  started_at: string | null
  created_at: string
}

export interface OnboardingResponse {
  server_id: string
  started_at: string | null
  completed_at: string | null
  outcome: OnboardingOutcome
  steps: OnboardingStep[]
}

export interface ApiError {
  error: string
  message: string
  [key: string]: unknown
}

export interface ServerMetrics {
  cpu: number | null
  ram: number | null
  disk: number | null
}

export interface DashboardServer {
  id: string
  name: string
  host: string
  tags: string[]
  status: 'pending' | 'online' | 'offline' | 'maintenance'
  last_seen_at: string | null
  metrics: ServerMetrics
}

export interface DashboardSummary {
  servers: { total: number; online: number; offline: number; maintenance: number }
  services: { up: number; down: number }
  alerts: { firing: number; snoozed: number; acknowledged: number }
  ssl_domains: { expiring: number; expired: number }
}

export interface DashboardData {
  summary: DashboardSummary
  servers: DashboardServer[]
}

export interface RecentAlert {
  id: string
  server_name: string
  severity: string
  message: string
  state: string
  sent_at: string | null
}

// ── Settings (Phase 10) ──────────────────────────────────────────────────────
export interface Session {
  jti: string
  is_current: boolean
  ip_address: string | null
  user_agent: string | null
  issued_at: string
  expires_at: string
}

export interface OrgAssignment {
  org_id: string
  org_name: string
  role: 'operator' | 'viewer'
}

export interface TeamMember {
  id: string
  username: string
  role: 'admin' | 'member'
  created_at: string
  org_assignments: OrgAssignment[]
}

export interface PendingInvite {
  id: string
  email: string
  org_id: string
  org_name: string
  role: 'operator' | 'viewer'
  expires_at: string
}

export interface RotationServer {
  server_id: string
  server_name: string
  status: 'pending' | 'deploying' | 'ok' | 'error'
  message: string
}

// --- Server Detail metrics (Phase 2) ---------------------------------------

export type MetricRange = '1h' | '6h' | '24h' | '7d' | '30d'

export interface MetricSeriesPoint {
  time: string
  value: number | null
}

export interface MetricSeries {
  metric_name: string
  labels: Record<string, string>
  data: MetricSeriesPoint[]
}

export interface MetricsResponse {
  range: MetricRange
  resolution: string
  series: MetricSeries[]
}

/** A single-valued latest reading (gauge metrics with no per-label split). */
export interface LatestScalar {
  value: number | null
  time: string
}

/** A per-label latest reading (disk per path, net per interface, etc.). */
export interface LatestLabeled {
  value: number | null
  labels: Record<string, string>
  time: string
}

/** GET /metrics/latest → map of metric_name → scalar or array of labeled. */
export type LatestValues = Record<string, LatestScalar | LatestLabeled[]>

export interface MaintenanceState {
  active: boolean
  reason?: string | null
  starts_at?: string
  ends_at?: string | null
}

export interface StartMaintenancePayload {
  reason?: string | null
  ends_at?: string | null
}

// --- Processes (live snapshot, no history) ---------------------------------

export interface ProcessRow { pid: number; user?: string; name: string; cpu_pct: number; mem_pct: number }
export interface ProcessSnapshot { reachable: boolean; collected_at: string | null; processes: ProcessRow[]; top_cpu: ProcessRow[]; top_mem: ProcessRow[] }
