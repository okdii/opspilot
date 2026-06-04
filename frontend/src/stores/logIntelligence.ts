import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getLogIntelligence, type LogIntelligenceData } from '@/services/api'

const DEFAULT_RANGE = '24h'

export const useLogIntelligenceStore = defineStore('logIntelligence', () => {
  const data = ref<LogIntelligenceData | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const range = ref(DEFAULT_RANGE)

  async function fetchIntelligence(orgId: string, r: string): Promise<void> {
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
    range.value = DEFAULT_RANGE
  }

  return { data, loading, error, range, fetchIntelligence, reset }
})
