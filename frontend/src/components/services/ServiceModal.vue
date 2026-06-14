<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { SlideOver } from '@/components/ui'
import { getApiError } from '@/services/api'
import { useServiceStore } from '@/stores/services'
import type { Service, ServiceCreatePayload, ServiceType, ServiceUpdatePayload } from '@/stores/services'

interface ServerOption {
  id: string
  name: string
  status: string
}

const props = defineProps<{
  modelValue: boolean
  service: Service | null
  servers: ServerOption[]
  lockedServerId?: string | null
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'saved', s: Service): void
}>()

const store = useServiceStore()

const editMode = computed(() => props.service != null)
const submitting = ref(false)

const INTERVALS = [30, 60, 120, 300, 600]
const TIMEOUTS = [3, 5, 10, 30]
const METHODS = ['GET', 'POST', 'HEAD']
interface FormState {
  server_id: string
  name: string
  type: ServiceType
  interval_sec: number
  timeout_sec: number
  is_active: boolean
  is_public: boolean
  // http
  url: string
  expected_status: number
  ignore_ssl_errors: boolean
  ssl_warn_days: number
  ssl_critical_days: number
  // content monitoring (http only)
  expected_keyword: string
  forbidden_keywords_enabled: boolean
  // tcp
  host: string
  port: number | null
}

function blank(): FormState {
  return {
    server_id: props.lockedServerId ?? props.servers[0]?.id ?? '',
    name: '',
    type: 'http',
    interval_sec: 60,
    timeout_sec: 5,
    is_active: true,
    is_public: false,
    url: '',
    expected_status: 200,
    ignore_ssl_errors: false,
    ssl_warn_days: 30,
    ssl_critical_days: 7,
    expected_keyword: '',
    forbidden_keywords_enabled: true,
    host: '',
    port: null,
  }
}

const form = reactive<FormState>(blank())
const errors = reactive<Record<string, string>>({})
const nameTouched = ref(false)

function hydrate(): void {
  Object.assign(form, blank())
  for (const k of Object.keys(errors)) delete errors[k]
  nameTouched.value = false
  const s = props.service
  if (!s) return
  form.server_id = s.server_id
  form.name = s.name
  form.type = s.type
  form.interval_sec = s.interval_sec
  form.timeout_sec = s.timeout_sec
  form.is_active = s.is_active
  form.is_public = s.is_public
  if (s.type === 'http') {
    form.url = s.url ?? ''
    form.expected_status = s.expected_status ?? 200
    form.ignore_ssl_errors = s.ignore_ssl_errors
    form.ssl_warn_days = s.ssl_warn_days ?? 30
    form.ssl_critical_days = s.ssl_critical_days ?? 7
    form.expected_keyword = s.expected_keyword ?? ''
    form.forbidden_keywords_enabled = s.forbidden_keywords_enabled ?? true
  } else {
    form.host = s.url ?? ''
    form.port = s.port
  }
  nameTouched.value = true
}

watch(() => props.modelValue, (open) => { if (open) hydrate() })

// Auto-fill the service name from URL/host:port unless the user edited it.
function autoFillName(): void {
  if (nameTouched.value) return
  if (form.type === 'http') {
    try {
      if (form.url) form.name = new URL(form.url).hostname
    } catch { /* incomplete URL */ }
  } else if (form.host && form.port) {
    form.name = `${form.host}:${form.port}`
  }
}

