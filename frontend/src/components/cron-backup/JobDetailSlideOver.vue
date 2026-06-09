<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { SlideOver, StatusBadge } from '@/components/ui'
import MetricChart from '@/components/charts/MetricChart.vue'
import { useNotify } from '@/composables/useNotify'
import { useDateFormat } from '@/composables/useDateFormat'
import { useJobsStore } from '@/stores/jobs'
import type { MonitoredJob, JobRun } from '@/stores/jobs'
import { cronToLabel } from './cronLabel'
import CalendarHeatmap from './CalendarHeatmap.vue'
import { relativeTime, fmtDuration } from '@/utils/time'

/**
 * Job detail slide-over for the unified MonitoredJob system (spec §7.5).
 * rclone snippet block (always with two tabs), 30-day calendar heatmap,
 * size/duration trend chart, and all-column run history table.
 * Reuses ui/SlideOver, StatusBadge, MetricChart.
 */
const props = defineProps<{
  modelValue: boolean
  job: MonitoredJob | null
  canEdit: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'edit'): void
}>()

const store = useJobsStore()
const notify = useNotify()
const { formatDateTime: fmtDateTime } = useDateFormat()

const runs = ref<JobRun[]>([])
const cursor = ref<string | null>(null)
const hasMore = ref(false)
const loadingRuns = ref(false)
const showRegenConfirm = ref(false)
const regenerating = ref(false)

const cronLabel = computed(() => {
  if (!props.job) return null
  return cronToLabel(props.job.schedule)
})

const scheduleText = computed(() => {
  if (!props.job) return ''
  return cronLabel.value?.label ?? props.job.schedule
})

const graceText = computed(() => {
  if (!props.job) return null
  return `Grace: ${props.job.grace_period_min} min`
})

const pingUrl = computed(() => props.job?.ping_url ?? '')

const nextExpectedText = computed(() => {
  const iso = props.job?.next_expected_at
  if (!iso) return '—'
  const dt = fmtDateTime(iso)
  const diff = new Date(iso).getTime() - Date.now()
  if (diff <= 0) return `${dt} (overdue)`
  const h = Math.round(diff / 3600000)
  return h < 24 ? `${dt} (in ${h}h)` : `${dt} (in ${Math.round(h / 24)}d)`
})

// ── Charts ────────────────────────────────────────────────────────────────
const hasSize = computed(() => runs.value.some((r) => r.size_bytes != null))
const hasDuration = computed(() => runs.value.some((r) => r.duration_sec != null))
const hasTrendData = computed(() => hasSize.value || hasDuration.value)

const trendSeries = computed(() => {
  // Oldest → newest for a left-to-right time axis.
  const ordered = [...runs.value].reverse()
  if (hasSize.value) {
    return [{
      name: 'Size',
      data: ordered
        .filter((r) => r.size_bytes != null)
        .map((r) => ({ x: new Date(r.ran_at).getTime(), y: r.size_bytes as number })),
    }]
  }
  return [{
    name: 'Duration',
    data: ordered
      .filter((r) => r.duration_sec != null)
      .map((r) => ({ x: new Date(r.ran_at).getTime(), y: r.duration_sec as number })),
  }]
})

const trendTitle = computed(() => (hasSize.value ? 'Backup Size Trend' : 'Duration Trend'))
const trendUnit = computed(() => (hasSize.value ? 'bytes/s' : 'count'))

// ── Run history ───────────────────────────────────────────────────────────
async function loadRuns(reset = true): Promise<void> {
  if (!props.job) return
  loadingRuns.value = true
  try {
    const res = await store.fetchRuns(props.job.id, reset ? null : cursor.value)
    runs.value = reset ? res.runs : [...runs.value, ...res.runs]
    cursor.value = res.next_cursor
    hasMore.value = !!res.next_cursor
  } catch {
    notify.error('Could not load run history.')
  } finally {
    loadingRuns.value = false
  }
}

watch(
  () => [props.modelValue, props.job?.id],
  ([open]) => {
    if (open && props.job) {
      runs.value = []
      cursor.value = null
      hasMore.value = false
      void loadRuns(true)
    }
  },
  { immediate: true },
)

