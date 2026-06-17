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

export const PAGE_SIZE = 50

export const useSecurityStore = defineStore('security', () => {
  const events = ref<SecurityEvent[]>([])
  const total = ref(0)
  const page = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchEvents(serverId: string, p = page.value) {
    loading.value = true
    error.value = null
    try {
      const r = await api.get(`/api/servers/${serverId}/security/events`, {
        params: { limit: PAGE_SIZE, offset: p * PAGE_SIZE },
      })
      events.value = r.data.items
      total.value = r.data.total
      page.value = p
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } }
      error.value = e?.response?.data?.detail || 'Failed to load security events'
    } finally {
      loading.value = false
    }
  }

  return { events, total, page, pageSize: PAGE_SIZE, loading, error, fetchEvents }
})
