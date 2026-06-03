import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import type { Organization } from '@/types'

const ACTIVE_ORG_KEY = 'opspilot.activeOrgId'
const ALL_SENTINEL = '__all__'

function readStoredOrgId(): string | null {
  const v = localStorage.getItem(ACTIVE_ORG_KEY)
  if (v === ALL_SENTINEL) return null  // "All Orgs" was explicitly chosen
  return v                              // UUID string or null (never set)
}

export const useOrgStore = defineStore('org', () => {
  const orgs = ref<Organization[]>([])
  const activeOrgId = ref<string | null>(readStoredOrgId())
  const loading = ref(false)

  const activeOrg = computed<Organization | null>(() => {
    if (!activeOrgId.value) return null
    return orgs.value.find((o) => o.id === activeOrgId.value) ?? null
  })

  const activeOrgRole = computed<'admin' | 'operator' | 'viewer' | null>(() => {
    const auth = useAuthStore()
    if (auth.isAdmin) return 'admin'
    if (!activeOrgId.value) return null
    const orgRef = auth.orgs.find((o) => o.id === activeOrgId.value)
    return orgRef?.my_role ?? null
  })

  const canEdit = computed(() => useAuthStore().isAdmin)
  const canActOnAlerts = computed(() => {
    const auth = useAuthStore()
    return auth.isAdmin || activeOrgRole.value === 'operator'
  })

  async function fetchOrgs(): Promise<void> {
    loading.value = true
    try {
      const { data } = await api.get<Organization[]>('/api/organizations')
      orgs.value = data
      // Set active org if not set or no longer accessible
      const stored = localStorage.getItem(ACTIVE_ORG_KEY)
      if (stored === null) {
        // First ever login — default to first org
        if (orgs.value.length > 0) setActiveOrg(orgs.value[0].id)
      } else if (stored !== ALL_SENTINEL && !orgs.value.find((o) => o.id === stored)) {
        // Previously selected org no longer accessible — reset to first
        if (orgs.value.length > 0) setActiveOrg(orgs.value[0].id)
      }
    } finally {
      loading.value = false
    }
  }

  function setActiveOrg(orgId: string | null): void {
    activeOrgId.value = orgId
    localStorage.setItem(ACTIVE_ORG_KEY, orgId ?? ALL_SENTINEL)
  }

  async function createOrg(payload: { name: string; slug: string; description?: string }): Promise<Organization> {
    const { data } = await api.post<Organization>('/api/organizations', payload)
    orgs.value.push(data)
    return data
  }

  async function updateOrg(id: string, payload: { name?: string; description?: string }): Promise<Organization> {
    const { data } = await api.patch<Organization>(`/api/organizations/${id}`, payload)
    const idx = orgs.value.findIndex((o) => o.id === id)
    if (idx >= 0) orgs.value[idx] = data
    return data
  }

  async function deleteOrg(id: string): Promise<void> {
    await api.delete(`/api/organizations/${id}`)
    orgs.value = orgs.value.filter((o) => o.id !== id)
    if (activeOrgId.value === id) {
      setActiveOrg(orgs.value[0]?.id ?? null)
    }
  }

  async function fetchStats(orgId: string): Promise<{ server_count: number; domain_count: number; member_count: number }> {
    const { data } = await api.get(`/api/organizations/${orgId}/stats`)
    return data
  }

  return {
    orgs,
    activeOrgId,
    activeOrg,
    activeOrgRole,
    loading,
    canEdit,
    canActOnAlerts,
    fetchOrgs,
    setActiveOrg,
    createOrg,
    updateOrg,
    deleteOrg,
    fetchStats,
  }
})
