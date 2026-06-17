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

export const useSecurityActionsStore = defineStore('securityActions', () => {
  const actions = ref<SecurityActionRow[]>([])
  const settings = ref<AutoResponseSettings | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  function _err(err: unknown, fallback: string) {
    const e = err as { response?: { data?: { detail?: { message?: string } | string } } }
    const d = e?.response?.data?.detail
    error.value = (typeof d === 'object' ? d?.message : d) || fallback
  }

  async function fetchActions(serverId: string) {
    loading.value = true; error.value = null
    try {
      actions.value = (await api.get(`/api/servers/${serverId}/security/actions`)).data
    } catch (e) { _err(e, 'Failed to load response actions') }
    finally { loading.value = false }
  }

  async function fetchSettings(serverId: string) {
    try {
      settings.value = (await api.get(`/api/servers/${serverId}/security/auto-response`)).data
    } catch (e) { _err(e, 'Failed to load auto-response settings') }
  }

  async function updateSettings(serverId: string, body: AutoResponseSettings) {
    settings.value = (await api.put(`/api/servers/${serverId}/security/auto-response`, body)).data
  }

  async function approve(serverId: string, id: number) {
    await api.post(`/api/servers/${serverId}/security/actions/${id}/approve`)
    await fetchActions(serverId)
  }
  async function reject(serverId: string, id: number) {
    await api.post(`/api/servers/${serverId}/security/actions/${id}/reject`)
    await fetchActions(serverId)
  }
  async function undo(serverId: string, id: number) {
    await api.post(`/api/servers/${serverId}/security/actions/${id}/undo`)
    await fetchActions(serverId)
  }

  return { actions, settings, loading, error,
           fetchActions, fetchSettings, updateSettings, approve, reject, undo }
})
