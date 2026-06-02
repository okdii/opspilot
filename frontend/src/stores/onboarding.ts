import { defineStore } from 'pinia'
import { reactive } from 'vue'
import { api, getApiError } from '@/services/api'
import { wsClient } from '@/utils/ws'
import type { OnboardingOutcome, OnboardingResponse, OnboardingStatus } from '@/types'

// Canonical 10-step flow (spec 03 §3). Order + labels drive the UI;
// pending steps that have no log row yet are rendered from this list.
export const ONBOARDING_STEPS: { id: string; label: string }[] = [
  { id: 'ssh_connect', label: 'SSH Connection' },
  { id: 'detect_os', label: 'OS Detection' },
  { id: 'add_repos', label: 'Package Repositories' },
  { id: 'install_telegraf', label: 'Installing Telegraf' },
  { id: 'install_fluent_bit', label: 'Installing Fluent Bit' },
  { id: 'configure_telegraf', label: 'Configure Telegraf' },
  { id: 'configure_fluent_bit', label: 'Configure Fluent Bit' },
  { id: 'enable_mariadb_slowlog', label: 'MariaDB Slow Query Log' },
  { id: 'start_services', label: 'Start Services' },
  { id: 'verify_data_flow', label: 'Verify Data Flow' },
]
export const TOTAL_STEPS = ONBOARDING_STEPS.length

const STEP_INDEX: Record<string, number> = Object.fromEntries(
  ONBOARDING_STEPS.map((s, i) => [s.id, i + 1]),
)

export interface LiveStep {
  status: OnboardingStatus
  message: string
  duration_ms: number | null
}

export interface OnboardingState {
  // keyed by step id
  steps: Record<string, LiveStep>
  outcome: OnboardingOutcome
  sshOutput: string
  failedStep: string | null
  failedMessage: string | null
  durationSec: number | null
  hydrated: boolean
}

function blankState(): OnboardingState {
  const steps: Record<string, LiveStep> = {}
  for (const s of ONBOARDING_STEPS) {
    steps[s.id] = { status: 'pending', message: '', duration_ms: null }
  }
  return {
    steps,
    outcome: 'pending',
    sshOutput: '',
    failedStep: null,
    failedMessage: null,
    durationSec: null,
    hydrated: false,
  }
}

export const useOnboardingStore = defineStore('onboarding', () => {
  // reactive map: server_id -> OnboardingState
  const states = reactive<Record<string, OnboardingState>>({})

  function ensure(serverId: string): OnboardingState {
    if (!states[serverId]) states[serverId] = blankState()
    return states[serverId]
  }

  /** Re-initialise a server's state to all-pending (used on retry). */
  function reset(serverId: string): void {
    states[serverId] = blankState()
    states[serverId].outcome = 'running'
  }

  /** Load persisted onboarding log (if any) into state. */
  async function hydrate(serverId: string): Promise<void> {
    const st = ensure(serverId)
    try {
      const { data } = await api.get<OnboardingResponse>(`/api/servers/${serverId}/onboarding`)
      const fresh = blankState()
      for (const row of data.steps) {
        fresh.steps[row.step] = {
          status: row.status as OnboardingStatus,
          message: row.message ?? '',
          duration_ms: row.duration_ms,
        }
        if (row.ssh_output) {
          fresh.sshOutput += `\n$ ${ONBOARDING_STEPS.find((s) => s.id === row.step)?.label ?? row.step}\n${row.ssh_output}\n`
        }
        if (row.status === 'failed') {
          fresh.failedStep = row.step
          fresh.failedMessage = row.message ?? ''
        }
      }
      fresh.outcome = data.outcome
      fresh.hydrated = true
      states[serverId] = fresh
    } catch (err) {
      // 404 = no onboarding has run yet → keep blank state
      const apiErr = getApiError(err)
      st.hydrated = true
      if (apiErr?.error !== 'no_onboarding') {
        // network/other error — leave blank but still mark hydrated
      }
    }
  }

  /** Apply a WS message on an `onboarding:{id}` channel. */
  function applyEvent(serverId: string, event: string, data: Record<string, any>): void {
    const st = ensure(serverId)
    if (event === 'step_update') {
      const id = data.step as string
      if (!st.steps[id]) st.steps[id] = { status: 'pending', message: '', duration_ms: null }
      st.steps[id].status = data.status
      st.steps[id].message = data.message ?? ''
      st.steps[id].duration_ms = data.duration_ms ?? null
      if (data.status === 'running' && st.outcome === 'pending') st.outcome = 'running'
      if (data.status === 'failed') {
        st.failedStep = id
        st.failedMessage = data.message ?? ''
      }
    } else if (event === 'ssh_output') {
      st.sshOutput += data.chunk ?? ''
    } else if (event === 'onboarding_complete') {
      st.outcome = 'success'
      st.durationSec = data.duration_sec ?? null
    } else if (event === 'onboarding_failed') {
      st.outcome = 'failed'
      // The backend's catch-all emits step:'unknown'; prefer the real failed step
      // we already captured from step_update events.
      if (data.step && data.step !== 'unknown') st.failedStep = data.step
      if (data.message) st.failedMessage = data.message
    }
  }

  // ── WS subscription helpers ────────────────────────────────────────────────
  function subscribe(serverId: string): void {
    wsClient.send({ action: 'subscribe_onboarding', server_id: serverId })
  }
  function unsubscribe(serverId: string): void {
    wsClient.send({ action: 'unsubscribe_onboarding', server_id: serverId })
  }

  // ── Derived helpers ──────────────────────────────────────────────────────
  function currentStepNumber(serverId: string): number {
    const st = states[serverId]
    if (!st) return 0
    let n = 0
    for (const s of ONBOARDING_STEPS) {
      const status = st.steps[s.id]?.status
      if (status === 'done' || status === 'skipped') n = STEP_INDEX[s.id]
      else if (status === 'running' || status === 'failed') return STEP_INDEX[s.id]
    }
    return n
  }

  function progressPct(serverId: string): number {
    return Math.round((currentStepNumber(serverId) / TOTAL_STEPS) * 100)
  }

  function runningLabel(serverId: string): string {
    const st = states[serverId]
    if (!st) return ''
    const running = ONBOARDING_STEPS.find((s) => st.steps[s.id]?.status === 'running')
    return running?.label ?? ''
  }

  return {
    states,
    ensure,
    reset,
    hydrate,
    applyEvent,
    subscribe,
    unsubscribe,
    currentStepNumber,
    progressPct,
    runningLabel,
  }
})
