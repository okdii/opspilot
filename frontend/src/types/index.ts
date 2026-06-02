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
