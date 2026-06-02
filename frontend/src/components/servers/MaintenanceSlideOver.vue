<script setup lang="ts">
import { computed, ref } from 'vue'
import { SlideOver } from '@/components/ui'
import { useMetricsStore } from '@/stores/metrics'
import { relativeTime } from '@/utils/metrics'

const props = defineProps<{ modelValue: boolean; serverName: string }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const metrics = useMetricsStore()
const active = computed(() => metrics.maintenance.active)

// Form state (enable flow)
type EndMode = 'none' | 'duration' | 'specific'
const reason = ref('')
const endMode = ref<EndMode>('none')
const duration = ref('2h')
const specificAt = ref('')
const busy = ref(false)
const error = ref<string | null>(null)

const DURATION_MS: Record<string, number> = {
  '30m': 30 * 60_000, '1h': 60 * 60_000, '2h': 120 * 60_000,
  '4h': 240 * 60_000, '8h': 480 * 60_000,
}

function close() {
  emit('update:modelValue', false)
}

function computeEndsAt(): string | null {
  if (endMode.value === 'duration') return new Date(Date.now() + DURATION_MS[duration.value]).toISOString()
  if (endMode.value === 'specific' && specificAt.value) return new Date(specificAt.value).toISOString()
  return null
}

async function enable() {
  busy.value = true
  error.value = null
  try {
    await metrics.startMaintenance({ reason: reason.value || null, ends_at: computeEndsAt() })
    close()
  } catch {
    error.value = 'Failed to enable maintenance.'
  } finally {
    busy.value = false
  }
}

async function end() {
  busy.value = true
  error.value = null
  try {
    await metrics.endMaintenance()
    close()
  } catch {
    error.value = 'Failed to end maintenance.'
  } finally {
    busy.value = false
  }
}

const endsLabel = computed(() => {
  const e = metrics.maintenance.ends_at
  return e ? `${new Date(e).toLocaleString()} (${relativeTime(e).replace(' ago', '')} left)` : 'No end time (manual)'
})
</script>

<template>
  <SlideOver
    :model-value="props.modelValue"
    :title="active ? `Maintenance Active — ${serverName}` : `Maintenance Mode — ${serverName}`"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <!-- Active state -->
    <div v-if="active" class="mw">
      <p class="mw-desc">Alerts for this server are suppressed. Metric and log collection continues.</p>
      <dl class="mw-meta">
        <div><dt>Reason</dt><dd>{{ metrics.maintenance.reason || '—' }}</dd></div>
        <div><dt>Started</dt><dd>{{ metrics.maintenance.starts_at ? new Date(metrics.maintenance.starts_at).toLocaleString() : '—' }}</dd></div>
        <div><dt>Ends</dt><dd>{{ endsLabel }}</dd></div>
      </dl>
      <p v-if="error" class="mw-err">{{ error }}</p>
      <div class="mw-actions">
        <button class="btn ghost" :disabled="busy" @click="close">Cancel</button>
        <button class="btn danger" :disabled="busy" @click="end">End Maintenance Now</button>
      </div>
    </div>

    <!-- Enable state -->
    <div v-else class="mw">
      <p class="mw-desc">Enable maintenance mode to suppress all alerts for this server. Metric and log collection continues uninterrupted.</p>

      <label class="mw-field">
        <span>Reason (optional)</span>
        <input v-model="reason" type="text" placeholder="e.g. OS kernel upgrade" />
      </label>

      <fieldset class="mw-field">
        <legend>Auto-end maintenance after</legend>
        <label class="mw-radio"><input v-model="endMode" type="radio" value="none" /> No end time (manual off)</label>
        <label class="mw-radio">
          <input v-model="endMode" type="radio" value="duration" /> Duration:
          <select v-model="duration" :disabled="endMode !== 'duration'">
            <option v-for="d in ['30m','1h','2h','4h','8h']" :key="d" :value="d">{{ d }}</option>
          </select>
        </label>
        <label class="mw-radio">
          <input v-model="endMode" type="radio" value="specific" /> Specific time:
          <input v-model="specificAt" type="datetime-local" :disabled="endMode !== 'specific'" />
        </label>
      </fieldset>

      <p v-if="error" class="mw-err">{{ error }}</p>
      <div class="mw-actions">
        <button class="btn ghost" :disabled="busy" @click="close">Cancel</button>
        <button class="btn primary" :disabled="busy" @click="enable">Enable Maintenance</button>
      </div>
    </div>
  </SlideOver>
</template>

<style scoped>
.mw { display: flex; flex-direction: column; gap: 18px; }
.mw-desc { color: var(--muted); font-size: 13px; line-height: 1.5; }
.mw-meta { display: flex; flex-direction: column; gap: 10px; }
.mw-meta div { display: flex; justify-content: space-between; gap: 16px; font-size: 13px; }
.mw-meta dt { color: var(--muted); }
.mw-meta dd { color: var(--text); text-align: right; }
.mw-field { display: flex; flex-direction: column; gap: 8px; border: 0; padding: 0; }
.mw-field > span, .mw-field legend { font-size: 12px; color: var(--muted); }
.mw-field input[type='text'], .mw-field input[type='datetime-local'], .mw-field select {
  background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px;
  padding: 9px 12px; color: var(--text); font-size: 13px;
}
.mw-radio { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text); }
.mw-err { color: var(--red); font-size: 13px; }
.mw-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 4px; }
.btn { padding: 9px 16px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; border: 1px solid transparent; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.ghost { background: transparent; border-color: var(--border); color: var(--text); }
.btn.primary { background: var(--accent); color: #fff; }
.btn.danger { background: var(--red); color: #fff; }
</style>
