<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useNotify } from '@/composables/useNotify'
import { api, getApiError } from '@/services/api'

const settings = useSettingsStore()
const notify = useNotify()

// Local editable copies (so we only persist on Save).
const instanceName = ref('')
const baseUrl = ref('')
const timezone = ref('UTC')

const TIMEZONES = [
  { value: 'UTC', label: 'UTC — Coordinated Universal Time' },
  { value: 'America/New_York', label: 'America/New_York — ET (UTC-5/-4)' },
  { value: 'America/Chicago', label: 'America/Chicago — CT (UTC-6/-5)' },
  { value: 'America/Denver', label: 'America/Denver — MT (UTC-7/-6)' },
  { value: 'America/Los_Angeles', label: 'America/Los_Angeles — PT (UTC-8/-7)' },
  { value: 'America/Sao_Paulo', label: 'America/Sao_Paulo — BRT (UTC-3)' },
  { value: 'Europe/London', label: 'Europe/London — GMT/BST (UTC+0/+1)' },
  { value: 'Europe/Paris', label: 'Europe/Paris — CET (UTC+1/+2)' },
  { value: 'Europe/Berlin', label: 'Europe/Berlin — CET (UTC+1/+2)' },
  { value: 'Europe/Moscow', label: 'Europe/Moscow — MSK (UTC+3)' },
  { value: 'Asia/Dubai', label: 'Asia/Dubai — GST (UTC+4)' },
  { value: 'Asia/Kolkata', label: 'Asia/Kolkata — IST (UTC+5:30)' },
  { value: 'Asia/Dhaka', label: 'Asia/Dhaka — BST (UTC+6)' },
  { value: 'Asia/Bangkok', label: 'Asia/Bangkok — ICT (UTC+7)' },
  { value: 'Asia/Jakarta', label: 'Asia/Jakarta — WIB (UTC+7)' },
  { value: 'Asia/Singapore', label: 'Asia/Singapore — SGT (UTC+8)' },
  { value: 'Asia/Kuala_Lumpur', label: 'Asia/Kuala_Lumpur — MYT (UTC+8)' },
  { value: 'Asia/Shanghai', label: 'Asia/Shanghai — CST (UTC+8)' },
  { value: 'Asia/Hong_Kong', label: 'Asia/Hong_Kong — HKT (UTC+8)' },
  { value: 'Asia/Tokyo', label: 'Asia/Tokyo — JST (UTC+9)' },
  { value: 'Asia/Seoul', label: 'Asia/Seoul — KST (UTC+9)' },
  { value: 'Australia/Perth', label: 'Australia/Perth — AWST (UTC+8)' },
  { value: 'Australia/Sydney', label: 'Australia/Sydney — AEST (UTC+10/+11)' },
  { value: 'Pacific/Auckland', label: 'Pacific/Auckland — NZST (UTC+12/+13)' },
]

const smtpHost = ref('')
const smtpPort = ref<number>(587)
const smtpEncryption = ref<'none' | 'tls' | 'ssl'>('tls')
const smtpUsername = ref('')
const smtpFrom = ref('')
const smtpRecipients = ref('')
const smtpPassword = ref('') // blank = keep existing
const hasPassword = ref(false)
const smtpEnabled = ref(true)
const testingDiscord = ref(false)

const discordWebhookUrl = ref('')
const discordEnabled = ref(false)
const savingDiscord = ref(false)

const autoResponseEnabled = ref(false)
const savingAutoResponse = ref(false)

const aiProvider = ref<'disabled' | 'anthropic' | 'openai' | 'gemini' | 'custom'>('disabled')
const aiModel = ref('claude-sonnet-4-6')
const aiBaseUrl = ref('')
const aiApiKey = ref('')
const aiHasKey = ref(false)
const aiTestStatus = ref<'idle' | 'testing' | 'ok' | 'error'>('idle')
const aiTestMsg = ref('')
const savingAi = ref(false)

const savingIdentity = ref(false)
const savingSmtp = ref(false)
const testing = ref(false)
const loading = ref(true)

