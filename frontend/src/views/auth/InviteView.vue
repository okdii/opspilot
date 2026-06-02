<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { api, getApiError } from '@/services/api'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

type Mode = 'loading' | 'valid' | 'invalid' | 'expired' | 'used'
const mode = ref<Mode>('loading')
const role = ref<string>('')
const email = ref<string>('')
const errorTitle = ref('')
const errorBody = ref('')

const username = ref('')
const password = ref('')
const confirmPassword = ref('')
const showPassword = ref(false)
const showConfirm = ref(false)
const loading = ref(false)
const errors = ref<Record<string, string>>({})
const banner = ref('')

const token = computed(() => String(route.params.token))

onMounted(async () => {
  try {
    const { data } = await api.get<{ email: string; role: string }>(`/api/invite/${token.value}`)
    role.value = data.role
    email.value = data.email
    mode.value = 'valid'
  } catch (err) {
    const api = getApiError(err)
    if (api?.error === 'expired') {
      mode.value = 'expired'
      errorTitle.value = 'Invite Expired'
      errorBody.value = 'This invite link has expired. Ask your admin to resend it.'
    } else if (api?.error === 'already_accepted') {
      mode.value = 'used'
      errorTitle.value = 'Invite Already Used'
      errorBody.value = 'This invite has already been used. Please log in.'
    } else {
      mode.value = 'invalid'
      errorTitle.value = 'Invalid Invite'
      errorBody.value = 'This invite link is invalid.'
    }
  }
})

function validate(): boolean {
  errors.value = {}
  const u = username.value.trim()
  if (!u) errors.value.username = 'Username is required'
  else if (u.length < 3) errors.value.username = 'Username must be at least 3 characters'
  else if (!/^[a-zA-Z0-9_]+$/.test(u)) errors.value.username = 'Username can only contain letters, numbers, and underscores'

  if (!password.value) errors.value.password = 'Password is required'
  else if (password.value.length < 8) errors.value.password = 'Password must be at least 8 characters'

  if (!confirmPassword.value) errors.value.confirm = 'Please confirm your password'
  else if (password.value !== confirmPassword.value) errors.value.confirm = 'Passwords do not match'

  return Object.keys(errors.value).length === 0
}

async function handleSubmit() {
  banner.value = ''
  if (!validate()) return
  loading.value = true
  try {
    await auth.acceptInvite(token.value, username.value.trim(), password.value)
    await router.replace('/')
  } catch (err) {
    const api = getApiError(err)
    if (api?.error === 'username_taken') errors.value.username = 'This username is already taken'
    else if (api?.error === 'expired') {
      mode.value = 'expired'
      errorTitle.value = 'Invite Expired'
      errorBody.value = 'This invite link has expired. Ask your admin to resend it.'
    } else banner.value = 'Unable to connect. Please try again.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-shell">
    <div class="brand">
      <div class="logo">⚡</div>
      <h1>OpsPilot</h1>
      <p v-if="mode === 'valid'">You've been invited to join OpsPilot</p>
      <p v-if="mode === 'valid'" class="role-tag">Role: {{ role.charAt(0).toUpperCase() + role.slice(1) }}</p>
    </div>

    <div v-if="mode === 'loading'" class="card">
      <div class="loading-state"><span class="spin"></span> Loading…</div>
    </div>

    <div v-else-if="mode !== 'valid'" class="card error-card">
      <div class="icon">⚠</div>
      <h2>{{ errorTitle }}</h2>
      <p>{{ errorBody }}</p>
      <router-link v-if="mode === 'used'" to="/login" class="primary link-btn">Go to Login</router-link>
    </div>

    <div v-else class="card">
      <h2>Create Your Account</h2>

      <div v-if="banner" class="banner danger">{{ banner }}</div>

      <form @submit.prevent="handleSubmit">
        <label>Username</label>
        <input v-model="username" type="text" autocomplete="username" placeholder="Choose a username" :class="{ invalid: errors.username }" />
        <div v-if="errors.username" class="err">{{ errors.username }}</div>

        <label>Password</label>
        <div class="pw-wrap">
          <input v-model="password" :type="showPassword ? 'text' : 'password'" autocomplete="new-password" placeholder="Min 8 characters" :class="{ invalid: errors.password }" />
          <button type="button" class="eye" @click="showPassword = !showPassword">{{ showPassword ? '🙈' : '👁' }}</button>
        </div>
        <div v-if="errors.password" class="err">{{ errors.password }}</div>

        <label>Confirm Password</label>
        <div class="pw-wrap">
          <input v-model="confirmPassword" :type="showConfirm ? 'text' : 'password'" autocomplete="new-password" placeholder="Repeat password" :class="{ invalid: errors.confirm }" />
          <button type="button" class="eye" @click="showConfirm = !showConfirm">{{ showConfirm ? '🙈' : '👁' }}</button>
        </div>
        <div v-if="errors.confirm" class="err">{{ errors.confirm }}</div>

        <button type="submit" class="primary" :disabled="loading">
          <span v-if="loading" class="spin"></span>
          <span v-else>Create Account</span>
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.auth-shell { min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 32px 16px; gap: 28px; }
.brand { text-align: center; }
.brand .logo { font-size: 40px; }
.brand h1 { font-size: 28px; margin: 6px 0 2px; color: #fff; letter-spacing: -0.5px; }
.brand p { color: var(--muted); font-size: 13px; }
.role-tag { color: var(--accent-2) !important; font-weight: 600; margin-top: 4px !important; }
.card { width: 100%; max-width: 400px; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 28px; box-shadow: 0 8px 24px rgba(0,0,0,0.3); }
.card h2 { font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-bottom: 18px; text-align: center; }
.error-card { text-align: center; padding: 36px 28px; }
.error-card .icon { font-size: 36px; margin-bottom: 14px; }
.error-card h2 { font-size: 18px; color: #fff; letter-spacing: -0.3px; text-transform: none; margin-bottom: 10px; }
.error-card p { color: var(--muted); font-size: 14px; margin-bottom: 18px; }
.link-btn { display: inline-block; text-decoration: none; padding: 10px 24px; width: auto; }
.loading-state { display: flex; align-items: center; justify-content: center; gap: 10px; padding: 30px; color: var(--muted); }
label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; margin-top: 14px; }
input { width: 100%; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; color: var(--text); font-size: 14px; outline: none; transition: border-color 0.15s; }
input:focus { border-color: var(--accent); }
input.invalid { border-color: var(--red); }
.pw-wrap { position: relative; }
.pw-wrap input { padding-right: 40px; }
.eye { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); background: none; border: none; color: var(--muted); cursor: pointer; font-size: 16px; padding: 4px; }
.err { color: var(--red); font-size: 12px; margin-top: 6px; }
.banner { padding: 10px 14px; border-radius: 8px; font-size: 13px; margin-bottom: 14px; }
.banner.danger { background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239,68,68,0.4); color: #fecaca; }
.primary { width: 100%; margin-top: 22px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); border: none; color: #fff; padding: 12px; border-radius: 8px; font-weight: 600; font-size: 14px; cursor: pointer; display: flex; align-items: center; justify-content: center; min-height: 44px; }
.primary:disabled { opacity: 0.6; cursor: wait; }
.spin { width: 18px; height: 18px; border: 2px solid rgba(255,255,255,0.4); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
