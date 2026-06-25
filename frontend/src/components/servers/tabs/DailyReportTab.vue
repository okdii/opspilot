<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { getDailyReport, getDailyReportAlerts, regenerateDailyReport } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import type { DailyReport, DailyReportFinding } from '@/types'
import Pager from '@/components/ui/Pager.vue'

const props = defineProps<{ serverId: string }>()
const auth = useAuthStore()

type PageStatus = 'loading' | 'loaded' | 'ai_not_configured' | 'not_generated' | 'error'

const report = ref<DailyReport | null>(null)
const pageStatus = ref<PageStatus>('loading')
const errorMsg = ref('')
const regenerating = ref(false)

// ── Date navigation ──────────────────────────────────────────────────────────
function isoYesterday(): string {
  const d = new Date()
  d.setUTCDate(d.getUTCDate() - 1)
  return d.toISOString().slice(0, 10)
}

const selectedDate = ref(isoYesterday())

function isYesterday(): boolean {
  return selectedDate.value === isoYesterday()
}

function prevDay() {
  const d = new Date(selectedDate.value + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() - 1)
  selectedDate.value = d.toISOString().slice(0, 10)
}

function nextDay() {
  if (!isYesterday()) {
    const d = new Date(selectedDate.value + 'T00:00:00Z')
    d.setUTCDate(d.getUTCDate() + 1)
    selectedDate.value = d.toISOString().slice(0, 10)
  }
}

