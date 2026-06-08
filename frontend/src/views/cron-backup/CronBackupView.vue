<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useOrgStore } from '@/stores/org'
import { useServerStore } from '@/stores/server'
import { useJobsStore } from '@/stores/jobs'
import type { MonitoredJob } from '@/stores/jobs'
import { useNotify } from '@/composables/useNotify'
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

    <!-- List -->
    <div v-else class="job-list">
      <JobRow
        v-for="job in store.sortedJobs"
        :key="job.id"
        :job="job"
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
.muted-note { color: var(--muted); font-size: 13px; }
.state-note { color: var(--muted); padding: 40px 0; text-align: center; }

.job-list { display: flex; flex-direction: column; gap: 10px; }

.primary { padding: 9px 18px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); color: #fff; border: none; border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; min-height: 38px; }
.primary:disabled { opacity: 0.6; cursor: wait; }
</style>
