<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useOrgStore } from '@/stores/org'
import { useServerStore } from '@/stores/server'
import { useJobsStore } from '@/stores/jobs'
import type { MonitoredJob } from '@/stores/jobs'
import { useNotify } from '@/composables/useNotify'
import { fmtDuration } from '@/utils/time'
import { PageHeader, EmptyState } from '@/components/ui'
import JobRow from '@/components/cron-backup/JobRow.vue'
import JobDetailSlideOver from '@/components/cron-backup/JobDetailSlideOver.vue'
import JobModal from '@/components/cron-backup/JobModal.vue'

const orgStore = useOrgStore()
const serverStore = useServerStore()
const store = useJobsStore()
const notify = useNotify()

const canEdit = computed(() => orgStore.canEdit)
const openMenuId = ref<string | null>(null)

// ── Detail slide-over ───────────────────────────────────────────────────────
const detailOpen = ref(false)
const detailJob = ref<MonitoredJob | null>(null)

function openDetail(job: MonitoredJob): void {
  detailJob.value = job
  detailOpen.value = true
  openMenuId.value = null
}

// Keep the open slide-over in sync after edits.
watch(
  () => store.jobs,
  () => {
    if (!detailJob.value) return
    const fresh = store.jobs.find((j) => j.id === detailJob.value!.id)
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
    store.fetchJobs(orgId),
    store.fetchTodayRuns(orgId),
    serverStore.servers.length ? Promise.resolve() : serverStore.fetchByOrg(orgId),
  ])
}

onMounted(load)
watch(() => orgStore.activeOrgId, load)