onMounted(load)
async function load() {
  loading.value = true
  try {
    await settings.fetchSettings()
    instanceName.value = settings.general.instanceName
    baseUrl.value = settings.general.baseUrl
    timezone.value = settings.general.timezone
    smtpHost.value = settings.smtp.host
    smtpPort.value = settings.smtp.port
    smtpEncryption.value = settings.smtp.encryption
    smtpUsername.value = settings.smtp.username
    smtpFrom.value = settings.smtp.fromAddress
    smtpRecipients.value = settings.smtp.recipients
    hasPassword.value = settings.smtp.hasPassword
    smtpEnabled.value = settings.smtp.enabled
    discordWebhookUrl.value = settings.discord.webhookUrl
    discordEnabled.value = settings.discord.enabled
    autoResponseEnabled.value = settings.autoResponse.enabled
    aiProvider.value = settings.ai.provider
    aiModel.value = settings.ai.model
    aiHasKey.value = settings.ai.hasKey
    aiBaseUrl.value = settings.ai.baseUrl
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to load settings.')
  } finally {
    loading.value = false
  }
}

const smtpConfigured = computed(() => !!smtpHost.value.trim())

async function saveIdentity() {
  savingIdentity.value = true
  try {
    await settings.saveGeneral({
      instance_name: instanceName.value.trim() || 'OpsPilot',
      base_url: baseUrl.value.trim().replace(/\/+$/, ''),
      timezone: timezone.value,
    })
    baseUrl.value = settings.general.baseUrl
    timezone.value = settings.general.timezone
    notify.success('Settings saved.')
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to save settings.')
  } finally {
    savingIdentity.value = false
  }
}

async function saveSmtp() {
  savingSmtp.value = true
  try {
    const payload: Record<string, unknown> = {
      smtp_host: smtpHost.value.trim(),
      smtp_port: smtpPort.value,
      smtp_encryption: smtpEncryption.value,
      smtp_username: smtpUsername.value.trim(),
      smtp_from_address: smtpFrom.value.trim(),
      smtp_recipients: smtpRecipients.value.trim(),
      smtp_enabled: smtpEnabled.value,
    }
    // Only send the password when the admin typed a new one.
    if (smtpPassword.value) payload.smtp_password = smtpPassword.value
    await settings.saveSmtp(payload)
    smtpPassword.value = ''
    hasPassword.value = settings.smtp.hasPassword
    notify.success('Settings saved.')
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to save SMTP settings.')
  } finally {
    savingSmtp.value = false
  }
}

async function sendTest() {
  testing.value = true
  try {
    const res = await settings.testSmtp()
    notify.success(`Test email sent to ${res.sent_to}.`)
  } catch (err) {
    notify.error(getApiError(err) ?? 'Test email failed.')
  } finally {
    testing.value = false
  }
}

async function sendDiscordTest() {
  testingDiscord.value = true
  try {
    await settings.testDiscord()
    notify.success('Test notification sent to Discord.')
  } catch (err) {
    notify.error(getApiError(err) ?? 'Discord test failed.')
  } finally {
    testingDiscord.value = false
  }
}

async function saveDiscord() {
  savingDiscord.value = true
  try {
    await settings.saveDiscord({
      discord_webhook_url: discordWebhookUrl.value.trim(),
      discord_enabled: discordEnabled.value,
    })
    notify.success('Discord settings saved.')
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to save Discord settings.')
  } finally {
    savingDiscord.value = false
  }
}

async function saveAutoResponse() {
  savingAutoResponse.value = true
  try {
    await settings.saveAutoResponse({
      auto_response_enabled: autoResponseEnabled.value,
    })
    notify.success('Security auto-response settings saved.')
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to save security auto-response settings.')
  } finally {
    savingAutoResponse.value = false
  }
}

