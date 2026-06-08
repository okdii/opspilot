<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useServerStore } from '@/stores/server'
import { useCronBackupStore } from '@/stores/cronBackup'
import type { BackupJob, BackupJobPayload } from '@/stores/cronBackup'
import { useNotify } from '@/composables/useNotify'

const props = defineProps<{
  job: BackupJob | null        // null = create mode
  serverId?: string            // if set: pre-fills and locks the server dropdown
}>()

const emit = defineEmits<{
  (e: 'saved', job: BackupJob): void
  (e: 'close'): void
}>()

const serverStore = useServerStore()
const store = useCronBackupStore()
const notify = useNotify()

const INTERVAL_OPTIONS = [1, 6, 12, 24, 48, 168, 720]
const intervalLabel = (h: number) =>
  h < 24 ? `${h} hour${h > 1 ? 's' : ''}` : h === 24 ? 'Daily (24h)' : h === 168 ? 'Weekly (168h)' : `${h} hours`

const form = ref({
  server_id: '',
  name: '',
  expected_interval_hours: 24,
  description: '',
})
const errors = ref<Record<string, string>>({})
const submitting = ref(false)

const editMode = computed(() => props.job != null)

const lockedServer = computed(() =>
  props.serverId ? serverStore.servers.find((s) => s.id === props.serverId) ?? null : null
)

function reset(): void {
  errors.value = {}
  if (props.job) {
    form.value = {
      server_id: props.job.server_id,
      name: props.job.name,
      expected_interval_hours: props.job.expected_interval_hours,
      description: props.job.description ?? '',
    }
  } else {
    form.value = {
      server_id: props.serverId ?? serverStore.servers[0]?.id ?? '',
      name: '',
      expected_interval_hours: 24,
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
  return Object.keys(errors.value).length === 0
}

async function submit(): Promise<void> {
  if (!validate()) return
  submitting.value = true
  try {
    const payload: BackupJobPayload = {
      server_id: form.value.server_id,
      name: form.value.name.trim(),
      expected_interval_hours: form.value.expected_interval_hours,
      description: form.value.description.trim() || null,
    }
    let saved: BackupJob
    if (editMode.value && props.job) {
      saved = await store.updateBackupJob(props.job.id, payload)
      notify.success('Backup job updated')
    } else {
      saved = await store.createBackupJob(payload)
      notify.success('Backup job created')
    }
    emit('saved', saved)
  } catch (err) {
    const msg = (err as { response?: { data?: { detail?: { message?: string } } } })?.response?.data?.detail?.message
    errors.value._form = msg ?? 'Could not save the job.'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal">
      <div class="modal-hdr">
        <h2>{{ editMode ? 'Edit' : 'Add' }} Backup Job</h2>
        <button class="close" @click="emit('close')">✕</button>
      </div>

      <form @submit.prevent="submit">
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

        <label>Expected Interval</label>
        <select v-model.number="form.expected_interval_hours">
          <option v-for="h in INTERVAL_OPTIONS" :key="h" :value="h">{{ intervalLabel(h) }}</option>
        </select>

        <label>Description</label>
        <input v-model="form.description" placeholder="Optional notes" />

        <div v-if="errors._form" class="err">{{ errors._form }}</div>

        <div class="actions">
          <button type="button" class="btn ghost" @click="emit('close')">Cancel</button>
          <button type="submit" class="primary" :disabled="submitting">
            {{ submitting ? 'Saving…' : editMode ? 'Save Changes' : 'Create Job' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 20px; }
.modal { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; width: 100%; max-width: 520px; max-height: 90vh; overflow-y: auto; }
.modal-hdr { padding: 18px 22px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
.modal-hdr h2 { font-size: 15px; color: #fff; }
.close { background: none; border: none; color: var(--muted); font-size: 18px; cursor: pointer; }
form { padding: 20px 22px; }
label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; margin-top: 14px; }
input, select { width: 100%; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; color: var(--text); font-size: 13px; outline: none; font-family: inherit; }
input:focus, select:focus { border-color: var(--accent); }
input.invalid, select.invalid { border-color: var(--red); }
input.locked { opacity: 0.6; cursor: not-allowed; }
.err { color: var(--red); font-size: 11px; margin-top: 6px; }
.actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 22px; padding-top: 14px; border-top: 1px solid var(--border); }
.primary { padding: 9px 18px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); color: #fff; border: none; border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; }
.primary:disabled { opacity: 0.6; cursor: wait; }
.btn { padding: 8px 16px; border-radius: 8px; font-size: 12px; cursor: pointer; border: 1px solid var(--border); background: var(--surface-2); color: var(--text); }
.btn.ghost:hover { border-color: var(--accent); color: var(--accent-2); }
</style>
