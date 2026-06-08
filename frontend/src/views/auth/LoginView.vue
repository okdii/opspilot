<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { getApiError } from '@/services/api'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const showPassword = ref(false)
const loading = ref(false)
const errors = ref<Record<string, string>>({})
const banner = ref('')
const bannerType = ref<'danger' | 'info'>('danger')

const usernameRef = ref<HTMLInputElement | null>(null)
const passwordRef = ref<HTMLInputElement | null>(null)

// Dev-only demo credentials helper (never rendered in production builds).
const isDev = import.meta.env.DEV
const demoCreds = { username: 'admin', password: 'admin123' }

function fillDemo(submit = false) {
  username.value = demoCreds.username
  password.value = demoCreds.password
  if (submit) void handleSubmit()
}

onMounted(() => {
  if (route.query.reason === 'expired') {
    banner.value = 'Your session has expired. Please sign in again.'
    bannerType.value = 'info'
  }
  usernameRef.value?.focus()
})

function validate(): boolean {
  errors.value = {}
  if (!username.value.trim()) errors.value.username = 'Username is required'
  if (!password.value.trim()) errors.value.password = 'Password is required'
  return Object.keys(errors.value).length === 0
}

async function handleSubmit() {
  banner.value = ''
  if (!validate()) return
  loading.value = true
  try {
    await auth.login(username.value.trim(), password.value.trim())
    await router.replace('/')
  } catch (err) {
    const api = getApiError(err)
    if (api?.error === 'invalid_credentials') {
      banner.value = 'Invalid username or password'
      bannerType.value = 'danger'
      password.value = ''
      await nextTick()
      passwordRef.value?.focus()
    } else if (typeof api?.error === 'string' && api.error.includes('rate_limit')) {
      banner.value = 'Too many attempts. Try again in a few minutes.'
      bannerType.value = 'danger'
    } else {
      banner.value = 'Unable to connect. Please try again.'
      bannerType.value = 'danger'
      password.value = ''
      await nextTick()
      usernameRef.value?.focus()
    }
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
      <p>Server Monitoring Dashboard</p>
    </div>

    <div class="card">
      <h2>Login</h2>

      <div v-if="banner" class="banner" :class="bannerType">{{ banner }}</div>

      <form @submit.prevent="handleSubmit">
        <label>Username</label>
        <input ref="usernameRef" v-model="username" type="text" autocomplete="username" placeholder="Enter username" :class="{ invalid: errors.username }" />
        <div v-if="errors.username" class="err">{{ errors.username }}</div>

        <label>Password</label>
        <div class="pw-wrap">
          <input ref="passwordRef" v-model="password" :type="showPassword ? 'text' : 'password'" autocomplete="current-password" placeholder="Enter password" :class="{ invalid: errors.password }" />
          <button type="button" class="eye" @click="showPassword = !showPassword">{{ showPassword ? '🙈' : '👁' }}</button>
        </div>
        <div v-if="errors.password" class="err">{{ errors.password }}</div>

        <button type="submit" class="primary" :disabled="loading">
          <span v-if="loading" class="spin"></span>
          <span v-else>Sign In</span>
        </button>
      </form>

      <div v-if="isDev" class="dev-creds">
        <div class="dev-hd">
          <span class="dev-tag">DEV</span> Demo credentials
        </div>
        <div class="dev-row">
          <code>{{ demoCreds.username }}</code>
          <span class="sep">/</span>
          <code>{{ demoCreds.password }}</code>
        </div>
        <div class="dev-actions">
          <button type="button" class="dev-btn" @click="fillDemo(false)">Fill</button>
          <button type="button" class="dev-btn primary-ghost" @click="fillDemo(true)">Fill &amp; sign in</button>
        </div>
        <p class="dev-note">Visible in dev mode only — hidden in production builds.</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-shell { min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 32px 16px; gap: 28px; }
.brand { text-align: center; }
.brand .logo { font-size: 40px; }
.brand h1 { font-size: 28px; margin: 6px 0 2px; color: #fff; letter-spacing: -0.5px; }
.brand p { color: var(--muted); font-size: 13px; }
.card { width: 100%; max-width: 400px; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 28px; box-shadow: 0 8px 24px rgba(0,0,0,0.3); }
.card h2 { font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-bottom: 18px; text-align: center; }
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
.banner.info { background: rgba(99, 102, 241, 0.15); border: 1px solid rgba(99,102,241,0.4); color: #c7d2fe; }
.primary { width: 100%; margin-top: 22px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); border: none; color: #fff; padding: 12px; border-radius: 8px; font-weight: 600; font-size: 14px; cursor: pointer; display: flex; align-items: center; justify-content: center; min-height: 44px; }
.primary:disabled { opacity: 0.6; cursor: wait; }
.spin { width: 18px; height: 18px; border: 2px solid rgba(255,255,255,0.4); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.dev-creds { margin-top: 20px; padding: 14px; border: 1px dashed var(--border); border-radius: 10px; background: rgba(255,255,255,0.02); }
.dev-hd { font-size: 11px; color: var(--muted); margin-bottom: 10px; display: flex; align-items: center; gap: 8px; letter-spacing: 0.04em; }
.dev-tag { background: rgba(245,158,11,0.15); color: #fcd34d; border: 1px solid rgba(245,158,11,0.4); border-radius: 5px; padding: 1px 6px; font-size: 10px; font-weight: 700; letter-spacing: 0.06em; }
.dev-row { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.dev-row code { background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px; padding: 5px 10px; font-size: 13px; color: var(--accent-2); user-select: all; }
.dev-row .sep { color: var(--muted); }
.dev-actions { display: flex; gap: 8px; }
.dev-btn { flex: 1; background: var(--surface-2); border: 1px solid var(--border); color: var(--text); border-radius: 8px; padding: 8px; font-size: 12px; cursor: pointer; transition: border-color 0.15s; }
.dev-btn:hover { border-color: var(--accent); }
.dev-btn.primary-ghost { color: var(--accent-2); border-color: rgba(99,102,241,0.4); }
.dev-note { color: var(--muted); font-size: 11px; margin-top: 8px; font-style: italic; }
</style>
