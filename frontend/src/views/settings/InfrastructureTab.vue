<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useNotify } from '@/composables/useNotify'
import { getApiError } from '@/services/api'
import type { RotationServer } from '@/types'

const settings = useSettingsStore()
const notify = useNotify()

const newPassword = ref('')
const confirmPassword = ref('')
const errors = ref<Record<string, string>>({})
const submitting = ref(false)
const showConfirm = ref(false)
const showEnvVars = ref(false)

const rotationId = ref<string | null>(null)
const servers = ref<RotationServer[]>([])
const rotationDone = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

const okCount = computed(() => servers.value.filter((s) => s.status === 'ok').length)

function validate(): boolean {
  errors.value = {}
  if (newPassword.value.length < 16) errors.value.next = 'Password must be at least 16 characters'
  else if (/\s/.test(newPassword.value)) errors.value.next = 'Password must not contain spaces'
  if (newPassword.value !== confirmPassword.value) errors.value.confirm = 'Passwords do not match'
  return Object.keys(errors.value).length === 0
}

function askConfirm() {
  if (!validate()) return
  showConfirm.value = true
}

async function startRotation() {
  showConfirm.value = false
  submitting.value = true
  stopPolling()
  servers.value = []
  rotationDone.value = false
  try {
    const { rotation_id } = await settings.rotateWriterPassword({ new_password: newPassword.value })
    rotationId.value = rotation_id
    newPassword.value = ''
    confirmPassword.value = ''
    await poll()
    pollTimer = setInterval(poll, 2000)
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to start rotation.')
  } finally {
    submitting.value = false
  }
}

async function poll() {
  if (!rotationId.value) return
  try {
    const res = await settings.pollRotation(rotationId.value)
    servers.value = res.servers
    rotationDone.value = res.done
    if (res.done) {
      stopPolling()
      notify.success(`Rotation complete. ${okCount.value} of ${servers.value.length} servers updated.`)
    }
  } catch (err) {
    stopPolling()
    notify.error(getApiError(err) ?? 'Lost track of the rotation.')
  }
}

