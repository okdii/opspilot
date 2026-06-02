import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/services/api'
import type { OrgRef, User } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const isAuthenticated = ref(false)
  const setupRequired = ref(false)
  const user = ref<User | null>(null)
  const initialized = ref(false)

  const isAdmin = computed(() => user.value?.role === 'admin')
  const orgs = computed<OrgRef[]>(() => user.value?.orgs ?? [])

  async function checkSetupStatus(): Promise<boolean> {
    const { data } = await api.get<{ setup_required: boolean }>('/api/setup/status')
    setupRequired.value = data.setup_required
    return data.setup_required
  }

  async function register(username: string, password: string): Promise<void> {
    await api.post('/api/setup/register', { username, password })
    setupRequired.value = false
    await fetchMe()
  }

  async function login(username: string, password: string): Promise<void> {
    await api.post('/api/auth/login', { username, password })
    await fetchMe()
  }

  async function logout(): Promise<void> {
    try {
      await api.post('/api/auth/logout')
    } catch {
      /* network errors must not block logout */
    }
    clearLocal()
  }

  async function fetchMe(): Promise<User | null> {
    try {
      const { data } = await api.get<User>('/api/auth/me')
      user.value = data
      isAuthenticated.value = true
      return data
    } catch {
      user.value = null
      isAuthenticated.value = false
      return null
    }
  }

  async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
    await api.patch('/api/auth/password', {
      current_password: currentPassword,
      new_password: newPassword,
    })
  }

  async function acceptInvite(token: string, username: string, password: string): Promise<void> {
    await api.post(`/api/invite/${token}/accept`, { username, password })
    await fetchMe()
  }

  function clearLocal(): void {
    user.value = null
    isAuthenticated.value = false
  }

  return {
    isAuthenticated,
    setupRequired,
    user,
    initialized,
    isAdmin,
    orgs,
    checkSetupStatus,
    register,
    login,
    logout,
    fetchMe,
    changePassword,
    acceptInvite,
    clearLocal,
  }
})
