import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getLogIntelligence, type LogIntelligenceData } from '@/services/api'

export const useLogIntelligenceStore = defineStore('logIntelligence', () => {
  const data = ref<LogIntelligenceData | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const range = ref('24h')

  async function fetch(orgId: string, r: string): Promise<void> {
    range.value = r
    loading.value = true
    error.value = null
    try {
      data.value = await getLogIntelligence(orgId, r)
    } catch {
      error.value = 'Could not load log intelligence.'
      data.value = null
    } finally {
      loading.value = false
    }
  }

  function reset(): void {
    data.value = null
    loading.value = false
    error.value = null
    range.value = '24h'
  }

  return { data, loading, error, range, fetch, reset }
})