async function saveAi() {
  savingAi.value = true
  try {
    const patch: Record<string, unknown> = {
      ai_provider: aiProvider.value,
      ai_model: aiModel.value,
      ai_base_url: aiBaseUrl.value.trim() || null,
    }
    if (aiApiKey.value) patch.ai_api_key = aiApiKey.value
    await api.patch('/api/settings', patch)
    await settings.fetchSettings()
    aiHasKey.value = settings.ai.hasKey
    aiApiKey.value = ''
    aiTestStatus.value = 'idle'
    notify.success('AI settings saved.')
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to save AI settings.')
  } finally {
    savingAi.value = false
  }
}

async function testAi() {
  aiTestStatus.value = 'testing'
  aiTestMsg.value = ''
  try {
    const { data } = await api.post('/api/settings/ai/test')
    aiTestStatus.value = 'ok'
    aiTestMsg.value = `Connected — model responded: "${data.response}"`
  } catch (err) {
    aiTestStatus.value = 'error'
    aiTestMsg.value = getApiError(err)?.message ?? 'Connection failed'
  }
}
</script>

<template>
  <div class="general">
    <!-- Identity -->
    <section class="card">
      <h2>OpsPilot Identity</h2>
      <div class="field">
        <label>Instance Name</label>
        <input v-model="instanceName" type="text" placeholder="OpsPilot" :disabled="loading" />
        <p class="hint">Shown in email subjects and the public status page header.</p>
      </div>
      <div class="field">
        <label>Base URL</label>
        <input v-model="baseUrl" type="url" placeholder="https://monitor.yourdomain.com" :disabled="loading" />
        <p class="hint">Used in alert email links and cron/backup ping URLs. No trailing slash.</p>
      </div>
      <div class="field">
        <label>Timezone</label>
        <select v-model="timezone" :disabled="loading">
          <option v-for="tz in TIMEZONES" :key="tz.value" :value="tz.value">{{ tz.label }}</option>
        </select>
        <p class="hint">All timestamps and daily uptime bars use this timezone.</p>
      </div>
      <div v-if="!loading && !baseUrl.trim()" class="banner amber">
        Base URL is not configured — links will use the request Host header as fallback.
      </div>
      <button class="primary" :disabled="savingIdentity || loading" @click="saveIdentity">
        <span v-if="savingIdentity" class="spin"></span><span v-else>Save</span>
      </button>
    </section>

    <!-- SMTP -->
    <section class="card">
      <h2>Email (SMTP)</h2>
      <div class="field toggle-row">
        <div>
          <span class="toggle-label">Send alert notifications via email</span>
          <p class="hint">Uncheck to pause all email alerts without removing your SMTP configuration.</p>
        </div>
        <label class="switch">
          <input v-model="smtpEnabled" type="checkbox" :disabled="loading" />
          <span class="slider"></span>
        </label>
      </div>
      <div v-if="!loading && !smtpConfigured" class="banner amber">
        Email notifications are disabled — configure SMTP to receive alerts.
      </div>
      <div class="row">
        <div class="field grow">
          <label>SMTP Host</label>
          <input v-model="smtpHost" type="text" placeholder="smtp.gmail.com" :disabled="loading" />
        </div>
        <div class="field port">
          <label>Port</label>
          <input v-model.number="smtpPort" type="number" min="1" max="65535" :disabled="loading" />
        </div>
        <div class="field enc">
          <label>Encryption</label>
          <select v-model="smtpEncryption" :disabled="loading">
            <option value="none">None</option>
            <option value="tls">TLS (STARTTLS)</option>
            <option value="ssl">SSL/TLS</option>
          </select>
        </div>
      </div>
      <div class="field">
        <label>Username</label>
        <input v-model="smtpUsername" type="text" autocomplete="off" :disabled="loading" />
      </div>
      <div class="field">
        <label>Password</label>
        <input
          v-model="smtpPassword"
          type="password"
          autocomplete="new-password"
          :placeholder="hasPassword ? '••••••••' : ''"
          :disabled="loading"
        />
        <p v-if="hasPassword" class="hint">Leave blank to keep existing SMTP password.</p>
      </div>
      <div class="field">
        <label>From Address</label>
        <input v-model="smtpFrom" type="email" placeholder="alerts@yourdomain.com" :disabled="loading" />
      </div>
      <div class="field">
        <label>Alert Recipients</label>
        <input v-model="smtpRecipients" type="text" placeholder="admin@example.com, ops@example.com" :disabled="loading" />
        <p class="hint">Comma-separated. At least one address required to send.</p>
      </div>

      <div class="actions">
        <button class="primary" :disabled="savingSmtp || loading" @click="saveSmtp">
          <span v-if="savingSmtp" class="spin"></span><span v-else>Save</span>
        </button>
        <button class="ghost" :disabled="testing || loading || !smtpConfigured" @click="sendTest">
          <span v-if="testing" class="spin dark"></span><span v-else>Send Test Email</span>
        </button>
      </div>
    </section>

    <!-- Discord -->
    <section class="card">
      <h2>Discord Notifications</h2>
      <div class="field toggle-row">
        <div>
          <span class="toggle-label">Send alert notifications to Discord</span>
          <p class="hint">Fires a message to your Discord channel on every alert and resolve.</p>
        </div>
        <label class="switch">
          <input v-model="discordEnabled" type="checkbox" :disabled="loading" />
          <span class="slider"></span>
        </label>
      </div>
      <div class="field">
        <label>Webhook URL</label>
        <input
          v-model="discordWebhookUrl"
          type="url"
          placeholder="https://discord.com/api/webhooks/…"
          :disabled="loading"
        />
        <p class="hint">
          In Discord: channel settings → Integrations → Webhooks → New Webhook → Copy Webhook URL.
        </p>
      </div>
      <div class="actions">
        <button class="primary" :disabled="savingDiscord || loading" @click="saveDiscord">
          <span v-if="savingDiscord" class="spin"></span><span v-else>Save</span>
        </button>
        <button class="ghost" :disabled="testingDiscord || loading || !discordWebhookUrl.trim()" @click="sendDiscordTest">
          <span v-if="testingDiscord" class="spin dark"></span><span v-else>Send Test Notification</span>
        </button>
      </div>
    </section>

    <!-- Security Auto-Response -->
    <section class="card">
      <h2>Security Auto-Response</h2>
      <div class="field toggle-row">
        <div>
          <span class="toggle-label">Security auto-response (master switch)</span>
          <p class="hint">Master kill switch. When OFF, no automatic remediation runs on any server, regardless of per-server settings.</p>
        </div>
        <label class="switch">
          <input v-model="autoResponseEnabled" type="checkbox" :disabled="loading" />
          <span class="slider"></span>
        </label>
      </div>
      <div class="actions">
        <button class="primary" :disabled="savingAutoResponse || loading" @click="saveAutoResponse">
          <span v-if="savingAutoResponse" class="spin"></span><span v-else>Save</span>
        </button>
      </div>
    </section>

    <!-- AI Provider -->
    <section class="card">
      <h2>AI Provider</h2>
      <p class="section-desc">Used for Daily Report generation on each server's detail page.</p>
      <div class="field">
        <label>Provider</label>
        <select v-model="aiProvider" :disabled="loading">
          <option value="disabled">Disabled</option>
          <option value="anthropic">Anthropic (Claude)</option>
          <option value="openai">OpenAI (GPT)</option>
          <option value="gemini">Google Gemini</option>
          <option value="custom">Custom (LiteLLM / OpenAI-compatible)</option>
        </select>
      </div>
      <template v-if="aiProvider !== 'disabled'">
        <div v-if="aiProvider === 'custom'" class="field">
          <label>Base URL</label>
          <input
            v-model="aiBaseUrl"
            type="url"
            placeholder="http://localhost:4000"
            :disabled="loading"
          />
          <p class="hint">LiteLLM proxy URL, e.g. <code>http://localhost:4000</code>. Must include scheme and port.</p>
        </div>
        <div class="field">
          <label>Model</label>
          <input v-model="aiModel" type="text" placeholder="claude-sonnet-4-6" :disabled="loading" />
        </div>
        <div class="field">
          <label>API Key{{ aiProvider === 'custom' ? ' (optional)' : '' }}</label>
          <input
            v-model="aiApiKey"
            type="password"
            :placeholder="aiHasKey ? '••••••••  (leave blank to keep)' : aiProvider === 'custom' ? 'Leave blank if not required' : 'Paste API key'"
            autocomplete="new-password"
            :disabled="loading"
          />
        </div>
        <div v-if="aiTestStatus !== 'idle'" class="test-result" :class="aiTestStatus">
          {{ aiTestMsg }}
        </div>
        <div class="actions">
          <button class="primary" :disabled="savingAi || loading" @click="saveAi">
            <span v-if="savingAi" class="spin"></span><span v-else>Save AI Settings</span>
          </button>
          <button class="ghost" :disabled="aiTestStatus === 'testing' || loading" @click="testAi">
            <span v-if="aiTestStatus === 'testing'" class="spin dark"></span>
            <span v-else>Test Connection</span>
          </button>
        </div>
      </template>
      <template v-else>
        <div class="actions">
          <button class="primary" :disabled="savingAi || loading" @click="saveAi">
            <span v-if="savingAi" class="spin"></span><span v-else>Save</span>
          </button>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.general { display: flex; flex-direction: column; gap: 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 22px; max-width: 640px; }