function formattedDate(): string {
  const d = new Date(selectedDate.value + 'T12:00:00Z')
  return d.toLocaleDateString('en-US', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
}

// ── Data loading ──────────────────────────────────────────────────────────────
async function load() {
  pageStatus.value = 'loading'
  errorMsg.value = ''
  report.value = null
  try {
    const data = await getDailyReport(props.serverId, selectedDate.value)
    if (data.status === 'ai_not_configured') {
      pageStatus.value = 'ai_not_configured'
    } else if (data.status === 'not_generated') {
      pageStatus.value = 'not_generated'
    } else {
      report.value = data
      pageStatus.value = 'loaded'
      loadAlerts()
    }
  } catch {
    pageStatus.value = 'error'
    errorMsg.value = 'Could not load daily report'
  }
}

async function regenerate() {
  regenerating.value = true
  errorMsg.value = ''
  try {
    const data = await regenerateDailyReport(props.serverId, selectedDate.value)
    report.value = data
    pageStatus.value = 'loaded'
  } catch {
    errorMsg.value = 'Regeneration failed — check AI settings'
  } finally {
    regenerating.value = false
  }
}

// ── Alerts table (server-side paginated) ─────────────────────────────────────
const alertPage     = ref(0)
const alertPageSize = ref(10)
const alertTotal    = ref(0)
const alertRows     = ref<any[]>([])
const alertLoading  = ref(false)

async function loadAlerts() {
  alertLoading.value = true
  try {
    const res = await getDailyReportAlerts(props.serverId, selectedDate.value, alertPage.value, alertPageSize.value)
    alertRows.value  = res.items
    alertTotal.value = res.total
  } finally {
    alertLoading.value = false
  }
}

function onAlertPage(p: number) {
  alertPage.value = p
  loadAlerts()
}

onMounted(load)
watch(selectedDate, () => { alertPage.value = 0; load() })

// ── Score / band helpers ──────────────────────────────────────────────────────
const bandColor = computed(() => {
  const map: Record<string, string> = {
    excellent: 'var(--green)', good: 'var(--green)',
    'needs-attention': 'var(--amber)', poor: '#f97316', critical: 'var(--red)',
  }
  return map[report.value?.band ?? ''] ?? 'var(--muted)'
})

const bandLabel = computed(() => {
  const map: Record<string, string> = {
    excellent: 'Excellent', good: 'Good',
    'needs-attention': 'Needs Attention', poor: 'Poor — Act Now', critical: 'Critical',
  }
  return map[report.value?.band ?? ''] ?? ''
})

const scoreDashoffset = computed(() => {
  const s = report.value?.score ?? 0
  return Math.round(263.9 * (1 - s / 100))
})

const criticalCount = computed(() => report.value?.findings.filter(f => f.severity === 'danger').length ?? 0)
const warningCount  = computed(() => report.value?.findings.filter(f => f.severity === 'warn').length ?? 0)
const healthyCount  = computed(() => report.value?.findings.filter(f => f.severity === 'ok').length ?? 0)

// ── Grouped findings ──────────────────────────────────────────────────────────
interface FindingGroup { key: string; title: string; findings: DailyReportFinding[] }

const findingGroups = computed((): FindingGroup[] => {
  if (!report.value) return []
  const groups: Record<string, FindingGroup> = {
    server_performance:    { key: 'server_performance',    title: 'Server Performance',       findings: [] },
    log_anomalies_security:{ key: 'log_anomalies_security', title: 'Log Anomalies & Security', findings: [] },
    jobs_services:         { key: 'jobs_services',          title: 'Jobs & Services',          findings: [] },
  }
  for (const f of report.value.findings) {
    const g = groups[f.group] ?? groups.server_performance
    g.findings.push(f)
  }
  return Object.values(groups).filter(g => g.findings.length > 0)
})

// ── Severity helpers ──────────────────────────────────────────────────────────
function sevClass(sev: string): string {
  return { danger: 'sev-danger', warn: 'sev-warn', info: 'sev-info', ok: 'sev-ok' }[sev] ?? 'sev-info'
}

function badgeClass(sev: string): string {
  return { danger: 'fb-danger', warn: 'fb-warn', info: 'fb-info', ok: 'fb-ok' }[sev] ?? 'fb-info'
}

function badgeLabel(sev: string): string {
  return { danger: 'CRITICAL', warn: 'WARNING', info: 'INFO', ok: 'HEALTHY' }[sev] ?? sev.toUpperCase()
}

function actionLabel(sev: string): string {
  return sev === 'ok' ? '✓ Status' : '🔧 What to do'
}

function actionClass(sev: string): string {
  return { danger: 'al-danger', warn: 'al-warn', info: 'al-info', ok: 'al-ok' }[sev] ?? 'al-info'
}

// ── Copy as Markdown ──────────────────────────────────────────────────────────
const copied = ref(false)

function buildMarkdown(): string {
  if (!report.value) return ''
  const r = report.value
  const s = r.data_snapshot ?? null
  const lines: string[] = []

  lines.push(`# Daily Server Report — ${formattedDate()}`)
  lines.push('')
  lines.push(`**Score:** ${r.score}/100 — ${bandLabel.value}`)
  lines.push(`**Model:** ${r.ai_model}${r.generated_at ? ' · ' + new Date(r.generated_at).toLocaleString() : ''}`)
  lines.push(`**Findings:** ${criticalCount.value} critical · ${warningCount.value} warnings · ${healthyCount.value} healthy`)
  lines.push('')
  lines.push('## Summary')
  lines.push('')
  lines.push(r.narrative ?? '')

  for (const group of findingGroups.value) {
    lines.push('')
    lines.push(`## ${group.title}`)
    for (const f of group.findings) {
      lines.push('')
      lines.push(`### ${f.icon} ${f.title} [${badgeLabel(f.severity)}]`)
      lines.push('')
      lines.push(f.description)
      lines.push('')
      lines.push(`**${actionLabel(f.severity)}:** ${f.fix}`)
    }
  }

  if (s?.metrics) {
    lines.push('')
    lines.push('## Metrics')
    lines.push('')
    lines.push(`- Avg CPU: ${s.metrics.cpu_avg_pct?.toFixed(0) ?? '—'}%`)
    lines.push(`- Peak RAM: ${s.metrics.ram_avg_pct?.toFixed(0) ?? '—'}%`)
    lines.push(`- Disk /: ${s.metrics.disk_eod_pct?.toFixed(0) ?? '—'}%`)
    lines.push(`- Alerts Fired: ${s.alerts?.length ?? 0}`)
    if (s.jobs) lines.push(`- Jobs: ${s.jobs.filter((j: any) => j.runs.some((rr: any) => rr.outcome === 'success')).length}/${s.jobs.length} succeeded`)
  }

  if (s?.services?.length) {
    lines.push('')
    lines.push('## Services')
    lines.push('')
    lines.push('| Service | Type | Uptime | Incidents |')
    lines.push('|---------|------|--------|-----------|')
    for (const svc of s.services) {
      lines.push(`| ${svc.name} | ${svc.type}${svc.url ? ' · ' + svc.url : ''} | ${svc.uptime_pct}% | ${svc.incident_count ? svc.incident_count + ' incident · ' + svc.total_down_min + ' min' : '0 incidents'} |`)
    }
  }

  if (alertRows.value.length) {
    lines.push('')
    lines.push(`## Alerts${alertTotal.value > alertRows.value.length ? ' (first ' + alertRows.value.length + ' of ' + alertTotal.value + ')' : ''}`)
    lines.push('')
    lines.push('| Severity | Type | Message | State | Fired | Resolved | Duration |')
    lines.push('|----------|------|---------|-------|-------|----------|----------|')
    for (const a of alertRows.value) {
      lines.push(`| ${a.severity} | ${a.type} | ${a.message} | ${a.state} | ${a.fired_at ?? '—'} | ${a.resolved_at ?? '—'} | ${a.duration_min != null ? a.duration_min + ' min' : '—'} |`)
    }
  }

  if (s?.jobs?.length) {
    lines.push('')
    lines.push('## Cron & Backup Jobs')
    lines.push('')
    for (const job of s.jobs) {
      const run = job.runs[0]
      const icon = run?.outcome === 'success' ? '✓' : '✗'
      const meta = run ? `Ran ${run.ran_at}${run.duration_sec ? ' · ' + run.duration_sec + 's' : ''}` : 'No runs recorded'
      lines.push(`- ${icon} **${job.name}** — ${meta} [${run?.outcome === 'success' ? 'Success' : 'Missed'}]`)
    }
  }

  if (s?.logs) {
    lines.push('')
    lines.push('## Log Volume')
    lines.push('')
    lines.push(`Total: ${s.logs.total_lines.toLocaleString()} lines`)
    lines.push('')
    for (const src of s.logs.sources) {
      lines.push(`- ${src.source}: ${src.count.toLocaleString()}`)
    }
    if (s.logs.failed_logins?.length) {
      lines.push(`- ⚠ ${s.logs.failed_logins[0].count} failed logins${s.logs.failed_logins[0].remote_host ? ' from ' + s.logs.failed_logins[0].remote_host : ''}`)
    }
    if (s.logs.slow_queries) {
      lines.push(`- ⚠ ${s.logs.slow_queries.count} slow queries — avg ${s.logs.slow_queries.avg_sec}s`)
    }
  }

  return lines.join('\n')
}

async function copyMarkdown() {
  const md = buildMarkdown()
  await navigator.clipboard.writeText(md)
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}

// ── Data section helpers ──────────────────────────────────────────────────────
const snap = computed(() => report.value?.data_snapshot ?? null)

function uptimeColor(pct: number): string {
  if (pct >= 99.5) return 'var(--green)'
  if (pct >= 95) return 'var(--amber)'
  return 'var(--red)'
}
</script>

<template>
  <div>

    <!-- Date nav -->
    <div class="datenav">
      <div class="dn-l">
        <button class="dn-btn" @click="prevDay">‹</button>
        <div>
          <div class="dn-date">{{ formattedDate() }}</div>
          <div class="dn-sub">{{ isYesterday() ? 'Yesterday' : selectedDate }} · UTC</div>
        </div>
        <button class="dn-btn" :class="{ 'dn-btn--off': isYesterday() }" @click="nextDay" :disabled="isYesterday()">›</button>
      </div>
      <div class="dn-r">
        <input type="date" v-model="selectedDate" class="dn-picker" :max="isoYesterday()" />
        <button class="dn-chip" @click="selectedDate = isoYesterday()">← Yesterday</button>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="pageStatus === 'loading'" class="state-card">
      <div class="spinner"></div>
      <p>Generating report…</p>
    </div>

    <!-- Error -->
    <div v-else-if="pageStatus === 'error'" class="state-card state-card--err">
      <p>{{ errorMsg }}</p>
      <button class="btn-sm" @click="load">Retry</button>
    </div>

    <!-- AI not configured -->
    <div v-else-if="pageStatus === 'ai_not_configured'" class="state-card">
      <div class="state-icon">✦</div>
      <h3>AI Analysis not set up</h3>
      <p>Configure an AI provider in Settings to enable daily server reports.</p>
      <router-link to="/settings" class="btn-sm">Go to Settings</router-link>
    </div>

    <!-- Not generated -->
    <div v-else-if="pageStatus === 'not_generated'" class="state-card">
      <div class="state-icon">📋</div>
      <h3>No report for this date</h3>
      <p>Reports are generated nightly at 00:05. Older dates may not have a cached report.</p>
      <button v-if="auth.isAdmin" class="btn-sm" @click="regenerate" :disabled="regenerating">
        {{ regenerating ? 'Generating…' : 'Generate Now' }}
      </button>
    </div>

    <!-- Report loaded -->
    <template v-else-if="pageStatus === 'loaded' && report">

      <!-- Score banner -->
      <div class="score-banner" :style="{ '--band': bandColor }">
        <div class="score-ring">
          <svg width="92" height="92" viewBox="0 0 92 92">
            <circle class="sr-track" cx="46" cy="46" r="38" />
            <circle class="sr-fill" cx="46" cy="46" r="38"
              :style="{ stroke: bandColor, strokeDashoffset: scoreDashoffset }" />
          </svg>
          <div class="score-num">
            <div class="score-val" :style="{ color: bandColor }">{{ report.score }}</div>
            <div class="score-den">/ 100</div>
          </div>
        </div>

        <div class="score-divider"></div>

        <div class="score-verdict">
          <div class="score-band-pill" :style="{ color: bandColor, borderColor: bandColor, background: bandColor + '22' }">
            ⚠ {{ bandLabel }}
          </div>
          <div class="score-headline">
            {{ criticalCount > 0 ? 'This server needs your attention.' : warningCount > 0 ? 'Some issues to review.' : 'Everything looks healthy.' }}
          </div>
          <div class="score-blurb">{{ report.narrative?.slice(0, 180) }}</div>
        </div>

        <div class="score-divider"></div>

        <div class="score-pills">
          <div class="sp"><span class="sp-dot" style="background:var(--red)"></span><span class="sp-cnt" style="color:var(--red)">{{ criticalCount }}</span><span class="sp-lbl">Critical</span></div>
          <div class="sp"><span class="sp-dot" style="background:var(--amber)"></span><span class="sp-cnt" style="color:var(--amber)">{{ warningCount }}</span><span class="sp-lbl">Warnings</span></div>
          <div class="sp"><span class="sp-dot" style="background:var(--green)"></span><span class="sp-cnt" style="color:var(--green)">{{ healthyCount }}</span><span class="sp-lbl">Healthy</span></div>
        </div>
      </div>

      <!-- AI card -->
      <div class="ai-card">
        <div class="ai-hdr">
          <div class="ai-badge">⬡ AI Analysis</div>
          <span class="ai-meta">{{ report.ai_model }} · {{ report.generated_at ? new Date(report.generated_at).toLocaleString() : '' }}</span>
          <button class="ai-copy" @click="copyMarkdown">
            {{ copied ? '✓ Copied' : '⎘ Copy as Markdown' }}
          </button>
          <button v-if="auth.isAdmin" class="ai-regen" @click="regenerate" :disabled="regenerating">
            {{ regenerating ? '…' : '↻ Regenerate' }}
          </button>
        </div>

        <div class="narrative-block">
          <p class="narrative-text">{{ report.narrative }}</p>
        </div>

        <div class="finding-groups">
          <div v-for="group in findingGroups" :key="group.key" class="finding-group">
            <div class="fg-hdr">
              <span class="fg-title">{{ group.title.toUpperCase() }}</span>
              <div class="fg-line"></div>
              <span class="fg-count">{{ group.findings.length }} finding{{ group.findings.length !== 1 ? 's' : '' }}</span>
            </div>

            <div v-for="f in group.findings" :key="f.id" class="finding" :class="sevClass(f.severity)">
              <div class="f-problem">
                <span class="f-icon">{{ f.icon }}</span>
                <div class="f-body">
                  <div class="f-title">{{ f.title }}</div>
                  <div class="f-desc">{{ f.description }}</div>
                </div>
                <span class="f-badge" :class="badgeClass(f.severity)">{{ badgeLabel(f.severity) }}</span>
              </div>
              <div class="f-action">
                <div class="f-action-label" :class="actionClass(f.severity)">{{ actionLabel(f.severity) }}</div>
                <div class="f-action-text">{{ f.fix }}</div>
              </div>
            </div>

          </div>
        </div>
      </div>

      <!-- Stat row -->
      <div class="stat-row" v-if="snap?.metrics">
        <div class="stat">
          <div class="s-lbl">Avg CPU</div>
          <div class="s-val">{{ snap.metrics.cpu_avg_pct?.toFixed(0) ?? '—' }}%</div>
        </div>
        <div class="stat" :class="(snap.metrics.ram_avg_pct ?? 0) > 80 ? 'tint-a' : ''">
          <div class="s-lbl">Peak RAM</div>
          <div class="s-val" :style="{ color: (snap.metrics.ram_avg_pct ?? 0) > 80 ? 'var(--amber)' : '' }">
            {{ snap.metrics.ram_avg_pct?.toFixed(0) ?? '—' }}%
          </div>
        </div>
        <div class="stat" :class="(snap.metrics.disk_eod_pct ?? 0) > 75 ? 'tint-a' : ''">
          <div class="s-lbl">Disk /</div>
          <div class="s-val" :style="{ color: (snap.metrics.disk_eod_pct ?? 0) > 75 ? 'var(--amber)' : '' }">
            {{ snap.metrics.disk_eod_pct?.toFixed(0) ?? '—' }}%
          </div>
        </div>
        <div class="stat" :class="snap.alerts?.length ? 'tint-r' : ''">
          <div class="s-lbl">Alerts Fired</div>
          <div class="s-val" :style="{ color: snap.alerts?.length ? 'var(--red)' : '' }">
            {{ snap.alerts?.length ?? 0 }}
          </div>
        </div>
        <div class="stat" :class="snap.jobs?.some(j => j.status === 'missed') ? 'tint-r' : ''">
          <div class="s-lbl">Jobs</div>
          <div class="s-val">
            <span style="color:var(--green)">{{ snap.jobs?.filter(j => j.runs.some(r => r.outcome === 'success')).length ?? 0 }}</span>
            <span class="s-sep"> / </span>
            {{ snap.jobs?.length ?? 0 }}
          </div>
        </div>
      </div>

      <!-- Services section -->
      <div class="section" v-if="snap?.services?.length">
        <div class="sec-hdr"><span class="sec-title">🔗 Services</span><span class="sec-sub">{{ snap.services.length }} monitored</span></div>
        <div class="sec-card">
          <div v-for="svc in snap.services" :key="svc.name" class="svc-row">
            <div class="svc-info">
              <div class="svc-name">{{ svc.name }}</div>
              <div class="svc-type">{{ svc.type }}{{ svc.url ? ` · ${svc.url}` : '' }}</div>
            </div>
            <div class="svc-uptime">
              <div class="svc-bar"><div class="svc-fill" :style="{ width: svc.uptime_pct + '%', background: uptimeColor(svc.uptime_pct) }"></div></div>
              <div class="svc-pct" :style="{ color: uptimeColor(svc.uptime_pct) }">{{ svc.uptime_pct }}%</div>
            </div>
            <div class="svc-inc" :style="{ color: svc.incident_count ? 'var(--amber)' : 'var(--muted)' }">
              {{ svc.incident_count ? `${svc.incident_count} incident · ${svc.total_down_min} min` : '0 incidents' }}
            </div>
          </div>
        </div>
      </div>

      <!-- Alerts table (server-side paginated) -->
      <div class="section" v-if="alertTotal > 0 || alertLoading">
        <div class="sec-hdr">
          <span class="sec-title">🔔 Alerts</span>
          <span class="sec-sub">{{ alertTotal }} fired</span>
        </div>
        <div class="sec-card">
          <table class="at-table">
            <thead>
              <tr>
                <th>Severity</th>
                <th>Type</th>
                <th>Message</th>
                <th>State</th>
                <th>Fired</th>
                <th>Resolved</th>
                <th>Duration</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="alertLoading">
                <td colspan="7" class="at-empty">Loading…</td>
              </tr>
              <tr v-else-if="alertRows.length === 0">
                <td colspan="7" class="at-empty">No alerts</td>
              </tr>
              <tr v-for="a in alertRows" :key="a.id" v-else>
                <td>
                  <span class="at-sev" :class="'at-sev--' + a.severity">{{ a.severity }}</span>
                </td>
                <td class="at-type">{{ a.type }}</td>
                <td class="at-msg">{{ a.message }}</td>
                <td>
                  <span class="at-state" :class="'at-state--' + a.state">{{ a.state }}</span>
                </td>
                <td class="at-time">{{ a.fired_at ?? '—' }}</td>
                <td class="at-time">{{ a.resolved_at ?? '—' }}</td>
                <td class="at-dur">{{ a.duration_min != null ? a.duration_min + ' min' : '—' }}</td>
              </tr>
            </tbody>
          </table>
          <Pager :page="alertPage" :page-size="alertPageSize" :total="alertTotal" @update:page="onAlertPage" />
        </div>
      </div>

      <!-- Jobs section -->
      <div class="section" v-if="snap?.jobs?.length">
        <div class="sec-hdr"><span class="sec-title">⏰ Cron & Backup Jobs</span></div>
        <div class="sec-card">
          <div v-for="job in snap.jobs" :key="job.name" class="job-row" :class="{ 'job-miss': job.status === 'missed' }">
            <span class="j-icon">{{ job.runs.length && job.runs[0].outcome === 'success' ? '✓' : job.status === 'missed' ? '✗' : '–' }}</span>
            <div class="j-name">{{ job.name }}</div>
            <div class="j-meta">
              <template v-if="job.runs.length">Ran {{ job.runs[0].ran_at }}<span v-if="job.runs[0].duration_sec"> · {{ job.runs[0].duration_sec }}s</span></template>
              <template v-else><span style="color:var(--red)">No runs recorded</span></template>
            </div>
            <span class="j-pill" :class="job.runs.length && job.runs[0].outcome === 'success' ? 'jp-ok' : 'jp-miss'">
              {{ job.runs.length && job.runs[0].outcome === 'success' ? 'Success' : 'Missed' }}
            </span>
          </div>
        </div>
      </div>

      <!-- Logs section -->
      <div class="section" v-if="snap?.logs">
        <div class="sec-hdr">
          <span class="sec-title">📋 Log Volume</span>
          <span class="sec-sub">{{ snap.logs.total_lines.toLocaleString() }} total lines</span>
        </div>
        <div class="sec-card">
          <div class="log-cols">
            <div v-for="src in snap.logs.sources.slice(0, 3)" :key="src.source" class="log-col">
              <div class="lc-name">{{ src.source.replace('_', ' ') }}</div>
              <div class="lc-count">{{ src.count.toLocaleString() }}</div>
            </div>
          </div>
          <div v-if="snap.logs.failed_logins?.length" class="log-flag log-flag--r">
            ⚠ {{ snap.logs.failed_logins[0].count }} failed logins
            <span v-if="snap.logs.failed_logins[0].remote_host"> from {{ snap.logs.failed_logins[0].remote_host }}</span>
          </div>
          <div v-if="snap.logs.slow_queries" class="log-flag log-flag--a">
            ⚠ {{ snap.logs.slow_queries.count }} slow queries — avg {{ snap.logs.slow_queries.avg_sec }}s
          </div>
        </div>
      </div>

    </template>
  </div>
</template>

<style scoped>

/* Date nav */
.datenav { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.dn-l { display: flex; align-items: center; gap: 12px; }
.dn-btn { width: 32px; height: 32px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; color: var(--muted); font-size: 16px; cursor: pointer; display: flex; align-items: center; justify-content: center; }
.dn-btn--off { opacity: .3; cursor: default; }
.dn-date { font-size: 15px; font-weight: 600; }
.dn-sub  { font-size: 12px; color: var(--muted); }
.dn-r { display: flex; gap: 8px; align-items: center; }
.dn-picker { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; font-size: 12px; color: var(--text); }
.dn-chip { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 6px 14px; font-size: 12px; color: var(--muted); cursor: pointer; }

/* State cards */
.state-card { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 48px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 12px; }
.state-card--err { border-color: rgba(239,68,68,.3); }
.state-icon { font-size: 32px; }
.state-card h3 { font-size: 16px; font-weight: 700; }
.state-card p  { font-size: 13px; color: var(--muted); max-width: 380px; }
.btn-sm { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 8px 20px; font-size: 13px; color: var(--text); cursor: pointer; text-decoration: none; }
.btn-sm:hover { background: rgba(99,102,241,.15); color: var(--accent-2); }
.spinner { width: 28px; height: 28px; border: 3px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* Score banner */
.score-banner { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 24px 28px; display: flex; align-items: center; gap: 24px; margin-bottom: 20px; }
.score-ring { position: relative; width: 92px; height: 92px; flex-shrink: 0; }
.score-ring svg { transform: rotate(-90deg); }
.sr-track { fill: none; stroke: var(--surface-2); stroke-width: 7; }
.sr-fill  { fill: none; stroke-width: 7; stroke-linecap: round; stroke-dasharray: 263.9; transition: stroke-dashoffset .5s; }
.score-num { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.score-val { font-size: 28px; font-weight: 800; line-height: 1; }
.score-den { font-size: 11px; color: var(--muted); }
.score-divider { width: 1px; height: 60px; background: var(--border); flex-shrink: 0; }
.score-verdict { flex: 1; min-width: 0; }
.score-band-pill { display: inline-flex; font-size: 11px; font-weight: 700; letter-spacing: .05em; padding: 3px 12px; border-radius: 20px; border: 1px solid; margin-bottom: 8px; }
.score-headline { font-size: 16px; font-weight: 700; color: #fff; margin-bottom: 5px; }
.score-blurb { font-size: 13px; color: var(--muted); line-height: 1.6; }
.score-pills { display: flex; flex-direction: column; gap: 8px; flex-shrink: 0; }
.sp { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.sp-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.sp-cnt { font-weight: 700; min-width: 20px; }
.sp-lbl { font-size: 12px; color: var(--muted); }

/* AI card */
.ai-card { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; overflow: hidden; margin-bottom: 20px; }
.ai-hdr { display: flex; align-items: center; gap: 12px; padding: 13px 20px; border-bottom: 1px solid var(--border); }
.ai-badge { background: rgba(99,102,241,.15); border: 1px solid rgba(99,102,241,.28); border-radius: 20px; padding: 4px 14px; font-size: 12px; font-weight: 600; color: var(--accent-2); }
.ai-meta { font-size: 12px; color: var(--muted); flex: 1; }
.ai-copy  { background: none; border: 1px solid var(--border); border-radius: 7px; color: var(--muted); font-size: 12px; cursor: pointer; padding: 4px 12px; transition: color .15s, border-color .15s; }
.ai-copy:hover { color: var(--text); border-color: var(--accent-2); }
.ai-regen { background: none; border: none; color: var(--accent-2); font-size: 12px; cursor: pointer; }

/* Narrative */
.narrative-block { padding: 22px 20px 18px; border-bottom: 1px solid var(--border); }
.narrative-text { font-size: 14px; line-height: 1.85; color: #c8d3e0; margin: 0; }

/* Finding groups */
.finding-groups { padding: 0 20px 20px; }
.finding-group { margin-top: 26px; }
.fg-hdr { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.fg-title { font-size: 11px; font-weight: 700; letter-spacing: .08em; color: var(--muted); white-space: nowrap; }
.fg-line { flex: 1; height: 1px; background: var(--border); }
.fg-count { font-size: 11px; color: var(--muted); background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px; padding: 1px 9px; white-space: nowrap; }

/* Finding cards */
.finding { border: 1px solid var(--border); border-radius: 12px; overflow: hidden; margin-bottom: 8px; background: var(--bg); }
.sev-danger { border-top: 3px solid var(--red); }
.sev-warn   { border-top: 3px solid var(--amber); }
.sev-info   { border-top: 3px solid var(--blue); }
.sev-ok     { border-top: 3px solid var(--green); }
.f-problem { display: flex; align-items: flex-start; gap: 12px; padding: 16px 18px 12px; }
.f-icon { font-size: 18px; flex-shrink: 0; margin-top: 1px; }
.f-body { flex: 1; min-width: 0; }
.f-title { font-size: 14px; font-weight: 700; color: #fff; margin-bottom: 4px; line-height: 1.4; }
.f-desc { font-size: 13px; color: var(--muted); line-height: 1.6; }
.f-badge { flex-shrink: 0; font-size: 10px; font-weight: 700; letter-spacing: .05em; padding: 3px 9px; border-radius: 6px; margin-top: 2px; }
.fb-danger { background: rgba(239,68,68,.15);  color: var(--red);   border: 1px solid rgba(239,68,68,.25); }
.fb-warn   { background: rgba(245,158,11,.15); color: var(--amber); border: 1px solid rgba(245,158,11,.25); }
.fb-info   { background: rgba(59,130,246,.15); color: var(--blue);  border: 1px solid rgba(59,130,246,.25); }
.fb-ok     { background: rgba(34,197,94,.12);  color: var(--green); border: 1px solid rgba(34,197,94,.2); }
.f-action { border-top: 1px solid var(--border); padding: 12px 18px 14px; background: rgba(255,255,255,.02); }
.f-action-label { font-size: 11px; font-weight: 700; letter-spacing: .06em; margin-bottom: 6px; }
.al-danger { color: var(--red); } .al-warn { color: var(--amber); } .al-info { color: var(--blue); } .al-ok { color: var(--green); }
.f-action-text { font-size: 13px; font-weight: 500; color: #fff; line-height: 1.7; white-space: pre-wrap; }

/* Stat row */
.stat-row { display: grid; grid-template-columns: repeat(5,1fr); gap: 12px; margin-bottom: 20px; }
.stat { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
.tint-a { border-color: rgba(245,158,11,.3); background: rgba(245,158,11,.03); }
.tint-r { border-color: rgba(239,68,68,.3);  background: rgba(239,68,68,.03); }
.s-lbl { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; margin-bottom: 8px; }
.s-val { font-size: 24px; font-weight: 700; color: #fff; }
.s-sep { font-size: 14px; color: var(--muted); }

/* Section headers */
.section { margin-bottom: 20px; }
.sec-hdr { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.sec-title { font-size: 14px; font-weight: 700; }
.sec-sub   { font-size: 12px; color: var(--muted); }
.sec-card  { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }

/* Services */
.svc-row { display: flex; align-items: center; padding: 12px 18px; border-bottom: 1px solid var(--border); gap: 14px; }
.svc-row:last-child { border-bottom: none; }
.svc-info { flex: 1; }
.svc-name { font-size: 13px; font-weight: 500; }
.svc-type { font-size: 12px; color: var(--muted); margin-top: 2px; }
.svc-uptime { width: 100px; }
.svc-bar { height: 5px; background: var(--surface-2); border-radius: 3px; overflow: hidden; }
.svc-fill { height: 100%; border-radius: 3px; }
.svc-pct { font-size: 12px; font-weight: 600; text-align: right; margin-top: 4px; }
.svc-inc { font-size: 12px; min-width: 120px; text-align: right; }

/* Alerts table */
.at-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.at-table th { padding: 10px 14px; text-align: left; font-size: 11px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; border-bottom: 1px solid var(--border); white-space: nowrap; }
.at-table td { padding: 11px 14px; border-bottom: 1px solid var(--border); vertical-align: middle; }
.at-table tr:last-child td { border-bottom: none; }
.at-table tbody tr:hover { background: rgba(255,255,255,.02); }
.at-empty { text-align: center; color: var(--muted); padding: 24px !important; }
.at-sev { font-size: 11px; font-weight: 700; letter-spacing: .04em; padding: 2px 8px; border-radius: 5px; text-transform: uppercase; }
.at-sev--critical { background: rgba(239,68,68,.15);  color: var(--red);   border: 1px solid rgba(239,68,68,.25); }
.at-sev--warning  { background: rgba(245,158,11,.15); color: var(--amber); border: 1px solid rgba(245,158,11,.25); }
.at-sev--info     { background: rgba(59,130,246,.15); color: var(--blue);  border: 1px solid rgba(59,130,246,.25); }
.at-state { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 5px; text-transform: capitalize; }
.at-state--resolved   { background: rgba(34,197,94,.1);  color: var(--green); }
.at-state--firing     { background: rgba(239,68,68,.1);  color: var(--red); }
.at-state--acked      { background: rgba(245,158,11,.1); color: var(--amber); }
.at-state--snoozed    { background: rgba(99,102,241,.1); color: var(--accent-2); }
.at-state--suppressed { background: rgba(148,163,184,.1); color: var(--muted); }
.at-type { color: var(--muted); font-size: 12px; white-space: nowrap; }
.at-msg  { max-width: 340px; }
.at-time { color: var(--muted); font-size: 12px; white-space: nowrap; font-variant-numeric: tabular-nums; }
.at-dur  { color: var(--muted); font-size: 12px; white-space: nowrap; text-align: right; }

/* Jobs */
.job-row { display: flex; align-items: center; padding: 12px 18px; border-bottom: 1px solid var(--border); gap: 12px; }
.job-row:last-child { border-bottom: none; }
.job-miss { background: rgba(239,68,68,.03); }
.j-icon { font-size: 15px; flex-shrink: 0; width: 20px; text-align: center; }
.j-name { flex: 1; font-size: 13px; font-weight: 500; }
.j-meta { font-size: 12px; color: var(--muted); }
.j-pill { font-size: 11px; font-weight: 600; padding: 2px 9px; border-radius: 10px; }
.jp-ok   { background: rgba(34,197,94,.12);  color: var(--green); }
.jp-miss { background: rgba(239,68,68,.12);  color: var(--red); }

/* Logs */
.log-cols { display: grid; grid-template-columns: repeat(3,1fr); border-bottom: 1px solid var(--border); }
.log-col { padding: 16px 18px; border-right: 1px solid var(--border); }
.log-col:last-child { border-right: none; }
.lc-name  { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; margin-bottom: 6px; }
.lc-count { font-size: 22px; font-weight: 700; }
.log-flag { padding: 10px 18px; font-size: 12px; font-weight: 500; border-top: 1px solid var(--border); }
.log-flag--r { color: var(--red); }
.log-flag--a { color: var(--amber); }
</style>
