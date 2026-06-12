import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/services/api'

export interface Fail2banStatus {
  running: boolean
  jail_count: number
  currently_banned: number
  bans_today: number
  last_checked: string | null
}

export interface Fail2banJail {
  jail_name: string
  currently_banned: number
  total_banned: number
  currently_failed: number
  checked_at: string
}

export interface Fail2banBannedIp {
  ip: string
  jail: string
  banned_since: string | null
  checked_at: string
  country_code: string | null
  country_name: string | null
  isp: string | null
}

export interface Fail2banBannedIpsResponse {
  total: number
  page: number
  per_page: number
  items: Fail2banBannedIp[]
}

export interface Fail2banEvent {
  hour: string
  ban_count: number
}

export interface Fail2banCountry {
  country_code: string
  country_name: string
  count: number
}

export const useFail2banStore = defineStore('fail2ban', () => {
  const status = ref<Fail2banStatus | null>(null)
  const jails = ref<Fail2banJail[]>([])
  const bannedIps = ref<Fail2banBannedIpsResponse | null>(null)
  const events = ref<Fail2banEvent[]>([])
  const topCountries = ref<Fail2banCountry[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchAll(serverId: string) {
    loading.value = true
    error.value = null
    try {
      const [s, j, b, e, c] = await Promise.all([
        api.get(`/api/servers/${serverId}/fail2ban/status`).then(r => r.data),
        api.get(`/api/servers/${serverId}/fail2ban/jails`).then(r => r.data),
        api.get(`/api/servers/${serverId}/fail2ban/banned-ips`).then(r => r.data),
        api.get(`/api/servers/${serverId}/fail2ban/events`).then(r => r.data),
        api.get(`/api/servers/${serverId}/fail2ban/top-countries`).then(r => r.data),
      ])
      status.value = s
      jails.value = j
      bannedIps.value = b
      events.value = e
      topCountries.value = c
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } }
      error.value = e?.response?.data?.detail || 'Failed to load fail2ban data'
    } finally {
      loading.value = false
    }
  }

  async function fetchBannedIps(serverId: string, page = 1) {
    const r = await api.get(`/api/servers/${serverId}/fail2ban/banned-ips?page=${page}`)
    bannedIps.value = r.data
  }

  return {
    status, jails, bannedIps, events, topCountries, loading, error,
    fetchAll, fetchBannedIps,
  }
})
