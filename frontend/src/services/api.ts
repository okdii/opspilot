import axios, { AxiosError } from 'axios'
import type { ApiError } from '@/types'

export const api = axios.create({
  baseURL: '/',
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

// Global 401 interceptor → redirect to login
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ detail?: ApiError }>) => {
    if (error.response?.status === 401) {
      const path = window.location.pathname
      const isAuthRoute =
        path === '/login' ||
        path === '/setup' ||
        path.startsWith('/invite/')
      if (!isAuthRoute) {
        // Lazy import to avoid circular dep
        import('@/stores/auth').then(({ useAuthStore }) => {
          useAuthStore().clearLocal()
        })
        window.location.href = '/login?reason=expired'
      }
    }
    return Promise.reject(error)
  },
)

export function getApiError(err: unknown): ApiError | null {
  if (axios.isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: ApiError } | undefined)?.detail
    if (detail && typeof detail === 'object') return detail
  }
  return null
}
