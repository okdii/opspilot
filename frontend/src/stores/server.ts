import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/services/api'
import type { Server } from '@/types'

export const useServerStore = defineStore('server', () => {
  const servers = ref<Server[]>([])
  const loading = ref(false)

  async function fetchByOrg(orgId: string): Promise<void> {
    loading.value = true
    try {
      const { data } = await api.get<Server[]>(`/api/organizations/${orgId}/servers`)
      servers.value = data
    } finally {
      loading.value = false
    }
  }

  async function fetchAll(): Promise<void> {
    loading.value = true
    try {
      const { data } = await api.get<Server[]>('/api/servers')
      servers.value = data
    } finally {
      loading.value = false
    }
  }

  async function create(orgId: string, payload: Record<string, unknown>): Promise<Server> {
    const { data } = await api.post<Server>(`/api/organizations/${orgId}/servers`, payload)
    servers.value.push(data)
    return data
  }

  async function update(id: string, payload: Record<string, unknown>): Promise<Server> {
    const { data } = await api.patch<Server>(`/api/servers/${id}`, payload)
    const idx = servers.value.findIndex((s) => s.id === id)
    if (idx >= 0) servers.value[idx] = data
    return data
  }

  async function remove(id: string): Promise<void> {
    await api.delete(`/api/servers/${id}`)
    servers.value = servers.value.filter((s) => s.id !== id)
  }

  async function redeploy(id: string): Promise<void> {
    await api.post(`/api/servers/${id}/redeploy`)
  }

  /** Start or retry the full 10-step onboarding flow. */
  async function onboard(id: string): Promise<void> {
    await api.post(`/api/servers/${id}/onboard`)
  }

  return { servers, loading, fetchByOrg, fetchAll, create, update, remove, redeploy, onboard }
})
