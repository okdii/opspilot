<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useSettingsStore } from '@/stores/settings'
import { useNotify } from '@/composables/useNotify'
import { getApiError } from '@/services/api'
import { relativeTime, relativeFuture } from '@/utils/time'
import { EmptyState } from '@/components/ui'
import type { Session } from '@/types'

const settings = useSettingsStore()
const { sessions } = storeToRefs(settings)
const notify = useNotify()

const loading = ref(false)

onMounted(load)
async function load() {
  loading.value = true
  try {
    await settings.fetchSessions()
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to load sessions.')
  } finally {
    loading.value = false
  }
}

const otherSessions = computed(() => sessions.value.filter((s) => !s.is_current))

// Best-effort "Browser · OS" from a user-agent string.
function parseUA(ua: string | null): string {
  if (!ua) return 'Unknown'
  let browser = ''
  if (/Edg\//.test(ua)) browser = 'Edge'
  else if (/OPR\/|Opera/.test(ua)) browser = 'Opera'
  else if (/Chrome\//.test(ua) && !/Chromium/.test(ua)) browser = 'Chrome'
  else if (/Firefox\//.test(ua)) browser = 'Firefox'
  else if (/Safari\//.test(ua) && /Version\//.test(ua)) browser = 'Safari'
  else if (/curl\//.test(ua)) browser = 'curl'
  let os = ''
  if (/Windows/.test(ua)) os = 'Windows'
  else if (/Macintosh|Mac OS X/.test(ua)) os = 'macOS'
  else if (/Android/.test(ua)) os = 'Android'
  else if (/iPhone|iPad|iOS/.test(ua)) os = 'iOS'
  else if (/Linux/.test(ua)) os = 'Linux'
  if (browser && os) return `${browser} · ${os}`
  if (browser) return browser
  return ua.length > 40 ? ua.slice(0, 40) + '…' : ua
}

async function revokeOne(s: Session) {
  if (!window.confirm('Sign out this device? It will be logged out on its next request.')) return
  try {
    await settings.revokeSession(s.jti)
    notify.success('Session revoked.')
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to revoke session.')
  }
}

async function revokeAllOthers() {
  if (!window.confirm('This will sign out all other devices. Continue?')) return
  try {
    await settings.revokeAllOtherSessions()
    notify.success('All other sessions have been revoked.')
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to revoke sessions.')
  }
}

// ── Change password ──────────────────────────────────────────────────────────
const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const pwLoading = ref(false)
const errors = ref<Record<string, string>>({})

function validate(): boolean {
  errors.value = {}
  if (!currentPassword.value) errors.value.current = 'Current password is required'
  if (!newPassword.value) errors.value.next = 'New password is required'
  else if (newPassword.value.length < 8) errors.value.next = 'Password must be at least 8 characters'
  if (newPassword.value !== confirmPassword.value) errors.value.confirm = 'Passwords do not match'
  return Object.keys(errors.value).length === 0
}

async function submitPassword() {
  if (!validate()) return
  pwLoading.value = true
  try {
    await settings.changePassword({ current_password: currentPassword.value, new_password: newPassword.value })
    notify.success('Password changed. All other sessions have been revoked.')
    currentPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    await settings.fetchSessions()
  } catch (err) {
    const api = getApiError(err)
    if (api?.error === 'wrong_password') errors.value.current = 'Current password is incorrect'
    else notify.error(api ?? 'Unable to change password.')
  } finally {
    pwLoading.value = false
  }
}
</script>

<template>
  <div class="security">
    <section class="card">
      <header class="card-head">
        <h2>Active Sessions</h2>
        <button v-if="otherSessions.length" class="ghost-danger" @click="revokeAllOthers">
          Revoke All Other Sessions
        </button>
      </header>

      <div v-if="loading" class="muted-row">Loading sessions…</div>

      <table v-else class="grid">
        <thead>
          <tr>
            <th>Device</th>
            <th>Browser / OS</th>
            <th>IP Address</th>
            <th>Issued</th>
            <th>Expires</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in sessions" :key="s.jti">
            <td>
              <span v-if="s.is_current" class="this-device">This device</span>
              <span v-else>Other device</span>
            </td>
            <td>{{ parseUA(s.user_agent) }}</td>
            <td class="mono">{{ s.ip_address ?? '—' }}</td>
            <td>{{ relativeTime(s.issued_at) }}</td>
            <td>{{ relativeFuture(s.expires_at) }}</td>
            <td class="right">
              <button v-if="!s.is_current" class="ghost-danger sm" @click="revokeOne(s)">Revoke</button>
            </td>
          </tr>
        </tbody>
      </table>

      <EmptyState
        v-if="!loading && otherSessions.length === 0"
        title="No other active sessions"
        message="You're only signed in on this device."
      />
    </section>

    <section class="card">
      <h2>Change Password</h2>
      <form class="pw-form" @submit.prevent="submitPassword">
        <label>Current Password</label>
        <input v-model="currentPassword" type="password" autocomplete="current-password" :class="{ invalid: errors.current }" />
        <div v-if="errors.current" class="err">{{ errors.current }}</div>

        <label>New Password</label>
        <input v-model="newPassword" type="password" autocomplete="new-password" placeholder="Min 8 characters" :class="{ invalid: errors.next }" />
        <div v-if="errors.next" class="err">{{ errors.next }}</div>

        <label>Confirm New Password</label>
        <input v-model="confirmPassword" type="password" autocomplete="new-password" :class="{ invalid: errors.confirm }" />
        <div v-if="errors.confirm" class="err">{{ errors.confirm }}</div>

        <button type="submit" class="primary" :disabled="pwLoading">
          <span v-if="pwLoading" class="spin"></span><span v-else>Update Password</span>
        </button>
      </form>
    </section>
  </div>
</template>

<style scoped>
.security { display: flex; flex-direction: column; gap: 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 22px; }
.card-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; gap: 12px; flex-wrap: wrap; }
.card h2 { font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
.card-head h2 { margin: 0; }

.grid { width: 100%; border-collapse: collapse; font-size: 13px; }
.grid th { text-align: left; color: var(--muted); font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; padding: 8px 12px; border-bottom: 1px solid var(--border); }
.grid td { padding: 11px 12px; border-bottom: 1px solid rgba(255,255,255,0.04); color: var(--text); }
.grid tr:last-child td { border-bottom: none; }
.grid .right { text-align: right; }
.mono { font-variant-numeric: tabular-nums; font-family: ui-monospace, monospace; color: var(--muted); }
.this-device { font-style: italic; color: var(--accent-2); }
.muted-row { color: var(--muted); font-size: 13px; padding: 8px 0; }

.ghost-danger { background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.35); color: #fca5a5; padding: 7px 12px; border-radius: 8px; font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.15s; }
.ghost-danger:hover { background: rgba(239,68,68,0.16); }
.ghost-danger.sm { padding: 5px 10px; font-size: 12px; }

.pw-form { max-width: 380px; }
label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; margin-top: 14px; }
.pw-form label:first-child { margin-top: 0; }
input { width: 100%; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; color: var(--text); font-size: 14px; outline: none; }
input:focus { border-color: var(--accent); }
input.invalid { border-color: var(--red); }
.err { color: var(--red); font-size: 12px; margin-top: 6px; }
.primary { margin-top: 18px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); border: none; color: #fff; padding: 11px 28px; border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; min-height: 42px; min-width: 160px; }
.primary:disabled { opacity: 0.6; cursor: wait; }
.spin { width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.4); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
