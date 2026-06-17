import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/services/api'
import type { SecurityEvent } from '@/stores/security'

export interface AttackerIntel {
  abuse_score: number | null
  country_code: string | null
  isp: string | null
  usage_type: string | null
  total_reports: number | null
  last_reported_at: string | null
}

export interface Attacker {
  ip: string
  event_count: number
  first_seen: string
  last_seen: string
  stages: string[]
  critical_count: number
  warning_count: number
  mitigations: number
  blocked: boolean
  last_type: string
  last_message: string
  intel: AttackerIntel | null
}

export interface TrendBucket {
  date: string
  critical: number
  warning: number
}

export type AttackerSort = 'last_seen' | 'events' | 'severity'
export const PAGE_SIZE = 20

export const useAttackersStore = defineStore('attackers', () => {
  const attackers = ref<Attacker[]>([])
  const total = ref(0)
  const page = ref(0)
  const sort = ref<AttackerSort>('last_seen')
  const trend = ref<TrendBucket[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchAttackers(serverId: string, p = page.value) {
    loading.value = true
    error.value = null
    try {
      const params = { sort: sort.value, limit: PAGE_SIZE, offset: p * PAGE_SIZE }
      const r = await api.get(`/api/servers/${serverId}/security/attackers`, { params })
      attackers.value = r.data.items
      total.value = r.data.total
      page.value = p
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } }
      error.value = e?.response?.data?.detail || 'Failed to load attackers'
    } finally {
      loading.value = false
    }
  }

  async function setSort(serverId: string, s: AttackerSort) {
    sort.value = s
    await fetchAttackers(serverId, 0)
  }

  async function fetchTrend(serverId: string, days = 30) {
    try {
      trend.value = (await api.get(`/api/servers/${serverId}/security/trend`, { params: { days } })).data
    } catch {
      /* trend is non-critical; leave prior data on transient failure */
    }
  }

  async function fetchAttackerEvents(serverId: string, ip: string, p = 0): Promise<{ items: SecurityEvent[]; total: number }> {
    const params = { limit: PAGE_SIZE, offset: p * PAGE_SIZE }
    const r = await api.get(`/api/servers/${serverId}/security/attackers/${encodeURIComponent(ip)}/events`, { params })
    return r.data
  }

  return {
    attackers, total, page, pageSize: PAGE_SIZE, sort, trend, loading, error,
    fetchAttackers, setSort, fetchTrend, fetchAttackerEvents,
  }
})
