<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { getApiError } from '@/services/api'

const auth = useAuthStore()
const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const banner = ref('')
const bannerType = ref<'success' | 'danger'>('success')
const errors = ref<Record<string, string>>({})

const roleLabel = computed(() => {
  if (auth.user?.role === 'admin') return 'Admin — Global Access'
  const orgs = auth.user?.orgs ?? []
  if (!orgs.length) return 'Member — no organizations assigned'
  const cap = (r: string) => r.charAt(0).toUpperCase() + r.slice(1)
  return 'Member — ' + orgs.map((o) => `${cap(o.my_role)} in ${o.name}`).join(', ')
})

const memberSince = computed(() => auth.user?.created_at?.slice(0, 10) ?? '—')

function validate(): boolean {
  errors.value = {}
  if (!currentPassword.value) errors.value.current = 'Current password is required'
  if (!newPassword.value) errors.value.next = 'New password is required'
  else if (newPassword.value.length < 8) errors.value.next = 'Password must be at least 8 characters'
  if (newPassword.value !== confirmPassword.value) errors.value.confirm = 'Passwords do not match'
  return Object.keys(errors.value).length === 0
}

async function submit() {
  banner.value = ''
  if (!validate()) return
  loading.value = true
  try {
    await auth.changePassword(currentPassword.value, newPassword.value)
    banner.value = 'Password changed. You have been signed out of all other devices.'
    bannerType.value = 'success'
    currentPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
  } catch (err) {
    const api = getApiError(err)
    if (api?.error === 'wrong_password') {
      errors.value.current = 'Current password is incorrect'
    } else {
      banner.value = 'Unable to update password'
      bannerType.value = 'danger'
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="page">
    <header class="hdr">
      <h1>My Profile</h1>
      <p>Account settings and password</p>
    </header>

    <div class="grid">
      <section class="card">
        <h2>Account</h2>
        <div class="kv"><span>Username</span><strong>{{ auth.user?.username }}</strong></div>
        <div class="kv"><span>Role</span><strong class="role">{{ roleLabel }}</strong></div>
        <div class="kv"><span>Member since</span><strong>{{ memberSince }}</strong></div>
      </section>

      <section class="card">
        <h2>Change Password</h2>
        <div v-if="banner" class="banner" :class="bannerType">{{ banner }}</div>
        <form @submit.prevent="submit">
          <label>Current Password</label>
          <input v-model="currentPassword" type="password" autocomplete="current-password" :class="{ invalid: errors.current }" />
          <div v-if="errors.current" class="err">{{ errors.current }}</div>

          <label>New Password</label>
          <input v-model="newPassword" type="password" autocomplete="new-password" placeholder="Min 8 characters" :class="{ invalid: errors.next }" />
          <div v-if="errors.next" class="err">{{ errors.next }}</div>

          <label>Confirm New Password</label>
          <input v-model="confirmPassword" type="password" autocomplete="new-password" :class="{ invalid: errors.confirm }" />
          <div v-if="errors.confirm" class="err">{{ errors.confirm }}</div>

          <button type="submit" class="primary" :disabled="loading">
            <span v-if="loading" class="spin"></span><span v-else>Update Password</span>
          </button>
        </form>
      </section>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 24px; max-width: 900px; margin: 0 auto; }
.hdr h1 { font-size: 22px; color: #fff; margin-bottom: 4px; }
.hdr p { color: var(--muted); font-size: 13px; margin-bottom: 28px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
@media (max-width: 700px) { .grid { grid-template-columns: 1fr; } }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 22px; }
.card h2 { font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-bottom: 16px; }
.kv { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.04); }
.kv:last-child { border-bottom: none; }
.kv span { color: var(--muted); font-size: 13px; flex-shrink: 0; }
.kv strong { color: var(--text); font-size: 13px; text-align: right; }
.kv strong.role { color: var(--accent-2); }
label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; margin-top: 14px; }
input { width: 100%; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; color: var(--text); font-size: 14px; outline: none; }
input:focus { border-color: var(--accent); }
input.invalid { border-color: var(--red); }
.err { color: var(--red); font-size: 12px; margin-top: 6px; }
.banner { padding: 10px 14px; border-radius: 8px; font-size: 13px; margin-bottom: 14px; }
.banner.danger { background: rgba(239,68,68,0.15); border: 1px solid rgba(239,68,68,0.4); color: #fecaca; }
.banner.success { background: rgba(34,197,94,0.15); border: 1px solid rgba(34,197,94,0.4); color: #bbf7d0; }
.primary { width: 100%; margin-top: 18px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); border: none; color: #fff; padding: 11px; border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; display: flex; align-items: center; justify-content: center; min-height: 42px; }
.primary:disabled { opacity: 0.6; cursor: wait; }
.spin { width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.4); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
