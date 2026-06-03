<script setup lang="ts">
import { computed } from 'vue'
import type { LogEntry } from '@/types'

const props = defineProps<{
  entry: LogEntry
  expanded: boolean
  showServer: boolean
  fresh?: boolean
  search?: string
}>()

const emit = defineEmits<{
  (e: 'toggle'): void
  (e: 'filter-source', source: string): void
  (e: 'filter-ip', ip: string): void
}>()

// --- Source badge colours (spec §6.3) — single source of truth here. --------
const SOURCE_TONE: Record<string, string> = {
  nginx_access: 'blue', nginx_error: 'blue-dark',
  php_fpm: 'purple', php_app: 'purple-dark',
  mariadb_error: 'orange', mariadb_slow: 'orange-dark',
  syslog: 'grey', auth: 'teal', kernel: 'grey-dark',
}

const sourceTone = computed(() => SOURCE_TONE[props.entry.source] ?? 'grey')

const severityTone = computed(() => {
  const s = props.entry.severity
  if (!s) return null
  return s
})

// Fields displayed per source (spec §6.4). Falls back to all fields.
const FIELD_ORDER: Record<string, string[]> = {
  nginx_access: ['client_ip', 'method', 'url', 'status_code', 'response_size', 'response_time_ms', 'user_agent', 'referrer'],
  nginx_error: ['severity', 'message', 'upstream'],
  php_fpm: ['severity', 'pool', 'pid', 'message'],
  php_app: ['type', 'file', 'line', 'message'],
  mariadb_error: ['severity', 'thread_id', 'message'],
  mariadb_slow: ['query_time', 'lock_time', 'rows_examined', 'rows_sent', 'user', 'host', 'db'],
  syslog: ['unit', 'priority', 'message'],
  auth: ['event', 'user', 'source_ip'],
  kernel: ['severity', 'subsystem', 'message'],
}

const fieldRows = computed<[string, unknown][]>(() => {
  const f = props.entry.fields ?? {}
  const order = FIELD_ORDER[props.entry.source]
  if (order) {
    const rows: [string, unknown][] = []
    for (const k of order) if (k in f && f[k] != null && f[k] !== '') rows.push([k, f[k]])
    // include any extra keys not in the predefined order
    for (const k of Object.keys(f)) {
      if (!order.includes(k) && k !== 'query' && f[k] != null && f[k] !== '') rows.push([k, f[k]])
    }
    return rows
  }
  return Object.entries(f).filter(([k, v]) => k !== 'query' && v != null && v !== '')
})

const isSlow = computed(() => props.entry.source === 'mariadb_slow')
const slowQuery = computed(() => String((props.entry.fields as Record<string, unknown>)?.query ?? ''))

const ipValue = computed(() => {
  const f = props.entry.fields as Record<string, unknown>
  const ip = f?.client_ip ?? f?.source_ip
  return typeof ip === 'string' ? ip : null
})

const localTime = computed(() => {
  const d = new Date(props.entry.time)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  const ms = String(d.getMilliseconds()).padStart(3, '0')
  return `${hh}:${mm}:${ss}.${ms}`
})

function fmtField(key: string, value: unknown): string {
  if (key === 'response_size' && typeof value === 'number') {
    if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`
    if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`
    return `${value} B`
  }
  if (key === 'response_time_ms' && typeof value === 'number') return `${value}ms`
  if ((key === 'query_time' || key === 'lock_time') && typeof value === 'number') return `${value}s`
  if ((key === 'rows_examined' || key === 'rows_sent') && typeof value === 'number') {
    return value.toLocaleString()
  }
  return String(value)
}

// Highlight search terms in the message (spec §4.4).
const messageParts = computed<{ text: string; hit: boolean }[]>(() => {
  const q = (props.search ?? '').trim()
  const msg = props.entry.message
  if (q.length < 2) return [{ text: msg, hit: false }]
  const lower = msg.toLowerCase()
  const ql = q.toLowerCase()
  const parts: { text: string; hit: boolean }[] = []
  let i = 0
  while (i < msg.length) {
    const idx = lower.indexOf(ql, i)
    if (idx === -1) { parts.push({ text: msg.slice(i), hit: false }); break }
    if (idx > i) parts.push({ text: msg.slice(i, idx), hit: false })
    parts.push({ text: msg.slice(idx, idx + q.length), hit: true })
    i = idx + q.length
  }
  return parts
})

function copyJson(): void {
  void navigator.clipboard?.writeText(JSON.stringify(props.entry, null, 2))
}
function copyQuery(): void {
  void navigator.clipboard?.writeText(slowQuery.value)
}
</script>

