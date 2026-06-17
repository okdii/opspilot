import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/services/api'
import type { SecurityActionRow } from '@/stores/securityActions'

export interface SecurityEvent {
  id: string
  type: string
  stage: string
  severity: 'critical' | 'warning'
  message: string
  state: string
  at: string
}

// A detected attack plus the mitigations taken in response — one node of the
// merged incident timeline. Actions are ordered oldest-first (response chronology).
export interface Incident extends SecurityEvent {
  actions: SecurityActionRow[]
}

export interface StageBreakdown {
  stage: string
  count: number
  severity: 'critical' | 'warning' | null
}

// Incidents carry their nested actions, so each row is heavier — page smaller.
export const PAGE_SIZE = 20

export const useSecurityStore = defineStore('security', () => {
  const incidents = ref<Incident[]>([])
  const total = ref(0)
  const page = ref(0)
  const stages = ref<StageBreakdown[]>([])
  const stageFilter = ref<string | null>(null)   // active kill-chain stage, or null
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchIncidents(serverId: string, p = page.value) {
    loading.value = true
    error.value = null
    try {
      const params: Record<string, unknown> = { limit: PAGE_SIZE, offset: p * PAGE_SIZE }
      if (stageFilter.value) params.stage = stageFilter.value
      const r = await api.get(`/api/servers/${serverId}/security/incidents`, { params })
      incidents.value = r.data.items
      total.value = r.data.total
      page.value = p
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } }
      error.value = e?.response?.data?.detail || 'Failed to load incidents'
    } finally {
      loading.value = false
    }
  }

  async function fetchStages(serverId: string) {
    try {
      stages.value = (await api.get(`/api/servers/${serverId}/security/stages`)).data
    } catch {
      /* pipeline is non-critical; leave prior data on transient failure */
    }
  }

  // Toggle the stage filter (click active stage again to clear) and reload page 0.
  async function setStage(serverId: string, stage: string | null) {
    stageFilter.value = stageFilter.value === stage ? null : stage
    await fetchIncidents(serverId, 0)
  }

  return {
    incidents, total, page, pageSize: PAGE_SIZE, stages, stageFilter, loading, error,
    fetchIncidents, fetchStages, setStage,
  }
})