// ── Ping URL / snippet actions ────────────────────────────────────────────
async function copy(text: string, label: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    notify.success(`${label} copied to clipboard`)
  } catch {
    notify.error('Copy failed — copy it manually.')
  }
}

const snippetTab = ref<'snippet' | 'curl'>('snippet')

const rcloneSnippet = computed(() => {
  const url = pingUrl.value
  return [
    '#!/bin/bash',
    '# OpsPilot backup monitoring wrapper — use as a standalone script.',
    '# Option A: save as a new .sh file and point your cron job here.',
    '# Option B: copy only the retry block + curl ping into your existing script.',
    '#   If integrating: capture EXIT_CODE=$? immediately after rclone,',
    '#   and place the curl ping as the last line before exit.',
    '',
    'REMOTE="gdrive:YOUR_REMOTE_PATH"    # ← set your rclone remote:path',
    'SOURCE="/your/source/path"           # ← set your local source directory',
    'MAX_RETRIES=3',
    'RETRY_DELAY=60                       # seconds to wait between retries',
    '',
    '# Run rclone with auto-retry',
    'EXIT_CODE=1',
    'ATTEMPT=0',
    'while [ $ATTEMPT -lt $MAX_RETRIES ]; do',
    '  ATTEMPT=$((ATTEMPT + 1))',
    '  rclone sync "$SOURCE" "$REMOTE"',
    '  EXIT_CODE=$?',
    '  [ $EXIT_CODE -eq 0 ] && break',
    '  [ $ATTEMPT -lt $MAX_RETRIES ] && sleep $RETRY_DELAY',
    'done',
    '',
    '# Query destination size and file count',
    'JSON=$(rclone size "$REMOTE" --json 2>/dev/null)',
    "SIZE_BYTES=$(echo \"$JSON\" | grep -o '\"bytes\":[0-9]*' | grep -o '[0-9]*$')",
    "FILES_COUNT=$(echo \"$JSON\" | grep -o '\"count\":[0-9]*' | grep -o '[0-9]*$')",
    '',
    '# Ping OpsPilot — exit_code != 0 fires a backup_failure alert + email',
    'BACKUP_FILE="${REMOTE}"          # ← set to output archive path if writing a file',
    '',
    `curl -s -X POST "${url}" \\`,
    '  -d "status=success&size_bytes=${SIZE_BYTES:-0}&exit_code=${EXIT_CODE}&files_count=${FILES_COUNT:-0}&label=$(basename ${BACKUP_FILE})" \\',
    '  > /dev/null',
    '',
    'exit $EXIT_CODE',
  ].join('\n')
})

const curlOnlySnippet = computed(() => {
  const url = pingUrl.value
  return [
    '# Add these lines at the end of your backup script.',
    '# IMPORTANT: capture $? immediately after rclone, before any other command.',
    'EXIT_CODE=$?',
    'JSON=$(rclone size "YOUR_REMOTE:YOUR_PATH" --json 2>/dev/null)',
    "SIZE_BYTES=$(echo \"$JSON\" | grep -o '\"bytes\":[0-9]*' | grep -o '[0-9]*$')",
    "FILES_COUNT=$(echo \"$JSON\" | grep -o '\"count\":[0-9]*' | grep -o '[0-9]*$')",
    '# Optional: pass the backup filename for display in OpsPilot',
    'label="$(basename /path/to/your_backup.tar.gz)"',
    `curl -s -X POST "${url}" \\`,
    '  -d "exit_code=$EXIT_CODE&size_bytes=${SIZE_BYTES:-0}&files_count=${FILES_COUNT:-0}&label=$label" \\',
    '  > /dev/null',
  ].join('\n')
})

const activeSnippet = computed(() =>
  snippetTab.value === 'snippet' ? rcloneSnippet.value : curlOnlySnippet.value
)

