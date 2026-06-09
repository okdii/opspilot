<script setup lang="ts">
import { ref, computed } from 'vue'
import { useNotify } from '@/composables/useNotify'

const props = defineProps<{
  serverName: string
  canEdit: boolean
  dbType?: 'mysql' | 'postgres'
}>()
const emit = defineEmits<{ (e: 'setup'): void }>()

const notify = useNotify()

function generatePassword(): string {
  const upper = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
  const lower = 'abcdefghijklmnopqrstuvwxyz'
  const digits = '0123456789'
  const special = '!@#$%^&*()-_=+'
  const all = upper + lower + digits + special
  const arr = new Uint32Array(20)
  crypto.getRandomValues(arr)
  // Ensure at least one of each character class
  const required = [
    upper[arr[0] % upper.length],
    lower[arr[1] % lower.length],
    digits[arr[2] % digits.length],
    special[arr[3] % special.length],
  ]
  const rest = Array.from(arr.slice(4), n => all[n % all.length])
  const combined = [...required, ...rest]
  // Fisher-Yates shuffle
  const swapArr = new Uint32Array(combined.length)
  crypto.getRandomValues(swapArr)
  for (let i = combined.length - 1; i > 0; i--) {
    const j = swapArr[i] % (i + 1)
    ;[combined[i], combined[j]] = [combined[j], combined[i]]
  }
  return combined.join('')
}

const password = ref(generatePassword())

function regenerate() {
  password.value = generatePassword()
}

const setupSql = computed(() =>
  props.dbType === 'postgres'
    ? `CREATE USER opspilot WITH PASSWORD '${password.value}';\nGRANT pg_monitor TO opspilot;`
    : `CREATE USER 'opspilot_monitor'@'127.0.0.1' IDENTIFIED BY '${password.value}';\nGRANT PROCESS, REPLICATION CLIENT, SLAVE MONITOR,\n  SELECT ON *.* TO 'opspilot_monitor'@'127.0.0.1';\nFLUSH PRIVILEGES;`
)

const dbLabel = computed(() => props.dbType === 'postgres' ? 'PostgreSQL' : 'MariaDB')

const copied = ref(false)
async function copySql() {
  try {
    await navigator.clipboard.writeText(setupSql.value)
    copied.value = true
    notify.success('SQL copied to clipboard')
    setTimeout(() => (copied.value = false), 2000)
  } catch {
    notify.error('Could not copy — select the SQL manually.')
  }
}
</script>

<template>
  <div class="no-creds">
    <div class="nc-icon" aria-hidden="true">
      <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
        <ellipse cx="12" cy="5" rx="9" ry="3" />
        <path d="M3 5v6c0 1.66 4 3 9 3s9-1.34 9-3V5" />
        <path d="M3 11v6c0 1.66 4 3 9 3s9-1.34 9-3v-6" />
      </svg>
    </div>

    <h2 class="nc-title">{{ dbLabel }} monitoring is not configured for {{ serverName }}</h2>
    <p class="nc-msg">
      To enable deep database metrics, create a read-only {{ dbLabel }} monitoring user on this
      server, then enter the credentials in OpsPilot.
    </p>

    <div class="nc-step">
      <span class="step-label">Step 1 — Run on {{ serverName }}</span>
      <div class="sql-card">
        <pre class="sql"><code>{{ setupSql }}</code></pre>
        <div class="sql-actions">
          <button class="copy-btn" type="button" @click="copySql">
            {{ copied ? 'Copied' : 'Copy SQL' }}
          </button>
          <button class="regen-btn" type="button" @click="regenerate" title="Generate a new password">
            ↻
          </button>
        </div>
      </div>
    </div>

    <div class="nc-step">
      <span class="step-label">Step 2 — Enter credentials in OpsPilot</span>
      <button v-if="props.canEdit" class="setup-btn" type="button" @click="emit('setup')">
        Set Up DB Monitoring for {{ serverName }}
      </button>
      <p v-else class="admin-only">Only an administrator can configure DB monitoring.</p>
    </div>
  </div>
</template>

<style scoped>
.no-creds {
  max-width: 620px; margin: 0 auto; padding: 40px 20px 60px; text-align: center;
}
.nc-icon { color: var(--muted); display: flex; justify-content: center; margin-bottom: 14px; }
.nc-title { font-size: 18px; color: #fff; margin-bottom: 8px; }
.nc-msg { color: var(--muted); font-size: 13px; line-height: 1.6; margin-bottom: 28px; }
.nc-step { text-align: left; margin-bottom: 24px; }
.step-label {
  display: block; font-size: 12px; color: var(--accent-2); font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 8px;
}
.sql-card {
  position: relative; background: #0d0f17; border: 1px solid var(--border); border-radius: 10px;
  padding: 16px 16px 14px;
}
.sql {
  margin: 0; font-family: 'SFMono-Regular', ui-monospace, Menlo, Consolas, monospace;
  font-size: 12.5px; line-height: 1.6; color: #c7d2fe; white-space: pre-wrap; word-break: break-word;
}
.sql-actions {
  position: absolute; top: 10px; right: 10px; display: flex; gap: 6px; align-items: center;
}
.copy-btn {
  background: var(--surface-2); border: 1px solid var(--border); color: var(--text);
  font-size: 11px; padding: 5px 10px; border-radius: 6px; cursor: pointer; min-height: 28px;
}
.copy-btn:hover { border-color: var(--accent); color: var(--accent-2); }
.regen-btn {
  background: var(--surface-2); border: 1px solid var(--border); color: var(--muted);
  font-size: 14px; padding: 0 8px; border-radius: 6px; cursor: pointer; min-height: 28px; line-height: 1;
}
.regen-btn:hover { border-color: var(--accent); color: var(--accent-2); }
.setup-btn {
  background: var(--accent); color: #fff; border: none; border-radius: 8px;
  font-size: 13px; font-weight: 600; padding: 11px 18px; cursor: pointer; min-height: 44px;
}
.setup-btn:hover { opacity: 0.92; }
.admin-only { color: var(--muted); font-size: 12px; font-style: italic; }
</style>