const intervalAdvisory = computed(() => form.interval_sec <= form.timeout_sec)
const isHttps = computed(() => /^https:\/\//i.test(form.url.trim()))

function validate(): boolean {
  for (const k of Object.keys(errors)) delete errors[k]
  if (!form.server_id) errors.server_id = 'Select a server'
  const name = form.name.trim()
  if (name.length < 2 || name.length > 100) errors.name = 'Name must be 2–100 characters'
  if (form.type === 'http') {
    if (!/^https?:\/\//.test(form.url.trim())) errors.url = 'Must start with http:// or https://'
    else if (form.url.trim().length > 500) errors.url = 'URL is too long (max 500)'
    if (form.expected_status < 100 || form.expected_status > 599) errors.expected_status = 'Status must be 100–599'
    if (isHttps.value) {
      if (form.ssl_warn_days < 1 || form.ssl_warn_days > 365)
        errors.ssl_warn_days = 'Must be 1–365'
      if (form.ssl_critical_days < 1 || form.ssl_critical_days >= form.ssl_warn_days)
        errors.ssl_critical_days = 'Must be ≥ 1 and less than warn threshold'
    }
    if (form.expected_keyword.trim().length > 200)
      errors.expected_keyword = 'Must be ≤ 200 characters'
  } else {
    if (!form.host.trim()) errors.host = 'Host is required'
    else if (/^https?:\/\//.test(form.host.trim())) errors.host = 'Enter a hostname or IP without protocol'
    if (form.port == null || form.port < 1 || form.port > 65535) errors.port = 'Port must be 1–65535'
  }
  return Object.keys(errors).length === 0
}

async function submit(): Promise<void> {
  if (!validate()) return
  submitting.value = true
  try {
    if (editMode.value && props.service) {
      const payload: ServiceUpdatePayload = {
        name: form.name.trim(),
        interval_sec: form.interval_sec,
        timeout_sec: form.timeout_sec,
        is_active: form.is_active,
        is_public: form.is_public,
      }
      if (form.type === 'http') {
        payload.url = form.url.trim()
        payload.expected_status = form.expected_status
        payload.ignore_ssl_errors = form.ignore_ssl_errors
        payload.ssl_warn_days = form.ssl_warn_days
        payload.ssl_critical_days = form.ssl_critical_days
        payload.expected_keyword = form.expected_keyword.trim() || null
        payload.forbidden_keywords_enabled = form.forbidden_keywords_enabled
      } else {
        payload.url = form.host.trim()
        payload.port = form.port
      }
      const saved = await store.updateService(props.service.id, payload)
      emit('saved', saved)
    } else {
      const payload: ServiceCreatePayload = {
        server_id: form.server_id,
        name: form.name.trim(),
        type: form.type,
        interval_sec: form.interval_sec,
        timeout_sec: form.timeout_sec,
        is_active: form.is_active,
        is_public: form.is_public,
        ignore_ssl_errors: form.type === 'http' ? form.ignore_ssl_errors : false,
      }
      if (form.type === 'http') {
        payload.url = form.url.trim()
        payload.expected_status = form.expected_status
        if (isHttps.value) {
          payload.ssl_warn_days = form.ssl_warn_days
          payload.ssl_critical_days = form.ssl_critical_days
        }
        payload.expected_keyword = form.expected_keyword.trim() || null
        payload.forbidden_keywords_enabled = form.forbidden_keywords_enabled
      } else {
        payload.url = form.host.trim()
        payload.port = form.port
      }
      const saved = await store.createService(payload)
      emit('saved', saved)
    }
    emit('update:modelValue', false)
  } catch (err) {
    errors._form = getApiError(err)?.message ?? 'Unable to save service.'
  } finally {
    submitting.value = false
  }
}

function intervalLabel(s: number): string {
  if (s < 60) return `${s}s`
  return s % 60 === 0 ? `${s / 60}min` : `${s}s`
}
</script>

<template>
  <SlideOver
    :model-value="modelValue"
    :title="editMode ? 'Edit Service' : 'Add Service'"
    :subtitle="editMode ? service?.name : 'Monitor an HTTP endpoint or TCP port'"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <form id="service-form" class="form" @submit.prevent="submit">
      <label class="fl">Server</label>
      <select v-model="form.server_id" :disabled="editMode || !!lockedServerId" :class="{ invalid: errors.server_id }">
        <option v-for="srv in servers" :key="srv.id" :value="srv.id">{{ srv.name }}</option>
      </select>
      <p v-if="errors.server_id" class="err">{{ errors.server_id }}</p>

      <label class="fl">Type</label>
      <div class="radio-row">
        <label class="radio" :class="{ on: form.type === 'http' }">
          <input v-model="form.type" type="radio" value="http" :disabled="editMode" /> HTTP
        </label>
        <label class="radio" :class="{ on: form.type === 'tcp' }">
          <input v-model="form.type" type="radio" value="tcp" :disabled="editMode" /> TCP
        </label>
      </div>

      <!-- HTTP fields -->
      <template v-if="form.type === 'http'">
        <label class="fl">URL</label>
        <input
          v-model="form.url"
          placeholder="https://app.example.com/health"
          :class="{ invalid: errors.url }"
          @blur="autoFillName"
        />
        <p v-if="errors.url" class="err">{{ errors.url }}</p>

        <div class="row">
          <div class="col">
            <label class="fl">Method</label>
            <select disabled><option>GET</option></select>
            <small class="hint">GET (configurable in a future release)</small>
          </div>
          <div class="col">
            <label class="fl">Expected Status</label>
            <input v-model.number="form.expected_status" type="number" :class="{ invalid: errors.expected_status }" />
            <p v-if="errors.expected_status" class="err">{{ errors.expected_status }}</p>
          </div>
        </div>

        <label class="toggle">
          <input v-model="form.ignore_ssl_errors" type="checkbox" />
          <span>Ignore SSL Errors</span>
        </label>
        <p v-if="form.ignore_ssl_errors" class="advisory">
          SSL cert errors will be ignored for this probe. SSL expiry is still tracked separately.
        </p>

        <!-- SSL thresholds — shown only for https:// URLs -->
        <template v-if="isHttps">
          <div class="section-divider"></div>
          <p class="ssl-hint">SSL certificate expiry will be tracked automatically for this HTTPS service.</p>
          <div class="row">
            <div class="col">
              <label class="fl">Warn at (days)</label>
              <input
                v-model.number="form.ssl_warn_days"
                type="number"
                min="1"
                max="365"
                :class="{ invalid: errors.ssl_warn_days }"
              />
              <p v-if="errors.ssl_warn_days" class="err">{{ errors.ssl_warn_days }}</p>
            </div>
            <div class="col">
              <label class="fl">Critical at (days)</label>
              <input
                v-model.number="form.ssl_critical_days"
                type="number"
                min="1"
                :class="{ invalid: errors.ssl_critical_days }"
              />
              <p v-if="errors.ssl_critical_days" class="err">{{ errors.ssl_critical_days }}</p>
            </div>
          </div>
        </template>

        <!-- Content Monitoring -->
        <div class="section-divider"></div>
        <p class="section-label">Content Monitoring</p>

        <label class="toggle">
          <input v-model="form.forbidden_keywords_enabled" type="checkbox" />
          <span>Block malicious content</span>
        </label>
        <p v-if="form.forbidden_keywords_enabled" class="info-chip">
          Alerts if gambling or defacement keywords (e.g. "judi", "casino", "togel") are found in the response body.
        </p>

        <label class="fl">Expected keyword <span class="optional">(optional)</span></label>
        <input
          v-model="form.expected_keyword"
          placeholder="e.g. Kementerian Pertanian"
          :class="{ invalid: errors.expected_keyword }"
          maxlength="200"
        />
        <p v-if="errors.expected_keyword" class="err">{{ errors.expected_keyword }}</p>
        <small v-else class="hint">Alert if this text is missing from the response body.</small>
      </template>

      <!-- TCP / DB fields -->
      <template v-else>
        <div class="row">
          <div class="col" style="flex: 2">
            <label class="fl">Host</label>
            <input v-model="form.host" placeholder="db.example.com" :class="{ invalid: errors.host }" @blur="autoFillName" />
            <p v-if="errors.host" class="err">{{ errors.host }}</p>
          </div>
          <div class="col">
            <label class="fl">Port</label>
            <input v-model.number="form.port" type="number" placeholder="3306" :class="{ invalid: errors.port }" @blur="autoFillName" />
            <p v-if="errors.port" class="err">{{ errors.port }}</p>
          </div>
        </div>
      </template>

      <label class="fl">Service Name</label>
      <input v-model="form.name" placeholder="Auto-filled from URL/host" :class="{ invalid: errors.name }" @input="nameTouched = true" />
      <p v-if="errors.name" class="err">{{ errors.name }}</p>

      <div class="row">
        <div class="col">
          <label class="fl">Check Interval</label>
          <select v-model.number="form.interval_sec">
            <option v-for="i in INTERVALS" :key="i" :value="i">{{ intervalLabel(i) }}</option>
          </select>
        </div>
        <div class="col">
          <label class="fl">Timeout</label>
          <select v-model.number="form.timeout_sec">
            <option v-for="t in TIMEOUTS" :key="t" :value="t">{{ t }}s</option>
          </select>
        </div>
      </div>
      <p v-if="intervalAdvisory" class="advisory">
        Interval is shorter than or equal to the timeout — checks may overlap.
      </p>

      <label class="toggle">
        <input v-model="form.is_active" type="checkbox" />
        <span>Active</span>
      </label>
      <p v-if="!form.is_active" class="info-chip">Service is inactive — checks will not run.</p>

      <label class="toggle">
        <input v-model="form.is_public" type="checkbox" />
        <span>Show on public status page</span>
      </label>

      <p v-if="errors._form" class="err form-err">{{ errors._form }}</p>
    </form>

    <template #footer>
      <button type="button" class="btn ghost" @click="emit('update:modelValue', false)">Cancel</button>
      <button type="submit" form="service-form" class="btn primary" :disabled="submitting">
        <span v-if="submitting" class="spin"></span>
        <span v-else>{{ editMode ? 'Save Changes' : 'Add Service' }}</span>
      </button>
    </template>
  </SlideOver>
</template>

<style scoped>
.form { display: flex; flex-direction: column; }
.fl { font-size: 12px; color: var(--muted); margin: 14px 0 6px; }
input, select { width: 100%; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; color: var(--text); font-size: 13px; outline: none; font-family: inherit; }
input:focus, select:focus { border-color: var(--accent); }
input.invalid, select.invalid { border-color: var(--red); }
input:disabled, select:disabled { opacity: 0.6; cursor: not-allowed; }
.row { display: flex; gap: 12px; }
.col { flex: 1; }
.radio-row { display: flex; gap: 8px; }
.radio { flex: 1; display: flex; align-items: center; justify-content: center; gap: 6px; padding: 9px; border: 1px solid var(--border); border-radius: 8px; font-size: 13px; color: var(--muted); cursor: pointer; background: var(--surface-2); }
.radio.on { border-color: var(--accent); color: var(--accent-2); background: rgba(99,102,241,0.1); }
.radio input { width: auto; }
.toggle { display: flex; align-items: center; gap: 8px; margin-top: 16px; font-size: 13px; color: var(--text); cursor: pointer; }
.toggle input { width: auto; }
.hint { font-size: 11px; color: var(--muted); margin-top: 4px; display: block; }
.err { color: var(--red); font-size: 11px; margin-top: 6px; }
.form-err { margin-top: 14px; }
.advisory { font-size: 11px; color: var(--amber); margin-top: 8px; background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.25); border-radius: 6px; padding: 8px 10px; }
.info-chip { font-size: 11px; color: var(--muted); margin-top: 6px; background: rgba(107,114,128,0.15); border-radius: 6px; padding: 6px 10px; }
.btn { padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; border: 1px solid var(--border); background: var(--surface-2); color: var(--text); display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 38px; }
.btn.ghost:hover { border-color: var(--accent); color: var(--accent-2); }
.btn.primary { background: linear-gradient(90deg, var(--accent), var(--accent-2)); color: #fff; border: none; }
.btn.primary:disabled { opacity: 0.6; cursor: wait; }
.spin { width: 14px; height: 14px; border: 2px solid rgba(255,255,255,0.4); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.section-divider { height: 1px; background: var(--border); margin: 12px 0; }
.ssl-hint { font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.section-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 4px; }
.optional { font-size: 11px; color: var(--muted); font-weight: 400; }
</style>
