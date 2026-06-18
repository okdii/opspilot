import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/services/api'

export interface SecurityActionRow {
  id: number
  alert_id: string | null
  action_type: string
  target: string | null
  tier: number
  status: 'pending_approval' | 'executed' | 'failed' | 'rejected' | 'reverted' | 'expired'
  actor: string
  confidence: string | null
  detail: string | null
  created_at: string
  executed_at: string | null
  reverted_at: string | null
  reversible: boolean
}

export interface AutoResponseSettings {
  auto_response_enabled: boolean
  block_ttl_hours: number
}

export interface SecuritySummary {
  active_events: number
  pending_approvals: number
  blocked_ips: number
}

export const PAGE_SIZE = 50

export const useSecurityActionsStore = defineStore('securityActions', () => {
  const actions = ref<SecurityActionRow[]>([])   // current ledger page (newest-first)
  const total = ref(0)
  const page = ref(0)
  const pending = ref<SecurityActionRow[]>([])    // all pending_approval rows (banner)
  const summary = ref<SecuritySummary>({ active_events: 0, pending_approvals: 0, blocked_ips: 0 })
  const settings = ref<AutoResponseSettings | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  function _err(err: unknown, fallback: string) {
    const e = err as { response?: { data?: { detail?: { message?: string } | string } } }
    const d = e?.response?.data?.detail
    error.value = (typeof d === 'object' ? d?.message : d) || fallback
  }

  async function fetchActions(serverId: string, p = page.value) {
    loading.value = true; error.value = null
    try {
      const r = await api.get(`/api/servers/${serverId}/security/actions`, {
        params: { limit: PAGE_SIZE, offset: p * PAGE_SIZE },
      })
      actions.value = r.data.items
      total.value = r.data.total
      page.value = p
    } catch (e) { _err(e, 'Failed to load response actions') }
    finally { loading.value = false }
  }

  // All pending actions for the approval banner — independent of the ledger page,
  // so a pending item never hides on a later page. Pending is rare, so 100 covers it.
  async function fetchPending(serverId: string) {
    try {
      pending.value = (await api.get(`/api/servers/${serverId}/security/actions`, {
        params: { status: 'pending_approval', limit: 100 },
      })).data.items
    } catch (e) { _err(e, 'Failed to load pending actions') }
  }

  async function fetchSummary(serverId: string) {
    try {
      summary.value = (await api.get(`/api/servers/${serverId}/security/summary`)).data
    } catch (e) { _err(e, 'Failed to load security summary') }
  }

  // Refresh what a mutation changes within this store: the approval banner and the
  // status-bar counts. The merged incident timeline (security store) is refetched by
  // the component, since the attack→mitigation grouping lives there.
  async function refresh(serverId: string) {
    await Promise.all([fetchPending(serverId), fetchSummary(serverId)])
  }

  async function fetchSettings(serverId: string) {
    settings.value = null  // clear stale data from previous server immediately
    try {
      settings.value = (await api.get(`/api/servers/${serverId}/security/auto-response`)).data
    } catch (e) { _err(e, 'Failed to load auto-response settings') }
  }

  async function updateSettings(serverId: string, body: AutoResponseSettings) {
    settings.value = (await api.put(`/api/servers/${serverId}/security/auto-response`, body)).data
  }

  async function approve(serverId: string, id: number) {
    await api.post(`/api/servers/${serverId}/security/actions/${id}/approve`)
    await refresh(serverId)
  }
  async function reject(serverId: string, id: number) {
    await api.post(`/api/servers/${serverId}/security/actions/${id}/reject`)
    await refresh(serverId)
  }
  async function undo(serverId: string, id: number) {
    await api.post(`/api/servers/${serverId}/security/actions/${id}/undo`)
    await refresh(serverId)
  }

  return { actions, total, page, pageSize: PAGE_SIZE, pending, summary,
           settings, loading, error,
           fetchActions, fetchPending, fetchSummary, refresh,
           fetchSettings, updateSettings, approve, reject, undo }
})
