import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/services/api'

export interface SecurityEvent {
  id: string
  type: string
  stage: string
  severity: 'critical' | 'warning'
  message: string
  state: string
  at: string
}

export const useSecurityStore = defineStore('security', () => {
  const events = ref<SecurityEvent[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchEvents(serverId: string) {
    loading.value = true
    error.value = null
    try {
      const r = await api.get(`/api/servers/${serverId}/security/events`)
      events.value = r.data
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } }
      error.value = e?.response?.data?.detail || 'Failed to load security events'
    } finally {
      loading.value = false
    }
  }

  return { events, loading, error, fetchEvents }
})