async function confirmRegenerate(): Promise<void> {
  if (!props.job) return
  regenerating.value = true
  try {
    await store.regenerateToken(props.job.id)
    notify.success('Ping URL regenerated — update your scripts.')
    showRegenConfirm.value = false
  } catch {
    notify.error('Could not regenerate the ping URL.')
  } finally {
    regenerating.value = false
  }
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

const jobTodayRuns = computed(() => {
  if (!props.job) return []
  return store.todayRuns.filter((r) => r.job_id === props.job!.id)
})

const jobTodayIds = computed(() =>
  new Set(jobTodayRuns.value.map((r) => r.id))
)

const jobTodayFailedCount = computed(() =>
  jobTodayRuns.value.filter((r) => r.outcome !== 'success').length
)

const todayLabel = computed(() =>
  new Date().toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
)

const earlierRuns = computed(() =>
  runs.value.filter((r) => !jobTodayIds.value.has(r.id))
)
</script>

<template>
  <SlideOver
    :model-value="modelValue"
    width="640px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div v-if="job" class="hdr">
        <div class="hdr-top">
          <h2>{{ job.name }}</h2>
          <button v-if="canEdit" class="btn ghost sm" @click="emit('edit')">Edit</button>
        </div>
        <p class="hdr-line">
          {{ job.server_name }}
          <span class="sep">·</span> {{ scheduleText }}
          <template v-if="graceText"><span class="sep">·</span> {{ graceText }}</template>
        </p>
        <p class="hdr-line">
          <StatusBadge kind="job" :status="job.status" />
          <span class="sep">·</span> Last ping: {{ relativeTime(job.last_ping_at) }}
        </p>
        <p class="hdr-line muted">Next expected: {{ nextExpectedText }}</p>
      </div>
    </template>

    <div v-if="job" class="body">
      <!-- Snippet block: rclone snippet / curl only tabs -->
      <section class="block ping-block">
        <div class="block-hd">
          <h3>Integration Snippet</h3>
          <button v-if="canEdit" class="link-danger" @click="showRegenConfirm = true">Regenerate</button>
        </div>
        <div class="snippet-tabs">
          <button
            class="stab"
            :class="{ active: snippetTab === 'snippet' }"
            @click="snippetTab = 'snippet'"
          >Standalone script</button>
          <button
            class="stab"
            :class="{ active: snippetTab === 'curl' }"
            @click="snippetTab = 'curl'"
          >Add to existing script</button>
        </div>
        <pre class="curl">{{ activeSnippet }}</pre>
        <div class="ping-actions">
          <button class="btn ghost sm" @click="copy(activeSnippet, 'Snippet')">Copy snippet</button>
          <button class="btn ghost sm" @click="copy(pingUrl, 'Ping URL')">Copy URL</button>
        </div>
        <p class="hint">
          <strong>Standalone:</strong> save as a new <code>.sh</code> file, fill in <code>REMOTE</code> and <code>SOURCE</code>, point your cron job here. &nbsp;
          <strong>Existing script:</strong> paste only the curl ping block at the end — <code>EXIT_CODE=$?</code> must come immediately after your rclone call.
          The UUID in the URL is the only authentication.
        </p>
      </section>

      <!-- Calendar heatmap -->
      <section class="block">
        <h3>Last 30 Days</h3>
        <CalendarHeatmap :runs="runs" :show-size="true" />
      </section>

      <!-- Trend chart -->
      <section class="block">
        <h3>{{ trendTitle }}</h3>
        <MetricChart
          v-if="hasTrendData"
          type="line"
          :series="trendSeries"
          :unit="trendUnit"
          :height="220"
        />
        <p v-else class="empty-note">No trend data yet.</p>
      </section>

      <!-- Run history -->
      <section class="block">
        <div class="rh-hdr">
          <h3>Run History</h3>
          <template v-if="jobTodayRuns.length > 0">
            <span class="today-chip">{{ todayLabel }}</span>
            <span class="today-badge">{{ jobTodayRuns.length }} run{{ jobTodayRuns.length !== 1 ? 's' : '' }} today</span>
            <span v-if="jobTodayFailedCount > 0" class="today-badge fail">{{ jobTodayFailedCount }} failed</span>
          </template>
        </div>
        <table v-if="jobTodayRuns.length > 0 || earlierRuns.length > 0" class="runs">
          <thead>
            <tr>
              <th></th>
              <th>File</th>
              <th>Started</th>
              <th>Ended</th>
              <th>Duration</th>
              <th>Size</th>
              <th>Files</th>
              <th>Exit</th>
            </tr>
          </thead>
          <tbody>
            <!-- Today group: pinned at top, sourced from store.todayRuns filtered by job.id -->
            <template v-if="jobTodayRuns.length > 0">
              <tr class="group-label today-group">
                <td colspan="8">▸ Today</td>
              </tr>
              <tr
                v-for="r in jobTodayRuns"
                :key="r.id"
                :class="r.outcome === 'success' ? 'today-row' : 'today-row-fail'"
              >
                <td class="icon-col">
                  <span :class="r.outcome === 'success' ? 'run-ok' : 'run-fail'">
                    {{ r.outcome === 'success' ? '✓' : '✗' }}
                  </span>
                </td>
                <td class="mono run-label">{{ r.label ?? '—' }}</td>
                <td class="mono">{{ fmtTime(r.started_at) }}</td>
                <td class="mono">{{ fmtTime(r.ran_at) }}</td>
                <td>{{ fmtDuration(r.duration_sec) }}</td>
                <td>{{ r.size_formatted ?? '—' }}</td>
                <td class="num">{{ r.files_count != null ? r.files_count.toLocaleString() : '—' }}</td>
                <td>{{ r.exit_code != null ? r.exit_code : '—' }}</td>
              </tr>
              <tr v-if="earlierRuns.length > 0" class="group-label earlier-group">
                <td colspan="8">Earlier</td>
              </tr>
            </template>
            <!-- Earlier runs: paginated, excludes IDs already shown in today group -->
            <tr v-for="r in earlierRuns" :key="r.id">
              <td class="icon-col">
                <span :class="r.outcome === 'success' ? 'run-ok' : 'run-fail'">
                  {{ r.outcome === 'success' ? '✓' : '✗' }}
                </span>
              </td>
              <td class="mono run-label">{{ r.label ?? '—' }}</td>
              <td class="mono">{{ fmtTime(r.started_at) }}</td>
              <td class="mono">{{ fmtTime(r.ran_at) }}</td>
              <td>{{ fmtDuration(r.duration_sec) }}</td>
              <td>{{ r.size_formatted ?? '—' }}</td>
              <td class="num">{{ r.files_count != null ? r.files_count.toLocaleString() : '—' }}</td>
              <td>{{ r.exit_code != null ? r.exit_code : '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else-if="!loadingRuns" class="empty-note">No runs recorded yet.</p>
        <p v-if="loadingRuns" class="empty-note">Loading…</p>
        <button v-if="hasMore" class="btn ghost sm load-more" @click="loadRuns(false)">Load more</button>
      </section>
    </div>

    <!-- Regenerate confirmation -->
    <div v-if="showRegenConfirm" class="confirm-overlay" @click.self="showRegenConfirm = false">
      <div class="confirm">
        <h3>Regenerate Ping URL?</h3>
        <p>
          Regenerating the URL will break existing scripts. Update all scripts
          before the next scheduled run, or the job will be marked missing.
        </p>
        <div class="confirm-actions">
          <button class="btn ghost" @click="showRegenConfirm = false">Cancel</button>
          <button class="btn danger" :disabled="regenerating" @click="confirmRegenerate">
            {{ regenerating ? 'Regenerating…' : 'Regenerate' }}
          </button>
        </div>
      </div>
    </div>
  </SlideOver>
</template>

<style scoped>
.hdr-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.hdr-top h2 { font-size: 16px; color: #fff; }
.hdr-line { font-size: 12px; color: var(--text); margin-top: 6px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.hdr-line.muted { color: var(--muted); }
.sep { opacity: 0.5; }

.body { display: flex; flex-direction: column; gap: 22px; }
.block { background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
.block h3 { font-size: 13px; color: #fff; margin-bottom: 12px; }
.block-hd { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.block-hd h3 { margin-bottom: 0; }

.ping-block { background: rgba(99, 102, 241, 0.06); border-color: rgba(99, 102, 241, 0.3); }
.curl { background: #0f1117; border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; font-family: ui-monospace, monospace; font-size: 11px; color: var(--green); overflow-x: auto; white-space: pre-wrap; word-break: break-all; margin-bottom: 12px; }
.ping-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.hint { font-size: 11px; color: var(--muted); line-height: 1.5; }
.hint code { background: rgba(255,255,255,0.07); border-radius: 3px; padding: 1px 4px; font-family: ui-monospace, monospace; }
.snippet-tabs { display: flex; gap: 4px; margin-bottom: 10px; }
.stab { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; color: var(--muted); font-size: 11px; padding: 4px 10px; cursor: pointer; }
.stab.active { background: rgba(99, 102, 241, 0.15); border-color: rgba(99, 102, 241, 0.4); color: var(--accent-2); }
.num { text-align: right; font-variant-numeric: tabular-nums; }

.empty-note { font-size: 12px; color: var(--muted); padding: 8px 0; }

.runs { width: 100%; border-collapse: collapse; font-size: 12px; }
.runs th { text-align: left; color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; padding: 6px 8px; border-bottom: 1px solid var(--border); }
.runs td { padding: 8px; border-bottom: 1px solid var(--border); color: var(--text); vertical-align: middle; }
.runs tbody tr:last-child td { border-bottom: none; }
.mono { font-family: ui-monospace, monospace; font-variant-numeric: tabular-nums; }
.outcome-text { margin-left: 8px; color: var(--muted); text-transform: capitalize; }
.load-more { margin-top: 12px; }
.icon-col { width: 24px; padding-right: 4px; }
.run-ok { color: var(--green, #4ade80); font-weight: 700; font-size: 13px; }
.run-fail { color: #f87171; font-weight: 700; font-size: 13px; }
.run-label { max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }

.btn { padding: 8px 16px; border-radius: 8px; font-size: 12px; cursor: pointer; border: 1px solid var(--border); background: var(--surface-2); color: var(--text); }
.btn.sm { padding: 6px 12px; font-size: 11px; }
.btn.ghost:hover { border-color: var(--accent); color: var(--accent-2); }
.btn.danger { background: rgba(239, 68, 68, 0.12); border-color: rgba(239, 68, 68, 0.4); color: #fca5a5; }
.btn.danger:hover { background: rgba(239, 68, 68, 0.2); }
.btn:disabled { opacity: 0.6; cursor: wait; }
.link-danger { background: none; border: none; color: #fca5a5; font-size: 11px; cursor: pointer; padding: 0; }
.link-danger:hover { text-decoration: underline; }

.confirm-overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6); display: flex; align-items: center; justify-content: center; z-index: 1200; padding: 20px; }
.confirm { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 22px; max-width: 420px; }
.confirm h3 { font-size: 15px; color: #fff; margin-bottom: 10px; }
.confirm p { font-size: 13px; color: var(--muted); line-height: 1.6; margin-bottom: 18px; }
.confirm-actions { display: flex; gap: 10px; justify-content: flex-end; }
.rh-hdr { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.rh-hdr h3 { margin-bottom: 0; color: #fff; font-size: 13px; }
.today-chip { font-size: 11px; color: var(--muted); background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 2px 7px; }
.today-badge { font-size: 11px; color: var(--text); background: rgba(99, 102, 241, 0.15); border: 1px solid rgba(99, 102, 241, 0.3); border-radius: 10px; padding: 2px 8px; }
.today-badge.fail { color: #fca5a5; background: rgba(239, 68, 68, 0.12); border-color: rgba(239, 68, 68, 0.3); }
.group-label td { padding: 6px 8px 4px; font-size: 10px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; border-bottom: none; }
.today-group td { color: #6366f1; background: rgba(99, 102, 241, 0.05); border-bottom: 1px solid rgba(99, 102, 241, 0.15); }
.earlier-group td { color: #475569; background: #0d1117; border-top: 2px solid var(--border); border-bottom: 1px solid var(--border); }
.today-row td { background: rgba(99, 102, 241, 0.03); }
.today-row-fail td { background: rgba(239, 68, 68, 0.04); }
</style>
