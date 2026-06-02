<script setup lang="ts">
import { computed, ref, watch, onUnmounted, nextTick } from 'vue'
import { useOnboardingStore, ONBOARDING_STEPS, TOTAL_STEPS } from '@/stores/onboarding'
import type { Server } from '@/types'

const props = defineProps<{ server: Server }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'retry'): void
  (e: 'edit'): void
  (e: 'delete'): void
  (e: 'view-dashboard'): void
}>()

const onboarding = useOnboardingStore()
const state = computed(() => onboarding.ensure(props.server.id))

const sshExpanded = ref(false)
const sshBox = ref<HTMLElement | null>(null)

// Step-specific fix hints (spec 03 §7), shown beneath a failed step's error.
const HINTS: Record<string, string> = {
  ssh_connect:
    'Check the IP/port and SSH credentials. The user needs passwordless sudo (NOPASSWD). Use Edit Server to fix credentials, then retry.',
  detect_os: 'Only Ubuntu 20.04+, Debian 10+, and RHEL/CentOS 7+ are supported.',
  add_repos:
    'Ensure the server has outbound internet access to repos.influxdata.com and packages.fluentbit.io.',
  install_telegraf:
    'Package not found — likely a repo configuration issue. Check the SSH output below for details.',
  install_fluent_bit:
    'Package not found — likely a repo configuration issue. Check the SSH output below for details.',
  configure_telegraf: 'Could not write the Telegraf config. Check the SSH output for details.',
  configure_fluent_bit: 'Could not write the Fluent Bit config. Check the SSH output for details.',
  start_services: 'Failed to start services. Check the SSH output for systemd error details.',
  verify_data_flow:
    'No metrics received within 30s. The server may still come online shortly — or verify Telegraf is running: sudo systemctl status telegraf',
}

const steps = computed(() =>
  ONBOARDING_STEPS.map((meta, i) => {
    const live = state.value.steps[meta.id]
    return {
      id: meta.id,
      label: meta.label,
      number: i + 1,
      status: live?.status ?? 'pending',
      message: live?.message ?? '',
      duration_ms: live?.duration_ms ?? null,
    }
  }),
)

const failedStepNumber = computed(() => {
  if (!state.value.failedStep) return null
  return ONBOARDING_STEPS.findIndex((s) => s.id === state.value.failedStep) + 1
})
const failedStepLabel = computed(
  () => ONBOARDING_STEPS.find((s) => s.id === state.value.failedStep)?.label ?? '',
)

// ── elapsed timer for the currently-running step ──────────────────────────────
const nowTick = ref(Date.now())
let runningSince = 0
let runningId = ''
let timer: number | null = null