// ── Keyboard shortcuts (spec §13) ────────────────────────────────────────────
function onKey(e: KeyboardEvent): void {
  const t = e.target as HTMLElement
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
  if (e.key === 'n' && canEdit.value) openAdd()
  else if (e.key === 'r') void load()
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

// ── Add / Edit modal ─────────────────────────────────────────────────────────
const showModal = ref(false)
const editingJob = ref<MonitoredJob | null>(null)

function openAdd(): void {
  editingJob.value = null
  showModal.value = true
}

function openEdit(job: MonitoredJob): void {
  editingJob.value = job
  showModal.value = true
  openMenuId.value = null
}

// ── Delete ────────────────────────────────────────────────────────────────────
async function remove(job: MonitoredJob): Promise<void> {
  openMenuId.value = null
  if (!window.confirm(`Delete "${job.name}"? This permanently removes its run history and stops the ping URL.`)) return
  try {
    await store.deleteJob(job.id)
    notify.success('Job deleted')
    if (detailJob.value?.id === job.id) detailOpen.value = false
  } catch {
    notify.error('Could not delete the job.')
  }
}

// ── Today's Backups panel helpers ─────────────────────────────────────────────
const todayLabel = computed(() => {
  return new Date().toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
})

const todayFailedCount = computed(() =>
  store.todayRuns.filter((r) => r.outcome !== 'success').length
)

function fmtTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function groupStatusCount(group: { jobs: MonitoredJob[] }, status: string): number {
  return group.jobs.filter((j) => j.status === status).length
}

// ── Subtitle ─────────────────────────────────────────────────────────────────
const subtitle = computed(() => {
  const total = store.jobs.length
  const miss = store.missingCount
  const parts = [`${total} job${total !== 1 ? 's' : ''}`]
  if (miss) parts.push(`${miss} missing`)
  return parts.join(' • ')
})
</script>

<template>
  <div class="page" @click="openMenuId = null">
    <PageHeader title="Cron & Backup Jobs" :subtitle="subtitle">
      <template #actions>
        <button v-if="canEdit && serverStore.servers.length" class="primary" @click="openAdd">
          + Add Job
        </button>
      </template>
    </PageHeader>

    <!-- Today's Backups panel -->
    <div v-if="store.todayRuns.length > 0" class="today-panel">
      <div class="today-hd">
        <span class="today-title">Today's Backups</span>
        <span class="today-chip">{{ todayLabel }}</span>
        <span class="today-badge">{{ store.todayRuns.length }} run{{ store.todayRuns.length !== 1 ? 's' : '' }}</span>
        <span v-if="todayFailedCount > 0" class="today-badge fail">{{ todayFailedCount }} failed</span>
      </div>
      <table class="today-table">
        <thead>
          <tr>
            <th></th>
            <th>File</th>
            <th>Job</th>
            <th>Started</th>
            <th>Duration</th>
            <th>Size</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in store.todayRuns" :key="r.id" :class="{ 'row-fail': r.outcome !== 'success' }">
            <td class="icon-col">
              <span :class="r.outcome === 'success' ? 'icon-ok' : 'icon-fail'">
                {{ r.outcome === 'success' ? '✓' : '✗' }}
              </span>
            </td>
            <td class="mono label-col">{{ r.label ?? '—' }}</td>
            <td class="job-col">
              <span class="job-name">{{ r.job_name }}</span>
              <span class="server-name">{{ r.server_name }}</span>
            </td>
            <td class="mono">{{ fmtTime(r.started_at) }}</td>
            <td>{{ fmtDuration(r.duration_sec) }}</td>
            <td>{{ r.size_formatted ?? '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- States -->
    <div v-if="store.isLoadingList && !store.jobs.length" class="state-note">Loading jobs…</div>

    <EmptyState
      v-else-if="!store.jobs.length"
      title="No jobs registered yet"
      message="Add a heartbeat check to monitor any scheduled script. OpsPilot alerts you if a job stops running on schedule."
    >
      <template #action>
        <button v-if="canEdit && serverStore.servers.length" class="primary" @click="openAdd">
          + Add Your First Job
        </button>
        <p v-else-if="!serverStore.servers.length" class="muted-note">Add a server first before registering jobs.</p>
      </template>
    </EmptyState>

    <!-- List grouped by server -->
    <div v-else class="server-groups">
      <div
        v-for="group in store.jobsGroupedByServer"
        :key="group.server_id"
        class="server-group"
        :class="`group-${group.worstStatus}`"
      >
        <div class="group-hd">
          <span class="dot" :class="`dot-${group.worstStatus}`"></span>
          <span class="group-name">{{ group.server_name }}</span>
          <span class="group-count">{{ group.jobs.length }} job{{ group.jobs.length !== 1 ? 's' : '' }}</span>
          <span
            v-if="group.worstStatus === 'missing'"
            class="group-badge badge-missing"
          >{{ groupStatusCount(group, 'missing') }} missing</span>
          <span
            v-else-if="group.worstStatus === 'late'"
            class="group-badge badge-late"
          >{{ groupStatusCount(group, 'late') }} late</span>
          <span v-else class="group-badge badge-healthy">all healthy</span>
        </div>
        <div class="group-jobs">
          <JobRow
            v-for="job in group.jobs"
            :key="job.id"
            :job="job"
            :can-edit="canEdit"
            :menu-open="openMenuId === job.id"
            :hide-server="true"
            @detail="openDetail(job)"
            @edit="openEdit(job)"
            @delete="remove(job)"
            @toggle-menu="openMenuId = openMenuId === job.id ? null : job.id"
          />
        </div>
      </div>
    </div>

    <!-- Detail slide-over -->
    <JobDetailSlideOver
      v-model="detailOpen"
      :job="detailJob"
      :can-edit="canEdit"
      @edit="detailJob && openEdit(detailJob)"
    />

    <!-- Add / Edit modal -->
    <JobModal
      v-if="showModal"
      :job="editingJob"
      @saved="showModal = false"
      @close="showModal = false"
    />
  </div>
</template>

<style scoped>
.page { padding: 28px; }
@media (max-width: 1023px) { .page { padding: 20px; } }
@media (max-width: 767px)  { .page { padding: 14px; } }
.muted-note { color: var(--muted); font-size: 13px; }
.state-note { color: var(--muted); padding: 40px 0; text-align: center; }

/* Server group cards */
.server-groups { display: flex; flex-direction: column; gap: 14px; }

.server-group {
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}
.server-group.group-missing { border-color: rgba(239, 68, 68, 0.4); }
.server-group.group-late    { border-color: rgba(245, 158, 11, 0.4); }

.group-hd {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 18px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.group-hd .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.group-hd .dot-healthy { background: var(--green); box-shadow: 0 0 8px rgba(34, 197, 94, 0.5); }
.group-hd .dot-late    { background: var(--amber); }
.group-hd .dot-missing { background: var(--red);   box-shadow: 0 0 8px rgba(239, 68, 68, 0.5); }
.group-hd .dot-paused  { background: var(--grey); }

.group-name {
  font-size: 13px;
  font-weight: 700;
  color: #fff;
}
.group-count {
  font-size: 10px;
  color: var(--muted);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 1px 7px;
}
.group-badge {
  font-size: 10px;
  border-radius: 10px;
  padding: 2px 8px;
}
.badge-missing { color: #fca5a5; background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.3); }
.badge-late    { color: #fcd34d; background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.3); }
.badge-healthy { color: #86efac; background: rgba(34, 197, 94, 0.1);   border: 1px solid rgba(34, 197, 94, 0.3);  }

.group-jobs {
  display: flex;
  flex-direction: column;
  gap: 0;
}

/* JobRows inside a server card: remove outer border-radius + side borders so rows blend into the card */
.group-jobs :deep(.job-row) {
  border-radius: 0;
  border-left: none;
  border-right: none;
  border-top: none;
  border-bottom: 1px solid var(--border);
}
.group-jobs :deep(.job-row):last-child {
  border-bottom: none;
}
.group-jobs :deep(.job-row.missing) {
  border-bottom-color: rgba(239, 68, 68, 0.2);
}

.primary { padding: 9px 18px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); color: #fff; border: none; border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; min-height: 38px; }
.primary:disabled { opacity: 0.6; cursor: wait; }

/* Today's Backups panel */
.today-panel {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 18px;
}

.today-hd {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.today-title {
  font-size: 13px;
  font-weight: 600;
  color: #fff;
}

.today-chip {
  font-size: 11px;
  color: var(--muted);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 7px;
}

.today-badge {
  font-size: 11px;
  color: var(--text);
  background: rgba(99, 102, 241, 0.15);
  border: 1px solid rgba(99, 102, 241, 0.3);
  border-radius: 10px;
  padding: 2px 8px;
}

.today-badge.fail {
  color: #fca5a5;
  background: rgba(239, 68, 68, 0.12);
  border-color: rgba(239, 68, 68, 0.3);
}

.today-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.today-table th {
  text-align: left;
  color: var(--muted);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 5px 8px;
  border-bottom: 1px solid var(--border);
}

.today-table td {
  padding: 7px 8px;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  vertical-align: middle;
}

.today-table tbody tr:last-child td {
  border-bottom: none;
}

.today-table .row-fail td {
  background: rgba(239, 68, 68, 0.04);
}

.icon-col { width: 28px; }

.icon-ok {
  color: var(--green, #4ade80);
  font-weight: 700;
  font-size: 13px;
}

.icon-fail {
  color: #f87171;
  font-weight: 700;
  font-size: 13px;
}

.label-col {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, monospace;
  font-size: 11px;
  color: var(--text);
}

.job-col {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.job-name {
  color: var(--text);
  font-size: 12px;
}

.server-name {
  color: var(--muted);
  font-size: 10px;
}

.mono {
  font-family: ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
}
</style>
