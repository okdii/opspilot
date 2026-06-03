<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useOrgStore } from '@/stores/org'
import { useServerStore } from '@/stores/server'
import { useCronBackupStore } from '@/stores/cronBackup'
import type { CronJob, BackupJob, CronJobPayload, BackupJobPayload } from '@/stores/cronBackup'
import { useNotify } from '@/composables/useNotify'
import { PageHeader, EmptyState } from '@/components/ui'
import JobRow from '@/components/cron-backup/JobRow.vue'
import JobDetailSlideOver from '@/components/cron-backup/JobDetailSlideOver.vue'
import { cronToLabel } from '@/components/cron-backup/cronLabel'

const orgStore = useOrgStore()
const serverStore = useServerStore()
const store = useCronBackupStore()
const notify = useNotify()

type Tab = 'cron' | 'backup'
const tab = ref<Tab>('cron')

const canEdit = computed(() => orgStore.canEdit)
const openMenuId = ref<string | null>(null)

// ── Detail slide-over ───────────────────────────────────────────────────────
const detailOpen = ref(false)
const detailJob = ref<CronJob | BackupJob | null>(null)
function openDetail(job: CronJob | BackupJob): void {
  detailJob.value = job
  detailOpen.value = true
  openMenuId.value = null
}
// Keep the open slide-over in sync after edits.
watch(
  () => [store.cronJobs, store.backupJobs],
  () => {
    if (!detailJob.value) return
    const list = tab.value === 'cron' ? store.cronJobs : store.backupJobs
    const fresh = list.find((j) => j.id === detailJob.value!.id)
    if (fresh) detailJob.value = fresh
  },
  { deep: true },
)

// ── Load data ───────────────────────────────────────────────────────────────
async function load(): Promise<void> {
  if (!orgStore.activeOrgId) {
    store.reset()
    return
  }
  const orgId = orgStore.activeOrgId
  await Promise.all([
    store.fetchCronJobs(orgId),
    store.fetchBackupJobs(orgId),
    serverStore.servers.length ? Promise.resolve() : serverStore.fetchByOrg(orgId),
  ])
}

onMounted(load)
watch(() => orgStore.activeOrgId, load)

