import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/services/api'
import type { UptimePoint } from '@/stores/services'

// ── Types (mirror the public status endpoints in routers/services.py) ─────────

export interface PublicService {
  id: string
  name: string
  last_status: string | null
  uptime_30d: number | null
  open_incident_id: string | null
  // Filled in client-side after fetching the per-service timeline.
  timeline?: UptimePoint[]
}

export interface PublicIncident {
  id: string
  service_name: string
  started_at: string | null
  resolved_at: string | null
  duration_sec: number | null
}

// These endpoints are public (no auth). The shared `api` sends withCredentials
// which is harmless here.
export const usePublicStatusStore = defineStore('publicStatus', () => {
  const services = ref<PublicService[]>([])
  const incidents = ref<PublicIncident[]>([])
  const loading = ref(false)
  const loaded = ref(false)
  const error = ref<string | null>(null)

  // Active incidents = unresolved; past = resolved (most recent first already).
  const activeIncidents = computed(() =>
    incidents.value.filter((i) => i.resolved_at == null),
  )
  const pastIncidents = computed(() =>
    incidents.value.filter((i) => i.resolved_at != null),
  )

  const allOperational = computed(
    () =>
      services.value.length > 0 &&
      services.value.every((s) => s.last_status === 'up') &&
      activeIncidents.value.length === 0,
  )

  async function fetchAll() {
    loading.value = true
    error.value = null
    try {
      const [svcRes, incRes] = await Promise.all([
        api.get<PublicService[]>('/api/public/services'),
        api.get<PublicIncident[]>('/api/public/incidents'),
      ])
      const svcs = svcRes.data
      // Fetch each service's 90-day timeline in parallel.
      await Promise.all(
        svcs.map(async (s) => {
          try {
            const { data } = await api.get<UptimePoint[]>(
              `/api/public/services/${s.id}/uptime?days=90`,
            )
            s.timeline = data
          } catch {
            s.timeline = []
          }
        }),
      )
      services.value = svcs
      incidents.value = incRes.data
      loaded.value = true
    } catch {
      error.value = 'Unable to load status.'
    } finally {
      loading.value = false
    }
  }

  return {
    services,
    incidents,
    loading,
    loaded,
    error,
    activeIncidents,
    pastIncidents,
    allOperational,
    fetchAll,
  }
})