.card h2 { font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-bottom: 18px; }
.field { margin-bottom: 16px; }
.row { display: flex; gap: 12px; }
.grow { flex: 1; }
.port { width: 90px; }
.enc { width: 170px; }
label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; }
input, select { width: 100%; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; color: var(--text); font-size: 14px; outline: none; }
input:focus, select:focus { border-color: var(--accent); }
input:disabled, select:disabled { opacity: 0.6; }
.hint { color: var(--muted); font-size: 12px; margin-top: 6px; }
.banner { padding: 10px 14px; border-radius: 8px; font-size: 13px; margin-bottom: 16px; }
.banner.amber { background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.4); color: #fcd34d; }
.actions { display: flex; gap: 10px; align-items: center; margin-top: 4px; }
.primary { background: linear-gradient(90deg, var(--accent), var(--accent-2)); border: none; color: #fff; padding: 11px 28px; border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; min-height: 42px; min-width: 120px; }
.primary:disabled { opacity: 0.6; cursor: wait; }
.ghost { background: var(--surface-2); border: 1px solid var(--border); color: var(--text); padding: 11px 20px; border-radius: 8px; font-weight: 500; font-size: 13px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; min-height: 42px; }
.ghost:disabled { opacity: 0.5; cursor: not-allowed; }
.spin { width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.4); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; }
.spin.dark { border-color: rgba(255,255,255,0.2); border-top-color: var(--text); }
@keyframes spin { to { transform: rotate(360deg); } }
.toggle-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.toggle-label { font-size: 14px; color: var(--text); }
.switch { position: relative; display: inline-block; width: 44px; height: 24px; flex-shrink: 0; margin-top: 2px; }
.switch input { opacity: 0; width: 0; height: 0; }
.slider { position: absolute; cursor: pointer; inset: 0; background: var(--border); border-radius: 24px; transition: 0.2s; }
.slider::before { content: ''; position: absolute; width: 18px; height: 18px; left: 3px; top: 3px; background: #fff; border-radius: 50%; transition: 0.2s; }
input:checked + .slider { background: var(--accent); }
input:checked + .slider::before { transform: translateX(20px); }
input:disabled + .slider { opacity: 0.5; cursor: not-allowed; }
.section-desc { font-size: 13px; color: var(--muted); margin-bottom: 16px; margin-top: -10px; }
.hint code { background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; font-size: 11px; font-family: monospace; }
.test-result { font-size: 13px; padding: 8px 12px; border-radius: 8px; margin-bottom: 12px; }
.test-result.ok      { background: rgba(34,197,94,.1);  color: var(--green); border: 1px solid rgba(34,197,94,.2); }
.test-result.error   { background: rgba(239,68,68,.1);  color: var(--red);   border: 1px solid rgba(239,68,68,.2); }
.test-result.testing { background: var(--surface-2); color: var(--muted); border: 1px solid var(--border); }
</style>
