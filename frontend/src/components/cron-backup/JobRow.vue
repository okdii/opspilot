<script setup lang="ts">
import { computed } from 'vue'
import { StatusBadge } from '@/components/ui'
import { cronToLabel } from './cronLabel'
import type { CronJob, BackupJob } from '@/stores/cronBackup'

/**
 * One job card row, shared by both tabs (spec 09 §4.1).
 * Status dot + name + server + schedule label + StatusBadge + last ping +
 * duration/size + next-expected. Kebab emits edit / detail / delete.
 */
const props = defineProps<{
  job: CronJob | BackupJob
  type: 'cron' | 'backup'
  canEdit: boolean
  menuOpen: boolean
}>()

const emit = defineEmits<{
  (e: 'detail'): void
  (e: 'edit'): void
  (e: 'delete'): void
  (e: 'toggle-menu'): void
}>()

const isCron = computed(() => props.type === 'cron')

const cronLabel = computed(() => {
  if (!isCron.value) return null
  return cronToLabel((props.job as CronJob).schedule)
})

const scheduleText = computed(() => {
  if (isCron.value) return cronLabel.value?.label ?? ''
  return `Every ${(props.job as BackupJob).expected_interval_hours}h`
})

const scheduleInvalid = computed(() => isCron.value && cronLabel.value?.valid === false)

const durationText = computed(() => {
  if (isCron.value) {
    const d = (props.job as CronJob).last_duration_sec
    if (d == null) return '—'
    if (d < 60) return `${d}s`
    const m = Math.floor(d / 60)
    const s = d % 60
    return s ? `${m}m ${s}s` : `${m}m`
  }
  const bj = props.job as BackupJob
  const size = bj.last_size_formatted ?? '—'
  if (bj.last_files_count != null) {
    return `${size} · ${bj.last_files_count.toLocaleString()} files`
  }
  return size
})

const durationLabel = computed(() => (isCron.value ? 'Duration' : 'Size'))

function relativeTime(iso: string | null): string {
  if (!iso) return 'never'
  const diff = Date.now() - new Date(iso).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

const nextExpected = computed(() => {
  const iso = props.job.next_expected_at
  if (!iso) return { text: '—', overdue: false }
  const diff = new Date(iso).getTime() - Date.now()
  if (diff <= 0) return { text: 'Overdue', overdue: true }
  const m = Math.floor(diff / 60000)
  if (m < 60) return { text: `in ${m}m`, overdue: false }
  const h = Math.floor(m / 60)
  if (h < 24) return { text: `in ${h}h`, overdue: false }
  return { text: `in ${Math.floor(h / 24)}d`, overdue: false }
})

const dotClass = computed(() => `dot-${props.job.status}`)
</script>

<template>
  <div class="job-row" :class="{ missing: job.status === 'missing' }">
    <button class="row-main" @click="emit('detail')">
      <span class="dot" :class="dotClass"></span>
      <div class="row-id">
        <span class="job-name">{{ job.name }}</span>
        <span class="job-sub">
          {{ job.server_name }}
          <span class="sep">·</span>
          <span :class="{ 'sched-bad': scheduleInvalid }" :title="scheduleInvalid ? 'Invalid cron expression' : ''">
            {{ scheduleText }}
          </span>
        </span>
      </div>
    </button>

    <div class="row-meta">
      <StatusBadge kind="job" :status="job.status" />
      <div class="meta-cell">
        <span class="mc-label">Last</span>
        <span class="mc-val">{{ relativeTime(job.last_ping_at) }}</span>
      </div>
      <div class="meta-cell">
        <span class="mc-label">{{ durationLabel }}</span>
        <span class="mc-val">{{ durationText }}</span>
      </div>
      <div class="meta-cell">
        <span class="mc-label">Next</span>
        <span class="mc-val" :class="{ overdue: nextExpected.overdue }">{{ nextExpected.text }}</span>
      </div>

      <div class="menu-wrap" @click.stop>
        <button class="kebab" aria-label="Job actions" @click="emit('toggle-menu')">⋮</button>
        <div v-if="menuOpen" class="kebab-menu">
          <button class="kmi" @click="emit('detail')">View Detail</button>
          <button v-if="canEdit" class="kmi" @click="emit('edit')">Edit</button>
          <template v-if="canEdit">
            <div class="kmi-div"></div>
            <button class="kmi danger" @click="emit('delete')">Delete</button>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.job-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  transition: border-color 0.15s;
}
.job-row:hover { border-color: var(--accent); }
.job-row.missing { border-color: rgba(239, 68, 68, 0.4); }

.row-main {
  display: flex;
  align-items: center;
  gap: 12px;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  text-align: left;
  min-width: 0;
  flex: 1;
}
.dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
.dot-healthy { background: var(--green); box-shadow: 0 0 8px rgba(34, 197, 94, 0.6); }
.dot-late { background: var(--amber); }
.dot-missing { background: var(--red); box-shadow: 0 0 8px rgba(239, 68, 68, 0.5); }
.dot-paused { background: var(--grey); }

.row-id { min-width: 0; }
.job-name { display: block; font-weight: 600; color: #fff; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.job-sub { display: block; font-size: 12px; color: var(--muted); margin-top: 2px; }
.sep { margin: 0 6px; opacity: 0.5; }
.sched-bad { color: var(--amber); }

.row-meta { display: flex; align-items: center; gap: 18px; flex-shrink: 0; }
.meta-cell { display: flex; flex-direction: column; align-items: flex-end; min-width: 56px; }
.mc-label { font-size: 9px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); opacity: 0.7; }
.mc-val { font-size: 12px; color: var(--text); font-variant-numeric: tabular-nums; }
.mc-val.overdue { color: var(--red); font-weight: 600; }

.menu-wrap { position: relative; }
.kebab { background: none; border: none; color: var(--muted); font-size: 16px; cursor: pointer; padding: 2px 6px; border-radius: 6px; line-height: 1; }
.kebab:hover { background: var(--surface-2); color: var(--text); }
.kebab-menu { position: absolute; top: 100%; right: 0; margin-top: 4px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 4px 0; min-width: 160px; z-index: 50; box-shadow: 0 12px 30px rgba(0, 0, 0, 0.4); }
.kmi { display: block; width: 100%; text-align: left; background: none; border: none; color: var(--text); font-size: 12px; padding: 8px 14px; cursor: pointer; }
.kmi:hover { background: rgba(99, 102, 241, 0.1); color: var(--accent-2); }
.kmi.danger { color: #fca5a5; }
.kmi.danger:hover { background: rgba(239, 68, 68, 0.1); color: var(--red); }
.kmi-div { height: 1px; background: var(--border); margin: 2px 0; }

@media (max-width: 720px) {
  .row-meta { gap: 10px; }
  .meta-cell { min-width: 44px; }
}
</style>
