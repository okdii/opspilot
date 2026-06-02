<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { getApiError } from '@/services/api'

const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const confirmPassword = ref('')
const showPassword = ref(false)
const showConfirm = ref(false)
const loading = ref(false)
const errors = ref<Record<string, string>>({})
const banner = ref('')

const passwordsMatch = computed(() => password.value === confirmPassword.value)

function validate(): boolean {
  errors.value = {}
  const u = username.value.trim()
  if (!u) errors.value.username = 'Username is required'
  else if (u.length < 3) errors.value.username = 'Username must be at least 3 characters'
  else if (!/^[a-zA-Z0-9_]+$/.test(u)) errors.value.username = 'Username can only contain letters, numbers, and underscores'

  if (!password.value) errors.value.password = 'Password is required'
  else if (password.value.length < 8) errors.value.password = 'Password must be at least 8 characters'

  if (!confirmPassword.value) errors.value.confirm = 'Please confirm your password'
  else if (!passwordsMatch.value) errors.value.confirm = 'Passwords do not match'

  return Object.keys(errors.value).length === 0
}

async function handleSubmit() {
  banner.value = ''
  if (!validate()) return
  loading.value = true
  try {
    await auth.register(username.value.trim(), password.value)
    await router.replace('/')
  } catch (err) {
    const api = getApiError(err)
    if (api?.error === 'username_taken') errors.value.username = 'This username is already taken'
    else if (api?.error === 'setup_complete') await router.replace('/login')
    else banner.value = 'Unable to connect. Please try again.'
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
      <p>Welcome — Let's get started</p>
    </div>

    <div class="card">
      <h2>Create Admin Account</h2>

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
.auth-shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 16px;
  gap: 28px;
}
.brand { text-align: center; }
.brand .logo { font-size: 40px; }
.brand h1 { font-size: 28px; margin: 6px 0 2px; color: #fff; letter-spacing: -0.5px; }
.brand p { color: var(--muted); font-size: 13px; }
.card {
  width: 100%;
  max-width: 400px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 28px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.3);
}
.card h2 {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 18px;
  text-align: center;
}
label {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 6px;
  margin-top: 14px;
}
input {
  width: 100%;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  color: var(--text);
  font-size: 14px;
  outline: none;
  transition: border-color 0.15s;
}
input:focus { border-color: var(--accent); }
input.invalid { border-color: var(--red); }
.pw-wrap { position: relative; }
.pw-wrap input { padding-right: 40px; }
.eye {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: var(--muted);
  cursor: pointer;
  font-size: 16px;
  padding: 4px;
}
.err { color: var(--red); font-size: 12px; margin-top: 6px; }
.banner {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  margin-bottom: 14px;
}
.banner.danger { background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239,68,68,0.4); color: #fecaca; }
.primary {
  width: 100%;
  margin-top: 22px;
  background: linear-gradient(90deg, var(--accent), var(--accent-2));
  border: none;
  color: #fff;
  padding: 12px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
  transition: opacity 0.15s;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 44px;
}
.primary:disabled { opacity: 0.6; cursor: wait; }
.spin {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255,255,255,0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