async function retry(serverId: string) {
  if (!rotationId.value) return
  try {
    await settings.retryRotationServer(rotationId.value, serverId)
    rotationDone.value = false
    await poll()
    if (!pollTimer) pollTimer = setInterval(poll, 2000)
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to retry.')
  }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onUnmounted(stopPolling)
</script>

<template>
  <div class="infra">
    <section class="card">
      <h2>Agent Database Password Rotation</h2>
      <p class="desc">
        The <code>opspilot_writer</code> PostgreSQL user backs the metrics/logs agents.
        Rotating updates the PostgreSQL user, re-deploys agent configs to all servers, and
        restarts the agents.
      </p>
      <div class="banner amber">
        ⚠ There will be a brief data gap (~5–30s per server) during agent restart. No data is
        lost — gaps appear as missing points in time-series charts.
      </div>

      <div class="field">
        <label>New Password</label>
        <input v-model="newPassword" type="password" autocomplete="new-password" placeholder="Min 16 characters, no spaces" :class="{ invalid: errors.next }" />
        <div v-if="errors.next" class="err">{{ errors.next }}</div>
      </div>
      <div class="field">
        <label>Confirm Password</label>
        <input v-model="confirmPassword" type="password" autocomplete="new-password" :class="{ invalid: errors.confirm }" />
        <div v-if="errors.confirm" class="err">{{ errors.confirm }}</div>
      </div>

      <button class="primary" :disabled="submitting" @click="askConfirm">
        <span v-if="submitting" class="spin"></span><span v-else>Rotate Password</span>
      </button>

      <!-- Progress panel -->
      <div v-if="servers.length" class="progress">
        <div class="progress-hd">
          <span v-if="!rotationDone">Rotation in progress…</span>
          <span v-else>Rotation complete. {{ okCount }} of {{ servers.length }} servers updated.</span>
        </div>
        <div v-for="s in servers" :key="s.server_id" class="prow">
          <span class="status" :class="s.status">
            <span v-if="s.status === 'ok'" class="ico">✓</span>
            <span v-else-if="s.status === 'error'" class="ico">✕</span>
            <span v-else-if="s.status === 'deploying'" class="spin sm"></span>
            <span v-else class="ico dot">○</span>
          </span>
          <span class="sname">{{ s.server_name }}</span>
          <span class="smsg" :class="{ err: s.status === 'error' }">{{ s.message }}</span>
          <button v-if="s.status === 'error'" class="retry" @click="retry(s.server_id)">Retry →</button>
        </div>
      </div>
    </section>

    <section class="card">
      <button class="collapse" @click="showEnvVars = !showEnvVars">
        <span class="caret" :class="{ open: showEnvVars }">▸</span> Environment Variables
      </button>
      <div v-if="showEnvVars" class="envvars">
        <p><code>OPSPILOT_ENCRYPTION_KEY</code> — AES-256 key for encrypting stored credentials.</p>
        <p><code>OPSPILOT_JWT_SECRET</code> — Signs JWT tokens.</p>
        <p><code>DATABASE_URL</code> — PostgreSQL connection string.</p>
        <p><code>OPSPILOT_WRITER_PASSWORD</code> — Initial writer password (used by Alembic on first migration; the Settings value takes over after rotation).</p>
        <p class="note">These are set at deployment time in your .env / Docker environment. They cannot be changed from this UI.</p>
      </div>
    </section>

    <!-- Confirm modal -->
    <div v-if="showConfirm" class="modal-overlay" @click.self="showConfirm = false">
      <div class="modal">
        <div class="modal-hdr"><h2>Confirm Rotation</h2><button class="x" @click="showConfirm = false">✕</button></div>
        <div class="modal-body">
          This will restart Telegraf and Fluent Bit on all active servers. Each server will have a
          brief data gap. Proceed?
        </div>
        <div class="modal-ftr">
          <button class="ghost" @click="showConfirm = false">Cancel</button>
          <button class="primary" @click="startRotation">Rotate Password</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.infra { display: flex; flex-direction: column; gap: 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 22px; max-width: 640px; }
.card h2 { font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-bottom: 14px; }
.desc { color: var(--muted); font-size: 13px; line-height: 1.6; margin-bottom: 16px; }
.desc code, .envvars code { background: var(--surface-2); padding: 1px 6px; border-radius: 4px; color: var(--accent-2); font-size: 12px; }
.banner { padding: 11px 14px; border-radius: 8px; font-size: 13px; line-height: 1.5; margin-bottom: 20px; }
.banner.amber { background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.4); color: #fcd34d; }
.field { margin-bottom: 16px; max-width: 380px; }
label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; }
input { width: 100%; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; color: var(--text); font-size: 14px; outline: none; }
input:focus { border-color: var(--accent); }
input.invalid { border-color: var(--red); }
.err { color: var(--red); font-size: 12px; margin-top: 6px; }
.primary { background: linear-gradient(90deg, var(--accent), var(--accent-2)); border: none; color: #fff; padding: 11px 24px; border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; min-height: 42px; min-width: 160px; }
.primary:disabled { opacity: 0.6; cursor: wait; }

.progress { margin-top: 22px; border: 1px solid var(--border); border-radius: 10px; padding: 16px; background: var(--surface-2); }
.progress-hd { font-size: 13px; color: var(--text); font-weight: 600; margin-bottom: 12px; }
.prow { display: flex; align-items: center; gap: 12px; padding: 7px 0; font-size: 13px; }
.status { width: 18px; display: flex; justify-content: center; }
.status.ok .ico { color: var(--green, #22c55e); }
.status.error .ico { color: var(--red); }
.ico { font-size: 13px; font-weight: 700; }
.ico.dot { color: var(--muted); }
.sname { min-width: 130px; color: var(--text); }
.smsg { color: var(--muted); }
.smsg.err { color: #fca5a5; }
.retry { margin-left: auto; background: none; border: 1px solid var(--border); color: var(--accent-2); border-radius: 6px; padding: 4px 10px; font-size: 12px; cursor: pointer; }
.retry:hover { border-color: var(--accent); }

.collapse { background: none; border: none; color: var(--text); font-size: 13px; font-weight: 500; cursor: pointer; display: flex; align-items: center; gap: 8px; padding: 0; }
.caret { display: inline-block; transition: transform 0.15s; color: var(--muted); }
.caret.open { transform: rotate(90deg); }
.envvars { margin-top: 14px; display: flex; flex-direction: column; gap: 8px; }
.envvars p { color: var(--muted); font-size: 13px; line-height: 1.5; }
.envvars .note { margin-top: 6px; font-style: italic; }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 20px; }
.modal { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; width: 100%; max-width: 440px; }
.modal-hdr { padding: 18px 22px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
.modal-hdr h2 { font-size: 15px; color: #fff; }
.x { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 14px; }
.modal-body { padding: 20px 22px; color: var(--text); font-size: 14px; line-height: 1.6; }
.modal-ftr { padding: 16px 22px; border-top: 1px solid var(--border); display: flex; justify-content: flex-end; gap: 10px; }
.ghost { background: var(--surface-2); border: 1px solid var(--border); color: var(--text); padding: 10px 18px; border-radius: 8px; font-size: 13px; cursor: pointer; }
.spin { width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.4); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; }
.spin.sm { width: 13px; height: 13px; border-width: 2px; border-color: rgba(99,102,241,0.3); border-top-color: var(--accent-2); }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