<template>
  <div class="log-row" :class="{ fresh, 'is-expanded': expanded }">
    <div class="lr-line" role="button" tabindex="0" @click="emit('toggle')" @keydown.enter.prevent="emit('toggle')" @keydown.space.prevent="emit('toggle')">
      <span class="lr-caret" :class="{ open: expanded }">›</span>
      <span class="lr-time" :title="entry.time">{{ localTime }}</span>
      <span v-if="showServer" class="lr-server">{{ entry.server_name }}</span>
      <span class="lr-source" :class="`src-${sourceTone}`">{{ entry.source }}</span>
      <span class="lr-sev">
        <span v-if="severityTone" class="sev-chip" :class="`sev-${severityTone}`">{{ entry.severity }}</span>
        <span v-else class="sev-none">—</span>
      </span>
      <span class="lr-msg">
        <template v-for="(p, i) in messageParts" :key="i"><mark v-if="p.hit">{{ p.text }}</mark><template v-else>{{ p.text }}</template></template>
      </span>
    </div>

    <div v-if="expanded" class="lr-detail">
      <div v-if="!isSlow" class="lr-fields">
        <div v-for="[k, v] in fieldRows" :key="k" class="lr-field">
          <span class="fk">{{ k }}</span>
          <span class="fv">{{ fmtField(k, v) }}</span>
        </div>
      </div>

      <template v-else>
        <div class="lr-fields">
          <div v-for="[k, v] in fieldRows" :key="k" class="lr-field">
            <span class="fk">{{ k }}</span>
            <span class="fv">{{ fmtField(k, v) }}</span>
          </div>
        </div>
        <div class="lr-query-label">Query</div>
        <pre class="lr-query">{{ slowQuery || entry.message }}</pre>
      </template>

      <div class="lr-actions">
        <button class="lr-btn" @click.stop="copyJson">Copy as JSON</button>
        <button v-if="isSlow" class="lr-btn" @click.stop="copyQuery">Copy Query</button>
        <button class="lr-btn" @click.stop="emit('filter-source', entry.source)">Filter to this source</button>
        <button v-if="ipValue" class="lr-btn" @click.stop="emit('filter-ip', ipValue)">Filter to this IP</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.log-row { border-bottom: 1px solid var(--border); font-size: 12.5px; }
.lr-line { display: flex; align-items: center; gap: 12px; padding: 9px 14px; cursor: pointer; min-height: 40px; box-sizing: border-box; }
.lr-line:hover { background: var(--surface-2); }
.is-expanded > .lr-line { background: var(--surface-2); }
.lr-caret { color: var(--muted); transition: transform 0.12s; display: inline-block; width: 8px; font-size: 14px; }
.lr-caret.open { transform: rotate(90deg); }
.lr-time { width: 110px; flex-shrink: 0; color: var(--muted); font-variant-numeric: tabular-nums; font-family: ui-monospace, monospace; }
.lr-server { width: 96px; flex-shrink: 0; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lr-source { width: 110px; flex-shrink: 0; font-size: 10px; font-weight: 600; padding: 3px 7px; border-radius: 4px; text-align: center; text-transform: lowercase; letter-spacing: 0.02em; }
.lr-sev { width: 64px; flex-shrink: 0; }
.sev-chip { font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; text-transform: uppercase; }
.sev-none { color: var(--muted); }
.lr-msg { flex: 1; min-width: 0; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-family: ui-monospace, monospace; }
.lr-msg mark { background: rgba(245,158,11,0.4); color: #fff; border-radius: 2px; }

/* Source tones */
.src-blue { background: rgba(59,130,246,0.18); color: #60a5fa; }
.src-blue-dark { background: rgba(37,99,235,0.22); color: #3b82f6; }
.src-purple { background: rgba(168,85,247,0.18); color: #c084fc; }
.src-purple-dark { background: rgba(147,51,234,0.22); color: #a855f7; }
.src-orange { background: rgba(245,158,11,0.18); color: #fbbf24; }
.src-orange-dark { background: rgba(217,119,6,0.22); color: #f59e0b; }
.src-teal { background: rgba(20,184,166,0.18); color: #2dd4bf; }
.src-grey { background: rgba(148,163,184,0.16); color: #cbd5e1; }
.src-grey-dark { background: rgba(100,116,139,0.22); color: #94a3b8; }

/* Severity tones (spec §4.3) */
.sev-debug { background: rgba(107,114,128,0.2); color: #9ca3af; }
.sev-info { background: rgba(59,130,246,0.18); color: #60a5fa; }
.sev-warn { background: rgba(245,158,11,0.18); color: #fbbf24; }
.sev-error { background: rgba(239,68,68,0.18); color: #f87171; }
.sev-fatal { background: rgba(153,27,27,0.5); color: #fca5a5; font-weight: 800; }

/* Expanded detail */
.lr-detail { padding: 10px 14px 14px 34px; background: var(--surface); }
.lr-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 24px; margin-bottom: 10px; }
.lr-field { display: flex; gap: 10px; padding: 4px 0; border-bottom: 1px solid rgba(148,163,184,0.08); }
.fk { width: 130px; flex-shrink: 0; color: var(--muted); font-size: 11.5px; }
.fv { color: var(--text); word-break: break-word; font-family: ui-monospace, monospace; font-size: 11.5px; }
.lr-query-label { color: var(--muted); font-size: 11px; margin: 6px 0 4px; text-transform: uppercase; letter-spacing: 0.05em; }
.lr-query { background: #0f1117; border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; color: #e2e8f0; font-family: ui-monospace, monospace; font-size: 11.5px; white-space: pre-wrap; word-break: break-word; margin: 0 0 10px; }
.lr-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.lr-btn { background: var(--surface-2); border: 1px solid var(--border); color: var(--text); font-size: 11px; padding: 5px 10px; border-radius: 6px; cursor: pointer; transition: all 0.12s; }
.lr-btn:hover { border-color: var(--accent); color: var(--accent-2); }

/* Live-tail fresh-row highlight (spec §8.3) */
.fresh { animation: lr-fresh 0.6s ease-out; }
@keyframes lr-fresh { from { background: rgba(245,158,11,0.18); } to { background: transparent; } }

@media (max-width: 720px) {
  .lr-fields { grid-template-columns: 1fr; }
  .lr-server { display: none; }
}
</style>
