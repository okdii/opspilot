import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  getActiveAlerts,
  getAlertHistory,
  getAlertFrequency,
  acknowledgeAlert as apiAck,
  snoozeAlert as apiSnooze,
} from '@/services/api'
import type {
  Alert,
  AlertHistoryFilters,
  FrequencyBucket,
  SnoozePayload,
  AlertFiredData,
  AlertResolvedData,
  AlertUpdatedData,
} from '@/types'

type AlertEvent = 'alert_fired' | 'alert_updated' | 'alert_resolved'

export const useAlertStore = defineStore('alerts', () => {
  const active = ref<Alert[]>([])
  const history = ref<Alert[]>([])
  const frequency = ref<FrequencyBucket[]>([])
  const historyCursor = ref<string | null>(null)
  const historyHasMore = ref(false)

  const loadingActive = ref(false)
  const loadingHistory = ref(false)
  const loadingFrequency = ref(false)
  const error = ref<string | null>(null)

  // Most recent alert_fired events for the toast stack (consumed by AppLayout).
  const recentFired = ref<AlertFiredData[]>([])

  const STATE_ORDER: Record<string, number> = {
    firing: 0,
    acknowledged: 1,
    snoozed: 2,
    suppressed: 3,
  }

  const firingCount = computed(() => active.value.filter((a) => a.state === 'firing').length)

  function sortActive(): void {
    active.value.sort((a, b) => {
      const so = (STATE_ORDER[a.state] ?? 99) - (STATE_ORDER[b.state] ?? 99)
      if (so !== 0) return so
      const at = a.sent_at ? new Date(a.sent_at).getTime() : 0
      const bt = b.sent_at ? new Date(b.sent_at).getTime() : 0
      return bt - at
    })
  }

  async function fetchActive(orgId: string): Promise<void> {
    loadingActive.value = true
    error.value = null
    try {
      active.value = await getActiveAlerts(orgId)
    } catch {
      error.value = 'Could not load active alerts.'
    } finally {
      loadingActive.value = false
    }
  }

  async function fetchHistory(orgId: string, filters: AlertHistoryFilters = {}, append = false): Promise<void> {
    loadingHistory.value = true
    error.value = null
    try {
      const cursor = append ? historyCursor.value : null
      const page = await getAlertHistory(orgId, filters, cursor)
      history.value = append ? [...history.value, ...page.items] : page.items
      historyCursor.value = page.next_cursor
      historyHasMore.value = page.has_more
    } catch {
      error.value = 'Could not load alert history.'
    } finally {
      loadingHistory.value = false
    }
  }

  async function fetchFrequency(orgId: string): Promise<void> {
    loadingFrequency.value = true
    try {
      frequency.value = await getAlertFrequency(orgId)
    } catch {
      frequency.value = []
    } finally {
      loadingFrequency.value = false
    }
  }

  async function acknowledge(alertId: string): Promise<Alert> {
    const updated = await apiAck(alertId)
    patchLocal(updated)
    return updated
  }

  async function snooze(alertId: string, payload: SnoozePayload): Promise<Alert> {
    const updated = await apiSnooze(alertId, payload)
    patchLocal(updated)
    return updated
  }

  function patchLocal(updated: Alert): void {
    const idx = active.value.findIndex((a) => a.id === updated.id)
    if (idx >= 0) {
      if (updated.state === 'resolved') {
        active.value.splice(idx, 1)
      } else {
        active.value[idx] = { ...active.value[idx], ...updated }
        sortActive()
      }
    }
  }

  // --- WS dispatch ---------------------------------------------------------
  function applyAlertEvent(event: AlertEvent, data: unknown): void {
    if (event === 'alert_fired') handleFired(data as AlertFiredData)
    else if (event === 'alert_updated') handleUpdated(data as AlertUpdatedData)
    else if (event === 'alert_resolved') handleResolved(data as AlertResolvedData)
  }

  function handleFired(data: AlertFiredData): void {
    const existing = active.value.find((a) => a.id === data.id)
    if (existing) {
      existing.state = 'firing'
      existing.message = data.message
      existing.sent_at = data.sent_at
    } else {
      active.value.unshift({
        id: data.id,
        type: data.type,
        severity: data.severity,
        message: data.message,
        state: data.state || 'firing',
        server_id: data.server_id,
        service_id: null,
        domain_id: null,
        ssl_cert_id: null,
        job_id: null,
        server_name: data.server_name,
        service_name: null,
        domain_name: null,
        sent_at: data.sent_at,
        acknowledged_at: null,
        snoozed_until: null,
        resolved_at: null,
      })
    }
    sortActive()
    // Push onto the toast feed (newest first, cap at 3).
    recentFired.value = [data, ...recentFired.value].slice(0, 3)
  }

  function handleUpdated(data: AlertUpdatedData): void {
    const a = active.value.find((x) => x.id === data.id)
    if (!a) return
    a.state = data.state
    a.acknowledged_at = data.acknowledged_at
    a.snoozed_until = data.snoozed_until
    sortActive()
  }

  function handleResolved(data: AlertResolvedData): void {
    const idx = active.value.findIndex((a) => a.id === data.id)
    if (idx >= 0) active.value.splice(idx, 1)
  }

  function dismissToast(id: string): void {
    recentFired.value = recentFired.value.filter((t) => t.id !== id)
  }

  function reset(): void {
    active.value = []
    history.value = []
    frequency.value = []
    historyCursor.value = null
    historyHasMore.value = false
    recentFired.value = []
    error.value = null
  }

  return {
    active,
    history,
    frequency,
    historyCursor,
    historyHasMore,
    loadingActive,
    loadingHistory,
    loadingFrequency,
    error,
    recentFired,
    firingCount,
    fetchActive,
    fetchHistory,
    fetchFrequency,
    acknowledge,
    snooze,
    applyAlertEvent,
    dismissToast,
    reset,
  }
})
