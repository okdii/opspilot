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
  logs_supported: boolean
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

// --- Server Services (agent-discovered process metrics) ---------------------

export interface ServerServiceEntry {
  name: string
  status: 'running' | 'stopped' | 'not_installed'
  cpu_pct: number | null
  mem_mb: number | null
  uptime_seconds: number | null
  muted: boolean
}

// --- Monitoring checks (HTTP/TCP probes) ------------------------------------

export type MonitoringServiceStatus = 'up' | 'down' | 'timeout' | null
export type MonitoringServiceType = 'http' | 'tcp' | 'db'

export interface MonitoringService {
  id: string
  name: string
  type: MonitoringServiceType
  url: string | null
  port: number | null
  last_status: MonitoringServiceStatus
  uptime_24h: number | null
  avg_response_ms_24h: number | null
}

// --- Log Viewer (Phase 3, spec 05) -----------------------------------------

export type LogSource =
  | 'nginx_access' | 'nginx_error' | 'php_fpm' | 'php_app'
  | 'mariadb_error' | 'mariadb_slow' | 'syslog' | 'auth' | 'kernel'

export type LogSeverity = 'debug' | 'info' | 'warn' | 'error' | 'fatal'

export type LogTimeRange = '15m' | '1h' | '6h' | '24h' | '7d' | 'custom'

export interface LogEntry {
  id: string
  time: string
  server_id: string
  server_name: string
  source: LogSource | string
  severity: LogSeverity | null
  message: string
  fields: Record<string, unknown>
}

export interface LogsResponse {
  entries: LogEntry[]
  next_cursor: string | null
  count: number
  limit_reached: boolean
}

export interface VolumeBucket {
  time: string
  debug: number
  info: number
  warn: number
  error: number
  fatal: number
}

export interface VolumeResponse {
  buckets: VolumeBucket[]
  bucket_seconds: number
}

export interface LogFilters {
  serverIds: string[]
  sources: LogSource[]
  severities: LogSeverity[]
  search: string
  range: LogTimeRange
  from: string | null
  to: string | null
}

export interface LogSummaryBand {
  count: number
  latest: LogEntry | null
}

export interface LogSummary {
  fatal: LogSummaryBand
  error: LogSummaryBand
  warn:  LogSummaryBand
}

// --- Alerting (Phase 8, spec 10) -------------------------------------------

export type AlertSeverity = 'critical' | 'warning'
export type AlertState = 'firing' | 'acknowledged' | 'snoozed' | 'resolved' | 'suppressed'

export interface Alert {
  id: string
  type: string
  severity: AlertSeverity | string
  message: string
  state: AlertState | string
  server_id: string | null
  service_id: string | null
  domain_id: string | null
  ssl_cert_id: string | null
  job_id: string | null
  server_name: string | null
  service_name: string | null
  domain_name: string | null
  sent_at: string | null
  acknowledged_at: string | null
  snoozed_until: string | null
  resolved_at: string | null
  consecutive_clear_count?: number
}

export interface AlertHistoryPage {
  items: Alert[]
  next_cursor: string | null
  has_more: boolean
}

export interface AlertHistoryFilters {
  server_id?: string
  type?: string
  start?: string
  end?: string
  search?: string
}

export interface FrequencyBucket {
  date: string
  critical: number
  warning: number
}

export interface SnoozePayload {
  minutes?: number
  until?: string
}

export interface MetricRule {
  id: string
  server_id: string
  server_name: string | null
  metric: string
  threshold: number
  rolling_window_min: number
  cooldown_min: number
  enabled: boolean
  last_fired_at: string | null
  is_auto: boolean
}

export interface LogRule {
  id: string
  server_id: string
  server_name: string | null
  source: string
  pattern: string
  severity: AlertSeverity | string
  threshold: number
  window_sec: number
  cooldown_min: number
  enabled: boolean
  last_fired_at: string | null
}

export interface AlertRules {
  metric_rules: MetricRule[]
  log_rules: LogRule[]
}

export interface MetricRulePayload {
  server_id?: string
  metric?: string
  threshold?: number
  rolling_window_min?: number
  cooldown_min?: number
  enabled?: boolean
}

export interface LogRulePayload {
  server_id?: string
  source?: string
  pattern?: string
  severity?: string
  threshold?: number
  window_sec?: number
  cooldown_min?: number
  enabled?: boolean
}

// WS event payloads (flat {event, data} from broadcast_org)
export interface AlertFiredData {
  id: string
  type: string
  severity: string
  message: string
  server_id: string | null
  server_name: string | null
  sent_at: string | null
  state: string
}

export interface AlertResolvedData {
  id: string
  state: string
  resolved_at: string | null
}

export interface AlertUpdatedData {
  id: string
  state: string
  acknowledged_at: string | null
  snoozed_until: string | null
}
