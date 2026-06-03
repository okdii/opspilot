import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/services/api'

export interface OrgSummary {
  org: { id: string; name: string }
  servers: { total: number; online: number; offline: number }
  alerts: { total: number; firing: number }
}

export const useGlobalDashboardStore = defineStore('globalDashboard', () => {
  const orgs = ref<OrgSummary[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  const totals = computed(() => ({
    servers: orgs.value.reduce((a, o) => a + o.servers.total, 0),
    online:  orgs.value.reduce((a, o) => a + o.servers.online, 0),
    offline: orgs.value.reduce((a, o) => a + o.servers.offline, 0),
    firing:  orgs.value.reduce((a, o) => a + o.alerts.firing, 0),
  }))

  async function fetch(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const { data } = await api.get<OrgSummary[]>('/api/dashboard/global')
      orgs.value = data
    } catch (e: any) {
      error.value = e?.response?.data?.detail ?? 'Failed to load global summary'
    } finally {
      loading.value = false
    }
  }

  function reset() {
    orgs.value = []
    error.value = null
  }

  return { orgs, loading, error, totals, fetch, reset }
})
