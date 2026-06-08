<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { SlideOver } from '@/components/ui'
import { useServerStore } from '@/stores/server'
import { useJobsStore } from '@/stores/jobs'
import type { MonitoredJob, JobPayload } from '@/stores/jobs'
import { cronToLabel } from '@/components/cron-backup/cronLabel'
import { useNotify } from '@/composables/useNotify'

const props = defineProps<{
  job?: MonitoredJob | null   // null/undefined = create mode, populated = edit mode
  serverId?: string | null    // if provided, server dropdown is locked to this server
}>()

const emit = defineEmits<{
  (e: 'saved'): void
  (e: 'close'): void
}>()

const serverStore = useServerStore()
const store = useJobsStore()
const notify = useNotify()

const GRACE_OPTIONS = [5, 10, 15, 30, 60, 120, 240]
const graceLabel = (m: number) =>
  m < 60 ? `${m} min` : m === 60 ? '1 hour' : `${m / 60} hours`

const form = ref({
  server_id: '',
  name: '',
  schedule: '0 2 * * *',
  grace_period_min: 10,
  description: '',
})
const errors = ref<Record<string, string>>({})
const submitting = ref(false)

const editMode = computed(() => props.job != null)

const lockedServer = computed(() =>
  props.serverId ? serverStore.servers.find((s) => s.id === props.serverId) ?? null : null
)

const schedulePreview = computed(() => cronToLabel(form.value.schedule))

function reset(): void {
  errors.value = {}
  if (props.job) {
    form.value = {
      server_id: props.job.server_id,
      name: props.job.name,
      schedule: props.job.schedule,
      grace_period_min: props.job.grace_period_min,
      description: props.job.description ?? '',
    }
  } else {
    form.value = {
      server_id: props.serverId ?? serverStore.servers[0]?.id ?? '',
      name: '',
      schedule: '0 2 * * *',
      grace_period_min: 10,
      description: '',
    }
  }
}

watch(() => [props.job, props.serverId], reset, { immediate: true, deep: true })

function validate(): boolean {
  errors.value = {}
  if (!form.value.server_id) errors.value.server_id = 'Select a server'
  const n = form.value.name.trim()
  if (n.length < 2 || n.length > 100) errors.value.name = 'Name must be 2–100 characters'
  if (!form.value.schedule.trim()) {
    errors.value.schedule = 'Schedule is required'
  } else if (!cronToLabel(form.value.schedule).valid) {
    errors.value.schedule = 'Invalid cron expression'
  }
  return Object.keys(errors.value).length === 0
}

async function submit(): Promise<void> {
  if (!validate()) return
  submitting.value = true
  try {
    const payload: JobPayload = {
      server_id: form.value.server_id,
      name: form.value.name.trim(),
      schedule: form.value.schedule.trim(),
      grace_period_min: form.value.grace_period_min,
      description: form.value.description.trim() || null,
    }
    if (editMode.value && props.job) {
      await store.updateJob(props.job.id, payload)
      notify.success('Job updated')
    } else {
      await store.createJob(payload)
      notify.success('Job created')
    }
    emit('saved')
  } catch (err) {
    const msg = (err as { response?: { data?: { detail?: { message?: string } } } })?.response?.data?.detail?.message
    errors.value._form = msg ?? 'Could not save the job.'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <SlideOver
    :model-value="true"
    :title="editMode ? 'Edit Monitored Job' : 'Add Monitored Job'"
    width="480px"
    @update:model-value="emit('close')"
  >
    <form id="job-modal-form" @submit.prevent="submit">
      <label>Server *</label>
      <select
        v-if="!lockedServer"
        v-model="form.server_id"
        :class="{ invalid: errors.server_id }"
      >
        <option v-for="s in serverStore.servers" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
      <input v-else :value="lockedServer.name" disabled class="locked" />
      <div v-if="errors.server_id" class="err">{{ errors.server_id }}</div>

      <label>Job Name *</label>
      <input v-model="form.name" placeholder="e.g. gdrive-nightly" :class="{ invalid: errors.name }" />
      <div v-if="errors.name" class="err">{{ errors.name }}</div>

      <label>Schedule (cron) *</label>
      <input
        v-model="form.schedule"
        placeholder="0 2 * * *"
        :class="{ invalid: errors.schedule }"
        spellcheck="false"
      />
      <div v-if="errors.schedule" class="err">{{ errors.schedule }}</div>
      <div v-else-if="form.schedule.trim()" class="preview" :class="{ 'preview-invalid': !schedulePreview.valid }">
        {{ schedulePreview.valid ? schedulePreview.label : 'Invalid expression' }}
      </div>

      <label>Grace Period</label>
      <select v-model.number="form.grace_period_min">
        <option v-for="m in GRACE_OPTIONS" :key="m" :value="m">{{ graceLabel(m) }}</option>
      </select>

      <label>Description</label>
      <textarea v-model="form.description" placeholder="Optional notes" rows="3" />

      <div v-if="errors._form" class="err form-err">{{ errors._form }}</div>
    </form>

    <template #footer>
      <button type="button" class="btn ghost" @click="emit('close')">Cancel</button>
      <button type="submit" form="job-modal-form" class="primary" :disabled="submitting">
        {{ submitting ? 'Saving…' : editMode ? 'Save Changes' : 'Create Job' }}
      </button>
    </template>
  </SlideOver>
</template>

<style scoped>
label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; margin-top: 16px; }
label:first-child { margin-top: 0; }
input, select, textarea { width: 100%; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; color: var(--text); font-size: 13px; outline: none; font-family: inherit; box-sizing: border-box; resize: vertical; }
input:focus, select:focus, textarea:focus { border-color: var(--accent); }
input.invalid, select.invalid, textarea.invalid { border-color: var(--red); }
input.locked { opacity: 0.6; cursor: not-allowed; }
.err { color: var(--red); font-size: 11px; margin-top: 6px; }
.form-err { margin-top: 14px; }
.preview { font-size: 11px; margin-top: 6px; color: var(--muted); }
.preview-invalid { color: var(--red); }
.primary { padding: 9px 18px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); color: #fff; border: none; border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; }
.primary:disabled { opacity: 0.6; cursor: wait; }
.btn { padding: 8px 16px; border-radius: 8px; font-size: 12px; cursor: pointer; border: 1px solid var(--border); background: var(--surface-2); color: var(--text); }
.btn.ghost:hover { border-color: var(--accent); color: var(--accent-2); }
</style>
