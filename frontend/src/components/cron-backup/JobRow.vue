<script setup lang="ts">
import { computed } from 'vue'
import { StatusBadge } from '@/components/ui'
import { cronToLabel } from './cronLabel'
import type { MonitoredJob } from '@/stores/jobs'

const props = defineProps<{
  job: MonitoredJob
  canEdit: boolean
  menuOpen: boolean
}>()

const emit = defineEmits<{
  (e: 'detail'): void
  (e: 'edit'): void
  (e: 'delete'): void
  (e: 'toggle-menu'): void
}>()

const cronLabel = computed(() => cronToLabel(props.job.schedule))
const scheduleText = computed(() => cronLabel.value?.label ?? props.job.schedule)
const scheduleInvalid = computed(() => cronLabel.value?.valid === false)

const sizeText = computed(() => {
  const job = props.job
  if (job.last_size_formatted != null) {
    if (job.last_files_count != null) {
      return `${job.last_size_formatted} · ${job.last_files_count.toLocaleString()} files`
    }
    return job.last_size_formatted
  }
  return '—'
})

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

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

function fmtDuration(sec: number | null | undefined): string {
  if (sec == null) return '—'
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return s ? `${m}m ${s}s` : `${m}m`
}

const lastRunStatus = computed(() => {
  const code = props.job.last_exit_code
  if (code == null || code === 0) return { text: '✓ Success', ok: true }
  return { text: `✗ Failed (exit ${code})`, ok: false }
})

const showStrip = computed(() => props.job.last_ping_at != null)

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
        <span class="mc-label">Size</span>
        <span class="mc-val">{{ sizeText }}</span>
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

    <!-- Last Run strip — shown once job has received at least one ping -->
    <div v-if="showStrip" class="last-run-strip" :class="{ 'strip-fail': !lastRunStatus.ok }">
      <span class="strip-title">Last Run</span>
      <div class="strip-divider"></div>
      <div class="run-cell">
        <span class="rc-label">Date</span>
        <span class="rc-val">{{ fmtDate(job.last_ping_at) }}</span>
      </div>
      <div class="run-cell">
        <span class="rc-label">Status</span>
        <span class="rc-val" :class="lastRunStatus.ok ? 'rc-ok' : 'rc-fail'">{{ lastRunStatus.text }}</span>
      </div>
      <div class="run-cell">
        <span class="rc-label">File</span>
        <span class="rc-val rc-mono">{{ job.last_label ?? '—' }}</span>
      </div>
      <div class="run-cell">
        <span class="rc-label">Size</span>
        <span class="rc-val">{{ job.last_size_formatted ?? '—' }}</span>
      </div>
      <div class="run-cell">
        <span class="rc-label">Duration</span>
        <span class="rc-val">{{ fmtDuration(job.last_duration_sec) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.job-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  transition: border-color 0.15s;
  overflow: hidden;
}
.job-row:hover { border-color: var(--accent); }
.job-row.missing { border-color: rgba(239, 68, 68, 0.4); }

/* top row — name + meta */
.row-main {
  display: flex;
  align-items: center;
  gap: 12px;
  background: none;
  border: none;
  padding: 14px 18px;
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

.row-meta { display: flex; align-items: center; gap: 18px; flex-shrink: 0; padding: 14px 18px; }
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

/* last-run strip */
.last-run-strip {
  width: 100%;
  border-top: 1px solid var(--border);
  padding: 9px 18px;
  background: rgba(255, 255, 255, 0.02);
  display: flex;
  align-items: flex-start;
  gap: 20px;
}
.last-run-strip.strip-fail { background: rgba(239, 68, 68, 0.04); }

.strip-title {
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--muted);
  align-self: center;
  white-space: nowrap;
  opacity: 0.7;
}
.strip-divider {
  width: 1px;
  height: 28px;
  background: var(--border);
  align-self: center;
  flex-shrink: 0;
}

.run-cell { display: flex; flex-direction: column; gap: 2px; }
.rc-label { font-size: 9px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); opacity: 0.7; }
.rc-val { font-size: 12px; color: var(--text); font-variant-numeric: tabular-nums; }
.rc-ok { color: var(--green); font-weight: 600; }
.rc-fail { color: var(--red); font-weight: 600; }
.rc-mono { font-family: ui-monospace, monospace; font-size: 11px; }

@media (max-width: 720px) {
  .row-meta { gap: 10px; }
  .meta-cell { min-width: 44px; }
  .last-run-strip { gap: 14px; flex-wrap: wrap; }
}
</style>