// ── Keyboard shortcuts (spec §13) ────────────────────────────────────────────
function onKey(e: KeyboardEvent): void {
  const t = e.target as HTMLElement
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
  if (e.key === '1') tab.value = 'cron'
  else if (e.key === '2') tab.value = 'backup'
  else if (e.key === 'n' && canEdit.value) openAdd()
  else if (e.key === 'r') void load()
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

// ── Add / Edit modal ─────────────────────────────────────────────────────────
const showModal = ref(false)
const editMode = ref(false)
const editingId = ref<string | null>(null)
const submitting = ref(false)
const errors = ref<Record<string, string>>({})

const GRACE_OPTIONS = [5, 10, 15, 30, 60, 120, 240]
const INTERVAL_OPTIONS = [1, 6, 12, 24, 48, 168, 720]

const form = ref({
  server_id: '',
  name: '',
  schedule: '0 * * * *',
  grace_period_min: 10,
  expected_interval_hours: 24,
  description: '',
})

const schedulePreview = computed(() => cronToLabel(form.value.schedule))

function resetForm(): void {
  form.value = {
    server_id: serverStore.servers[0]?.id ?? '',
    name: '',
    schedule: tab.value === 'cron' ? '0 * * * *' : '0 2 * * *',
    grace_period_min: tab.value === 'cron' ? 10 : 30,
    expected_interval_hours: 24,
    description: '',
  }
  errors.value = {}
}

function openAdd(): void {
  editMode.value = false
  editingId.value = null
  resetForm()
  showModal.value = true
}

function openEdit(job: CronJob | BackupJob): void {
  editMode.value = true
  editingId.value = job.id
  errors.value = {}
  openMenuId.value = null
  if (tab.value === 'cron') {
    const j = job as CronJob
    form.value = {
      server_id: j.server_id,
      name: j.name,
      schedule: j.schedule,
      grace_period_min: j.grace_period_min,
      expected_interval_hours: 24,
      description: '',
    }
  } else {
    const j = job as BackupJob
    form.value = {
      server_id: j.server_id,
      name: j.name,
      schedule: '0 2 * * *',
      grace_period_min: 30,
      expected_interval_hours: j.expected_interval_hours,
      description: j.description ?? '',
    }
  }
  showModal.value = true
}

function validate(): boolean {
  errors.value = {}
  if (!form.value.server_id) errors.value.server_id = 'Select a server'
  const n = form.value.name.trim()
  if (n.length < 2 || n.length > 100) errors.value.name = 'Name must be 2–100 characters'
  if (tab.value === 'cron' && !schedulePreview.value.valid) errors.value.schedule = 'Invalid cron expression'
  return Object.keys(errors.value).length === 0
}

async function submit(): Promise<void> {
  if (!validate()) return
  submitting.value = true
  try {
    if (tab.value === 'cron') {
      const payload: CronJobPayload = {
        server_id: form.value.server_id,
        name: form.value.name.trim(),
        schedule: form.value.schedule.trim(),
        grace_period_min: form.value.grace_period_min,
      }
      if (editMode.value && editingId.value) {
        await store.updateCronJob(editingId.value, payload)
        notify.success('Cron job updated')
      } else {
        await store.createCronJob(payload)
        notify.success('Cron job created')
      }
    } else {
      const payload: BackupJobPayload = {
        server_id: form.value.server_id,
        name: form.value.name.trim(),
        expected_interval_hours: form.value.expected_interval_hours,
        description: form.value.description.trim() || null,
      }
      if (editMode.value && editingId.value) {
        await store.updateBackupJob(editingId.value, payload)
        notify.success('Backup job updated')
      } else {
        await store.createBackupJob(payload)
        notify.success('Backup job created')
      }
    }
    showModal.value = false
  } catch (err) {
    const msg = (err as { response?: { data?: { detail?: { message?: string } } } })?.response?.data?.detail?.message
    errors.value._form = msg ?? 'Could not save the job.'
  } finally {
    submitting.value = false
  }
}

// ── Delete ────────────────────────────────────────────────────────────────────
async function remove(job: CronJob | BackupJob): Promise<void> {
  openMenuId.value = null
  if (!window.confirm(`Delete "${job.name}"? This permanently removes its run history and stops the ping URL.`)) return
  try {
    if (tab.value === 'cron') await store.deleteCronJob(job.id)
    else await store.deleteBackupJob(job.id)
    notify.success('Job deleted')
    if (detailJob.value?.id === job.id) detailOpen.value = false
  } catch {
    notify.error('Could not delete the job.')
  }
}

// ── Derived lists ───────────────────────────────────────────────────────────
const jobs = computed<(CronJob | BackupJob)[]>(() =>
  tab.value === 'cron' ? store.sortedCronJobs : store.sortedBackupJobs,
)

const gracePresetLabel = (m: number) =>
  m < 60 ? `${m} min` : m === 60 ? '1 hour' : `${m / 60} hours`
const intervalLabel = (h: number) =>
  h < 24 ? `${h} hour${h > 1 ? 's' : ''}` : h === 24 ? 'Daily (24h)' : h === 168 ? 'Weekly (168h)' : `${h} hours`

const subtitle = computed(() => {
  const cron = store.cronJobs.length
  const backup = store.backupJobs.length
  const miss = store.totalMissingCount
  const parts = [`${cron} cron`, `${backup} backup`]
  if (miss) parts.push(`${miss} missing`)
  return parts.join(' • ')
})
</script>

<template>
  <div class="page" @click="openMenuId = null">
    <PageHeader title="Cron & Backup Jobs" :subtitle="subtitle">
      <template #actions>
        <button v-if="canEdit && serverStore.servers.length" class="primary" @click="openAdd">
          + Add {{ tab === 'cron' ? 'Cron' : 'Backup' }} Job
        </button>
      </template>
    </PageHeader>

    <!-- Tabs -->
    <div class="tabs">
      <button class="tab" :class="{ active: tab === 'cron' }" @click="tab = 'cron'">
        Cron Jobs
        <span class="count" :class="{ alert: store.missingCronCount > 0 }">{{ store.cronJobs.length }}</span>
      </button>
      <button class="tab" :class="{ active: tab === 'backup' }" @click="tab = 'backup'">
        Backup Jobs
        <span class="count" :class="{ alert: store.missingBackupCount > 0 }">{{ store.backupJobs.length }}</span>
      </button>
    </div>

    <!-- States -->
    <div v-if="store.isLoadingList && !jobs.length" class="state-note">Loading jobs…</div>

    <EmptyState
      v-else-if="!jobs.length"
      :title="tab === 'cron' ? 'No cron jobs registered yet' : 'No backup jobs registered yet'"
      :message="tab === 'cron'
        ? 'Monitor your scheduled scripts by adding a heartbeat check. OpsPilot alerts you if a job stops running on schedule.'
        : 'Track your backups by adding a heartbeat check with size and exit-code reporting.'"
    >
      <template #action>
        <button v-if="canEdit && serverStore.servers.length" class="primary" @click="openAdd">
          + Register Your First {{ tab === 'cron' ? 'Cron' : 'Backup' }} Job
        </button>
        <p v-else-if="!serverStore.servers.length" class="muted-note">Add a server first before registering jobs.</p>
      </template>
    </EmptyState>

    <!-- List -->
    <div v-else class="job-list">
      <JobRow
        v-for="job in jobs"
        :key="job.id"
        :job="job"
        :type="tab"
        :can-edit="canEdit"
        :menu-open="openMenuId === job.id"
        @detail="openDetail(job)"
        @edit="openEdit(job)"
        @delete="remove(job)"
        @toggle-menu="openMenuId = openMenuId === job.id ? null : job.id"
      />
    </div>

    <!-- Detail slide-over -->
    <JobDetailSlideOver
      v-model="detailOpen"
      :job="detailJob"
      :type="tab"
      :can-edit="canEdit"
      @edit="detailJob && openEdit(detailJob)"
    />

    <!-- Add / Edit modal -->
    <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
      <div class="modal">
        <div class="modal-hdr">
          <h2>{{ editMode ? 'Edit' : 'Add' }} {{ tab === 'cron' ? 'Cron' : 'Backup' }} Job</h2>
          <button class="close" @click="showModal = false">✕</button>
        </div>

        <form @submit.prevent="submit">
          <label>Server *</label>
          <select v-model="form.server_id" :class="{ invalid: errors.server_id }">
            <option v-for="s in serverStore.servers" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
          <div v-if="errors.server_id" class="err">{{ errors.server_id }}</div>

          <label>Job Name *</label>
          <input v-model="form.name" placeholder="e.g. database-backup" :class="{ invalid: errors.name }" />
          <div v-if="errors.name" class="err">{{ errors.name }}</div>

          <!-- Cron-specific -->
          <template v-if="tab === 'cron'">
            <label>Schedule (cron expression) *</label>
            <input v-model="form.schedule" placeholder="0 * * * *" class="mono" :class="{ invalid: errors.schedule }" />
            <div class="preview" :class="{ bad: !schedulePreview.valid }">
              {{ schedulePreview.valid ? `Runs: ${schedulePreview.label}` : 'Invalid cron expression' }}
            </div>
            <div v-if="errors.schedule" class="err">{{ errors.schedule }}</div>

            <label>Grace Period</label>
            <select v-model.number="form.grace_period_min">
              <option v-for="g in GRACE_OPTIONS" :key="g" :value="g">{{ gracePresetLabel(g) }}</option>
            </select>
          </template>

          <!-- Backup-specific -->
          <template v-else>
            <label>Expected Interval</label>
            <select v-model.number="form.expected_interval_hours">
              <option v-for="h in INTERVAL_OPTIONS" :key="h" :value="h">{{ intervalLabel(h) }}</option>
            </select>

            <label>Description</label>
            <input v-model="form.description" placeholder="Optional notes" />

            <div class="instructions">
              Add to the end of your backup script:
              <pre>curl -s -X POST {ping_url} -d "status=success&size_bytes=&lt;BYTES&gt;&exit_code=$?"</pre>
              The real ping URL appears in the job detail view after saving.
            </div>
          </template>

          <div v-if="errors._form" class="err">{{ errors._form }}</div>

          <div class="actions">
            <button type="button" class="btn ghost" @click="showModal = false">Cancel</button>
            <button type="submit" class="primary" :disabled="submitting">
              {{ submitting ? 'Saving…' : editMode ? 'Save Changes' : 'Create Job' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 28px; }
.muted-note { color: var(--muted); font-size: 13px; }
.state-note { color: var(--muted); padding: 40px 0; text-align: center; }

.tabs { display: flex; gap: 6px; margin-bottom: 20px; border-bottom: 1px solid var(--border); }
.tab { display: inline-flex; align-items: center; gap: 8px; background: none; border: none; border-bottom: 2px solid transparent; color: var(--muted); font-size: 13px; font-weight: 600; padding: 10px 14px; cursor: pointer; margin-bottom: -1px; }
.tab:hover { color: var(--text); }
.tab.active { color: #fff; border-bottom-color: var(--accent); }
.count { background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px; padding: 1px 8px; font-size: 11px; font-variant-numeric: tabular-nums; }
.count.alert { background: rgba(239, 68, 68, 0.18); color: var(--red); border-color: rgba(239, 68, 68, 0.4); }

.job-list { display: flex; flex-direction: column; gap: 10px; }

.primary { padding: 9px 18px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); color: #fff; border: none; border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; min-height: 38px; }
.primary:disabled { opacity: 0.6; cursor: wait; }
.btn { padding: 8px 16px; border-radius: 8px; font-size: 12px; cursor: pointer; border: 1px solid var(--border); background: var(--surface-2); color: var(--text); }
.btn.ghost:hover { border-color: var(--accent); color: var(--accent-2); }

.modal-overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 20px; }
.modal { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; width: 100%; max-width: 520px; max-height: 90vh; overflow-y: auto; }
.modal-hdr { padding: 18px 22px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
.modal-hdr h2 { font-size: 15px; color: #fff; }
.close { background: none; border: none; color: var(--muted); font-size: 18px; cursor: pointer; }
form { padding: 20px 22px; }
label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; margin-top: 14px; }
input, select { width: 100%; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; color: var(--text); font-size: 13px; outline: none; font-family: inherit; }
input.mono { font-family: ui-monospace, monospace; }
input:focus, select:focus { border-color: var(--accent); }
input.invalid, select.invalid { border-color: var(--red); }
.preview { font-size: 11px; color: var(--accent-2); margin-top: 6px; }
.preview.bad { color: var(--red); }
.instructions { margin-top: 16px; font-size: 11px; color: var(--muted); background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 12px; line-height: 1.6; }
.instructions pre { margin: 8px 0; font-family: ui-monospace, monospace; font-size: 10px; color: var(--green); white-space: pre-wrap; word-break: break-all; }
.err { color: var(--red); font-size: 11px; margin-top: 6px; }
.actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 22px; padding-top: 14px; border-top: 1px solid var(--border); }
</style>
