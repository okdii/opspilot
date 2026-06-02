<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useNotify } from '@/composables/useNotify'
import { getApiError } from '@/services/api'

const settings = useSettingsStore()
const notify = useNotify()

interface FieldDef {
  key: 'metricsRetentionDays' | 'logsRetentionDays' | 'serviceChecksRetentionDays' | 'alertsRetentionDays'
  payloadKey: string
  label: string
  hint: string
  min: number
  max: number
}

const fields: FieldDef[] = [
  { key: 'metricsRetentionDays', payloadKey: 'metrics_retention_days', label: 'Raw metrics retention', hint: 'How long per-point server metrics are kept.', min: 7, max: 365 },
  { key: 'logsRetentionDays', payloadKey: 'logs_retention_days', label: 'Log retention', hint: 'How long ingested server logs are kept.', min: 7, max: 365 },
  { key: 'serviceChecksRetentionDays', payloadKey: 'service_checks_retention_days', label: 'Service check retention', hint: 'How long HTTP/TCP probe results are kept.', min: 30, max: 365 },
  { key: 'alertsRetentionDays', payloadKey: 'alerts_retention_days', label: 'Alert history retention', hint: 'How long resolved alerts are kept.', min: 30, max: 730 },
]

const model = ref<Record<string, number>>({
  metricsRetentionDays: 30,
  logsRetentionDays: 30,
  serviceChecksRetentionDays: 90,
  alertsRetentionDays: 90,
})
const errors = ref<Record<string, string>>({})
const loading = ref(true)
const saving = ref(false)

onMounted(load)
async function load() {
  loading.value = true
  try {
    await settings.fetchSettings()
    model.value = { ...settings.retention }
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to load retention settings.')
  } finally {
    loading.value = false
  }
}

function validate(): boolean {
  errors.value = {}
  for (const f of fields) {
    const v = model.value[f.key]
    if (v == null || Number.isNaN(v)) errors.value[f.key] = 'Required'
    else if (v < f.min || v > f.max) errors.value[f.key] = `Must be between ${f.min} and ${f.max} days`
  }
  return Object.keys(errors.value).length === 0
}

async function save() {
  if (!validate()) return
  saving.value = true
  try {
    const payload: Record<string, number> = {}
    for (const f of fields) payload[f.payloadKey] = model.value[f.key]
    await settings.saveRetention(payload)
    model.value = { ...settings.retention }
    notify.success('Retention settings saved. Changes will take effect shortly.')
  } catch (err) {
    notify.error(getApiError(err) ?? 'Unable to save retention settings.')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="card">
    <h2>Data Retention</h2>

    <div class="banner warn">
      <strong>⚠ Reducing a retention period deletes existing data beyond the new limit</strong>
      immediately via the TimescaleDB retention policy. This cannot be undone. Increasing a period
      does not restore already-deleted data.
    </div>

    <div class="fields">
      <div v-for="f in fields" :key="f.key" class="field">
        <label>{{ f.label }}</label>
        <div class="input-wrap">
          <input
            v-model.number="model[f.key]"
            type="number"
            :min="f.min"
            :max="f.max"
            :disabled="loading"
            :class="{ invalid: errors[f.key] }"
          />
          <span class="unit">days</span>
        </div>
        <p v-if="errors[f.key]" class="err">{{ errors[f.key] }}</p>
        <p v-else class="hint">{{ f.hint }} ({{ f.min }}–{{ f.max }} days)</p>
      </div>
    </div>

    <button class="primary" :disabled="saving || loading" @click="save">
      <span v-if="saving" class="spin"></span><span v-else>Save Retention Settings</span>
    </button>
  </section>
</template>

<style scoped>
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 22px; max-width: 560px; }
.card h2 { font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-bottom: 18px; }
.banner { padding: 12px 14px; border-radius: 8px; font-size: 13px; line-height: 1.5; margin-bottom: 20px; }
.banner.warn { background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.4); color: #fcd34d; }
.banner strong { color: #fde68a; }
.fields { display: flex; flex-direction: column; gap: 16px; margin-bottom: 22px; }
label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; }
.input-wrap { display: flex; align-items: center; gap: 8px; }
input { width: 120px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; color: var(--text); font-size: 14px; outline: none; }
input:focus { border-color: var(--accent); }
input.invalid { border-color: var(--red); }
input:disabled { opacity: 0.6; }
.unit { color: var(--muted); font-size: 13px; }
.hint { color: var(--muted); font-size: 12px; margin-top: 6px; }
.err { color: var(--red); font-size: 12px; margin-top: 6px; }
.primary { background: linear-gradient(90deg, var(--accent), var(--accent-2)); border: none; color: #fff; padding: 11px 28px; border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; min-height: 42px; min-width: 200px; }
.primary:disabled { opacity: 0.6; cursor: wait; }
.spin { width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.4); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