watch(
  () => onboarding.runningLabel(props.server.id),
  (label) => {
    const current = ONBOARDING_STEPS.find((s) => s.label === label)?.id ?? ''
    if (current && current !== runningId) {
      runningId = current
      runningSince = Date.now()
    }
    if (current && timer === null) {
      timer = window.setInterval(() => (nowTick.value = Date.now()), 1000)
    } else if (!current && timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
  },
  { immediate: true },
)
onUnmounted(() => {
  if (timer !== null) window.clearInterval(timer)
})

function elapsedFor(stepId: string): string {
  if (stepId !== runningId) return ''
  const s = Math.max(0, Math.round((nowTick.value - runningSince) / 1000))
  return `${s}s elapsed…`
}

function fmtDuration(ms: number | null): string {
  if (ms == null) return ''
  const s = ms / 1000
  return s < 10 ? `${s.toFixed(1)}s` : `${Math.round(s)}s`
}

// Auto-expand SSH output on failure; auto-scroll terminal on new output.
watch(
  () => state.value.outcome,
  (o) => {
    if (o === 'failed') sshExpanded.value = true
  },
)
watch(
  () => state.value.sshOutput,
  async () => {
    if (!sshExpanded.value) return
    await nextTick()
    if (sshBox.value) sshBox.value.scrollTop = sshBox.value.scrollHeight
  },
)
watch(sshExpanded, async (v) => {
  if (v) {
    await nextTick()
    if (sshBox.value) sshBox.value.scrollTop = sshBox.value.scrollHeight
  }
})
</script>

<template>
  <Teleport to="body">
    <div class="scrim" @click.self="emit('close')">
      <Transition name="slide" appear>
        <aside class="drawer" role="dialog" aria-label="Onboarding progress">
          <header class="d-hdr">
            <div>
              <h2>Onboarding Progress</h2>
              <p class="sub">{{ server.name }} · <span class="mono">{{ server.host }}</span></p>
            </div>
            <button class="close" aria-label="Close" @click="emit('close')">✕</button>
          </header>

          <div class="d-body">
            <!-- Step list -->
            <ol class="steps">
              <li v-for="s in steps" :key="s.id" class="step" :class="`st-${s.status}`">
                <span class="ico" aria-hidden="true">
                  <span v-if="s.status === 'done'" class="i-done">✓</span>
                  <span v-else-if="s.status === 'failed'" class="i-failed">✕</span>
                  <span v-else-if="s.status === 'skipped'" class="i-skip">—</span>
                  <span v-else-if="s.status === 'running'" class="spinner"></span>
                  <span v-else class="i-pending"></span>
                </span>
                <div class="s-main">
                  <div class="s-row">
                    <span class="s-label">{{ s.label }}</span>
                    <span class="s-meta mono">
                      <template v-if="s.status === 'done'">
                        <span v-if="s.message" class="s-note">{{ s.message }}</span>
                        <span class="s-dur">{{ fmtDuration(s.duration_ms) }}</span>
                      </template>
                      <template v-else-if="s.status === 'skipped'">
                        <span class="s-note">{{ s.message || 'skipped' }}</span>
                      </template>
                      <template v-else-if="s.status === 'running'">
                        <span class="s-elapsed">{{ elapsedFor(s.id) }}</span>
                      </template>
                      <template v-else-if="s.status === 'failed'">
                        <span class="s-failed-tag">FAILED</span>
                      </template>
                    </span>
                  </div>
                  <div v-if="s.status === 'failed'" class="s-error">
                    <p v-if="s.message" class="err-msg">{{ s.message }}</p>
                    <p v-if="HINTS[s.id]" class="err-hint">{{ HINTS[s.id] }}</p>
                  </div>
                </div>
              </li>
            </ol>

            <!-- Result banners -->
            <div v-if="state.outcome === 'success'" class="banner ok">
              <span class="b-ico">✅</span>
              <div>
                <strong>Onboarding complete — {{ server.name }} is now online!</strong>
                <span v-if="state.durationSec != null" class="b-sub">Total time: {{ state.durationSec }}s</span>
              </div>
            </div>
            <div v-else-if="state.outcome === 'failed'" class="banner fail">
              <span class="b-ico">✗</span>
              <div>
                <strong>
                  Onboarding failed<span v-if="failedStepNumber"> at step {{ failedStepNumber }}: {{ failedStepLabel }}</span>
                </strong>
              </div>
            </div>
            <div v-else-if="state.outcome === 'running'" class="banner running">
              <span class="spinner sm"></span>
              <div>
                <strong>Onboarding in progress…</strong>
                <span class="b-sub">Step {{ onboarding.currentStepNumber(server.id) }} of {{ TOTAL_STEPS }}</span>
              </div>
            </div>
          </div>

          <!-- SSH output (collapsible) -->
          <div class="ssh" :class="{ open: sshExpanded }">
            <button class="ssh-hd" @click="sshExpanded = !sshExpanded">
              <span>SSH Output</span>
              <span class="ssh-toggle">{{ sshExpanded ? 'Collapse' : 'Expand' }}</span>
            </button>
            <pre v-if="sshExpanded" ref="sshBox" class="ssh-out">{{ state.sshOutput.trim() || 'No output yet.' }}</pre>
          </div>

          <!-- Actions -->
          <footer class="d-actions">
            <template v-if="state.outcome === 'failed'">
              <button class="btn primary" @click="emit('retry')">Retry Onboarding</button>
              <button class="btn ghost" @click="emit('edit')">Edit Server</button>
              <button class="btn danger" @click="emit('delete')">Delete</button>
            </template>
            <template v-else-if="state.outcome === 'success'">
              <button class="btn primary" @click="emit('view-dashboard')">View Server Dashboard →</button>
            </template>
            <template v-else>
              <button class="btn ghost" @click="emit('close')">Close</button>
            </template>
          </footer>
        </aside>
      </Transition>
    </div>
  </Teleport>
</template>

<style scoped>
.scrim { position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 1100; display: flex; justify-content: flex-end; }
.drawer { width: 600px; max-width: 100vw; height: 100%; background: var(--surface); border-left: 1px solid var(--border); display: flex; flex-direction: column; box-shadow: -20px 0 50px rgba(0,0,0,0.4); }

.slide-enter-active, .slide-leave-active { transition: transform 0.25s ease-out; }
.slide-enter-from, .slide-leave-to { transform: translateX(100%); }

.d-hdr { padding: 18px 22px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: flex-start; flex-shrink: 0; }
.d-hdr h2 { font-size: 16px; color: #fff; }
.sub { font-size: 12px; color: var(--muted); margin-top: 4px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.close { background: none; border: none; color: var(--muted); font-size: 18px; cursor: pointer; padding: 4px; line-height: 1; }
.close:hover { color: var(--text); }

.d-body { flex: 1; overflow-y: auto; padding: 20px 22px; }

.steps { list-style: none; display: flex; flex-direction: column; gap: 2px; }
.step { display: flex; gap: 12px; padding: 9px 0; align-items: flex-start; }
.ico { flex-shrink: 0; width: 22px; height: 22px; display: flex; align-items: center; justify-content: center; margin-top: 1px; }
.i-done { color: var(--green); font-size: 14px; font-weight: 700; }
.i-failed { color: var(--red); font-size: 13px; font-weight: 700; }
.i-skip { color: var(--muted); font-size: 14px; }
.i-pending { width: 12px; height: 12px; border: 2px solid var(--border); border-radius: 50%; }
.spinner { width: 14px; height: 14px; border: 2px solid rgba(99,102,241,0.25); border-top-color: var(--accent-2); border-radius: 50%; animation: spin 0.7s linear infinite; }
.spinner.sm { width: 16px; height: 16px; }
@keyframes spin { to { transform: rotate(360deg); } }

.s-main { flex: 1; min-width: 0; }
.s-row { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }
.s-label { font-size: 13px; color: var(--text); }
.st-pending .s-label { color: var(--muted); }
.st-running .s-label { color: #fff; font-weight: 600; }
.s-meta { font-size: 11px; color: var(--muted); display: flex; gap: 10px; align-items: baseline; white-space: nowrap; }
.s-note { color: var(--muted); }
.s-dur { color: var(--muted); font-variant-numeric: tabular-nums; }
.s-elapsed { color: var(--accent-2); }
.s-failed-tag { color: var(--red); font-weight: 700; letter-spacing: 0.05em; }
.s-error { margin-top: 6px; background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.25); border-radius: 8px; padding: 10px 12px; }
.err-msg { font-size: 12px; color: #fca5a5; font-family: ui-monospace, monospace; word-break: break-word; }
.err-hint { font-size: 12px; color: var(--muted); margin-top: 6px; line-height: 1.5; }

.banner { margin-top: 18px; display: flex; gap: 12px; align-items: center; padding: 14px 16px; border-radius: 10px; }
.banner strong { display: block; font-size: 13px; color: #fff; }
.banner .b-sub { display: block; font-size: 12px; color: var(--muted); margin-top: 2px; }
.banner .b-ico { font-size: 18px; flex-shrink: 0; }
.banner.ok { background: rgba(34,197,94,0.1); border: 1px solid rgba(34,197,94,0.3); }
.banner.fail { background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3); }
.banner.fail .b-ico { color: var(--red); font-weight: 700; }
.banner.running { background: var(--surface-2); border: 1px solid var(--border); }

.ssh { border-top: 1px solid var(--border); flex-shrink: 0; }
.ssh-hd { width: 100%; display: flex; justify-content: space-between; align-items: center; padding: 12px 22px; background: none; border: none; color: var(--text); font-size: 12px; cursor: pointer; }
.ssh-hd:hover { background: var(--surface-2); }
.ssh-toggle { color: var(--accent-2); font-size: 11px; }
.ssh-out { margin: 0; max-height: 220px; overflow-y: auto; background: var(--surface-2); border-top: 1px solid var(--border); padding: 12px 22px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; line-height: 1.55; color: #cbd5e1; white-space: pre-wrap; word-break: break-word; }

.d-actions { flex-shrink: 0; border-top: 1px solid var(--border); padding: 14px 22px; display: flex; gap: 10px; flex-wrap: wrap; }
.btn { padding: 9px 16px; border-radius: 8px; font-size: 12px; font-weight: 600; cursor: pointer; border: 1px solid var(--border); background: var(--surface-2); color: var(--text); }
.btn.ghost:hover { border-color: var(--accent); color: var(--accent-2); }
.btn.primary { background: linear-gradient(90deg, var(--accent), var(--accent-2)); border: none; color: #fff; }
.btn.danger { color: #fca5a5; border-color: rgba(239,68,68,0.4); }
.btn.danger:hover { background: rgba(239,68,68,0.12); }

@media (max-width: 640px) {
  .drawer { width: 100vw; }
}
</style>
