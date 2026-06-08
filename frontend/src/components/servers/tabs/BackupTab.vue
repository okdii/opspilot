<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useOrgStore } from '@/stores/org'
import { useCronBackupStore } from '@/stores/cronBackup'
import type { BackupJob } from '@/stores/cronBackup'
import { useNotify } from '@/composables/useNotify'
import { EmptyState } from '@/components/ui'
import JobRow from '@/components/cron-backup/JobRow.vue'
import JobDetailSlideOver from '@/components/cron-backup/JobDetailSlideOver.vue'
import JobModal from '@/components/cron-backup/JobModal.vue'

const route = useRoute()
const orgStore = useOrgStore()
const store = useCronBackupStore()
const notify = useNotify()

const serverId = computed(() => route.params.id as string)
const canEdit = computed(() => orgStore.canEdit)
const openMenuId = ref<string | null>(null)

// Jobs for this server only, inheriting sort order from the store getter.
const jobs = computed(() =>
  store.sortedBackupJobs.filter((j) => j.server_id === serverId.value)
)

// Load if the store is empty (e.g., arrived directly on this tab).
onMounted(async () => {
  if (!store.backupJobs.length && orgStore.activeOrgId) {
    await store.fetchBackupJobs(orgStore.activeOrgId)
  }
})

// Re-fetch when org changes.
watch(
  () => orgStore.activeOrgId,
  async (orgId) => {
    if (orgId) await store.fetchBackupJobs(orgId)
  },
)

// ── Detail slide-over ────────────────────────────────────────────────────────
const detailOpen = ref(false)
const detailJob = ref<BackupJob | null>(null)

function openDetail(job: BackupJob): void {
  detailJob.value = job
  detailOpen.value = true
  openMenuId.value = null
}

// Keep slide-over in sync after edits.
watch(
  () => store.backupJobs,
  () => {
    if (!detailJob.value) return
    const fresh = store.backupJobs.find((j) => j.id === detailJob.value!.id)
    if (fresh) detailJob.value = fresh
  },
  { deep: true },
)

// ── Add / Edit modal ─────────────────────────────────────────────────────────
const showModal = ref(false)
const editingJob = ref<BackupJob | null>(null)

function openAdd(): void {
  editingJob.value = null
  showModal.value = true
  openMenuId.value = null
}

function openEdit(job: BackupJob): void {
  editingJob.value = job
  showModal.value = true
  openMenuId.value = null
}

// ── Delete ───────────────────────────────────────────────────────────────────
async function remove(job: BackupJob): Promise<void> {
  openMenuId.value = null
  if (!window.confirm(`Delete "${job.name}"? This permanently removes its run history and stops the ping URL.`)) return
  try {
    await store.deleteBackupJob(job.id)
    notify.success('Job deleted')
    if (detailJob.value?.id === job.id) detailOpen.value = false
  } catch {
    notify.error('Could not delete the job.')
  }
}
</script>

<template>
  <div class="backup-tab" @click="openMenuId = null">
    <div class="tab-hdr">
      <span class="tab-title">Backup Jobs <span class="count">{{ jobs.length }}</span></span>
      <button v-if="canEdit" class="primary" @click="openAdd">+ Add Backup Job</button>
    </div>

    <div v-if="store.isLoadingList && !jobs.length" class="state-note">Loading…</div>

    <EmptyState
      v-else-if="!jobs.length"
      title="No backup jobs for this server"
      message="Track your rclone backups by adding a heartbeat check. OpsPilot alerts you if a job is missed or fails."
    >
      <template #action>
        <button v-if="canEdit" class="primary" @click="openAdd">+ Add Backup Job</button>
      </template>
    </EmptyState>

    <div v-else class="job-list">
      <JobRow
        v-for="job in jobs"
        :key="job.id"
        :job="job"
        type="backup"
        :can-edit="canEdit"
        :menu-open="openMenuId === job.id"
        @detail="openDetail(job)"
        @edit="openEdit(job)"
        @delete="remove(job)"
        @toggle-menu="openMenuId = openMenuId === job.id ? null : job.id"
      />
    </div>

    <JobDetailSlideOver
      v-model="detailOpen"
      :job="detailJob"
      type="backup"
      :can-edit="canEdit"
      @edit="detailJob && openEdit(detailJob)"
    />

    <JobModal
      v-if="showModal"
      :job="editingJob"
      :server-id="serverId"
      @saved="showModal = false"
      @close="showModal = false"
    />
  </div>
</template>

<style scoped>
.backup-tab { padding: 4px 0; }
.tab-hdr { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.tab-title { font-size: 13px; font-weight: 600; color: var(--text); }
.count { background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px; padding: 1px 8px; font-size: 11px; margin-left: 8px; font-variant-numeric: tabular-nums; }
.state-note { color: var(--muted); padding: 40px 0; text-align: center; font-size: 13px; }
.job-list { display: flex; flex-direction: column; gap: 10px; }
.primary { padding: 8px 16px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); color: #fff; border: none; border-radius: 8px; font-weight: 600; font-size: 12px; cursor: pointer; }
</style>
