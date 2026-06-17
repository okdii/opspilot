<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useSecurityStore } from '@/stores/security'
import { useSecurityActionsStore, type SecurityActionRow } from '@/stores/securityActions'
import { useAuthStore } from '@/stores/auth'
import { useNotify } from '@/composables/useNotify'
import { relativeTime } from '@/utils/time'
import Pager from '@/components/ui/Pager.vue'
import KillChainBar from './KillChainBar.vue'
import IncidentTimeline from './IncidentTimeline.vue'

const props = defineProps<{ serverId: string }>()
const events = useSecurityStore()
const actions = useSecurityActionsStore()
const auth = useAuthStore()
const notify = useNotify()

const ttl = ref(24)
let evPoll: ReturnType<typeof setInterval> | null = null
let acPoll: ReturnType<typeof setInterval> | null = null

async function loadSettings() {
  await actions.fetchSettings(props.serverId)
  ttl.value = actions.settings?.block_ttl_hours ?? 24
}

// Refetch the merged timeline + kill-chain after a mutation (the store's own
// refresh only covers pending + summary).
function reloadTimeline() {
  return Promise.all([events.fetchIncidents(props.serverId), events.fetchStages(props.serverId)])
}

onMounted(() => {
  events.fetchIncidents(props.serverId, 0)
  events.fetchStages(props.serverId)
  actions.fetchPending(props.serverId)
  actions.fetchSummary(props.serverId)
  loadSettings()
  // Poll the current page in place so live updates appear without losing the page.
  evPoll = setInterval(() => {
    events.fetchIncidents(props.serverId)
    events.fetchStages(props.serverId)
    actions.fetchSummary(props.serverId)
  }, 60 * 1000)
  acPoll = setInterval(() => {
    actions.fetchPending(props.serverId)
    actions.fetchSummary(props.serverId)
  }, 30 * 1000)
})
onUnmounted(() => {
  if (evPoll) clearInterval(evPoll)
  if (acPoll) clearInterval(acPoll)
})

// ── Status-bar counts (server-side aggregates, accurate across all pages) ─────
const summary = computed(() => actions.summary)
const pending = computed(() => actions.pending)

const settingsOn = computed(() => actions.settings?.auto_response_enabled ?? false)

// ── Kill-chain stage filter ───────────────────────────────────────────────────
const stageFilter = computed(() => events.stageFilter)
function onStage(stage: string) { events.setStage(props.serverId, stage) }
function clearStage() { events.setStage(props.serverId, events.stageFilter) }

// ── Pagination (by incident) ───────────────────────────────────────────────────
function goIncidents(p: number) { events.fetchIncidents(props.serverId, p) }

// ── Helpers ─────────────────────────────────────────────────────────────────
const rel = relativeTime

// ── Mutations ───────────────────────────────────────────────────────────────
async function setEnabled(enabled: boolean) {
  try {
    await actions.updateSettings(props.serverId, {
      auto_response_enabled: enabled, block_ttl_hours: ttl.value,
    })
    notify.success(enabled ? 'Auto-response enabled for this server' : 'Auto-response disabled')
  } catch (e) { notify.error(e as Error) }
}
async function saveTtl() {
  if (!settingsOn.value) return
  try {
    await actions.updateSettings(props.serverId, {
      auto_response_enabled: true, block_ttl_hours: ttl.value,
    })
  } catch (e) { notify.error(e as Error) }
}
async function approve(a: SecurityActionRow) {
  const label = `${a.action_type} ${a.target ?? ''}`.trim()
  if (!window.confirm(`Approve and run: ${label}?\nThis acts on the server now.`)) return
  try { await actions.approve(props.serverId, a.id); await reloadTimeline(); notify.success('Action approved and executed') }
  catch (e) { notify.error(e as Error) }
}
async function reject(a: SecurityActionRow) {
  try { await actions.reject(props.serverId, a.id); await reloadTimeline(); notify.info('Action rejected') }
  catch (e) { notify.error(e as Error) }
}
async function undo(a: SecurityActionRow) {
  const label = `${a.action_type} ${a.target ?? ''}`.trim()
  if (!window.confirm(`Undo: ${label}?`)) return
  try { await actions.undo(props.serverId, a.id); await reloadTimeline(); notify.success('Action reverted') }
  catch (e) { notify.error(e as Error) }
}

watch(() => actions.settings?.block_ttl_hours, v => { if (typeof v === 'number') ttl.value = v })
</script>

<template>
  <div class="ti">
    <!-- ZONE 1 — Threat status bar -->
    <section class="statusbar">
      <div class="statusbar__left">
        <span class="statusbar__title">Threat Status</span>
        <div class="chips">
          <span class="chip chip--red"><span class="dot dot--red" />{{ summary.active_events }} Active Events</span>
          <span class="chip chip--amber"><span class="dot dot--amber" />{{ summary.pending_approvals }} Needs Approval</span>
          <span class="chip chip--blue"><span class="dot dot--blue" />{{ summary.blocked_ips }} IPs Blocked</span>
        </div>
      </div>
      <div class="statusbar__right">
        <span class="ar-label">Auto-Response</span>
        <VaSwitch
          :model-value="settingsOn"
          :disabled="!auth.isAdmin"
          @update:model-value="setEnabled($event)"
          aria-label="Enable auto-response"
          size="small" />
        <span class="ar-state" :class="settingsOn ? 'on' : 'off'">{{ settingsOn ? 'ON' : 'OFF' }}</span>
        <label v-if="settingsOn" class="ttl">
          <span>TTL</span>
          <VaInput v-model.number="ttl" type="number" :min="1" :max="720"
                   :disabled="!auth.isAdmin" @blur="saveTtl" class="ttl__input" />
          <span class="muted">h</span>
        </label>
      </div>
    </section>

    <!-- ZONE 1.5 — Kill-chain pipeline (per-category breakdown + feed filter) -->
    <KillChainBar :stages="events.stages" :active="stageFilter" @select="onStage" />

    <!-- ZONE 2 — Needs-approval banner (only when pending) -->
    <section v-if="pending.length" class="approval">
      <div class="approval__head">
        <span class="approval__title"><span class="dot dot--amber" /> Needs Your Approval</span>
        <span class="approval__badge">{{ pending.length }} pending</span>
      </div>
      <div v-for="a in pending" :key="a.id" class="approval__item">
        <div class="approval__meta">
          <span class="verb">{{ a.action_type }}</span>
          <span class="mp">target: <b>{{ a.target ?? '—' }}</b></span>
          <span class="mp">tier: <b>{{ a.tier }} · human approval</b></span>
          <span v-if="a.confidence" class="mp">confidence: <b class="conf">{{ a.confidence.toUpperCase() }}</b></span>
          <time class="mp time">{{ rel(a.created_at) }}</time>
        </div>
        <p v-if="a.detail" class="approval__desc">{{ a.detail }}</p>
        <div class="approval__btns">
          <VaButton size="small" preset="secondary" :disabled="!auth.isAdmin" @click="reject(a)">Reject</VaButton>
          <VaButton size="small" color="success" :disabled="!auth.isAdmin" @click="approve(a)">Approve Action</VaButton>
        </div>
      </div>
    </section>

    <!-- ZONE 3 — Merged incident timeline (detections + their mitigations) -->
    <section class="col">
      <header class="col__head">
        <span>Incident Timeline</span>
        <span class="col__head-right">
          <button v-if="stageFilter" class="feed-filter" @click="clearStage">
            {{ stageFilter }} <span class="feed-filter__x" aria-hidden="true">✕</span>
          </button>
          <span class="col__hint">attack → response · live · 1m</span>
        </span>
      </header>
      <div class="col__body">
        <div v-if="events.loading && !events.incidents.length" class="skeleton">
          <div v-for="n in 4" :key="n" class="skeleton__row" />
        </div>
        <p v-else-if="events.error" class="state-msg error" role="alert">{{ events.error }}</p>
        <div v-else-if="!events.incidents.length" class="state-msg empty">
          {{ stageFilter ? `No ${stageFilter} incidents.` : 'No security incidents detected.' }}
        </div>
        <IncidentTimeline v-else
          :incidents="events.incidents" :is-admin="auth.isAdmin"
          @approve="approve" @reject="reject" @undo="undo" />
      </div>
      <Pager :page="events.page" :page-size="events.pageSize" :total="events.total"
             :disabled="events.loading" @update:page="goIncidents" />
    </section>
  </div>
</template>

<style scoped>
.ti { display: flex; flex-direction: column; gap: 16px; }

/* Zone 1 */
.statusbar {
  display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap;
  background: var(--surface, #161d2e); border: 1px solid var(--border, #243049);
  border-radius: 12px; padding: 14px 18px;
}
.statusbar__title { font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase;
  color: var(--muted, #94a3b8); display: block; margin-bottom: 10px; }
.chips { display: flex; gap: 10px; flex-wrap: wrap; }
.chip { display: inline-flex; align-items: center; gap: 7px; padding: 6px 12px; border-radius: 8px;
  font-weight: 600; font-size: 13px; font-variant-numeric: tabular-nums; }
.chip--red   { background: rgba(239,68,68,0.12);  color: #fca5a5; border: 1px solid rgba(239,68,68,0.3); }
.chip--amber { background: rgba(245,158,11,0.12); color: #fcd34d; border: 1px solid rgba(245,158,11,0.3); }
.chip--blue  { background: rgba(59,130,246,0.12); color: #93c5fd; border: 1px solid rgba(59,130,246,0.3); }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.dot--red { background: #ef4444; } .dot--amber { background: #f59e0b; } .dot--blue { background: #3b82f6; }
.statusbar__right { display: flex; align-items: center; gap: 10px; }
.ar-label { font-size: 11px; letter-spacing: 1px; text-transform: uppercase; color: var(--muted, #94a3b8); }
.ar-state { font-weight: 700; font-size: 13px; }
.ar-state.on { color: var(--green, #22c55e); } .ar-state.off { color: var(--muted, #94a3b8); }
.ttl { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted, #94a3b8); }
.ttl__input { max-width: 72px; }

/* Zone 2 */
.approval {
  background: rgba(245,158,11,0.07); border: 1px solid rgba(245,158,11,0.35);
  border-left: 4px solid var(--amber, #f59e0b); border-radius: 12px; overflow: hidden;
}
.approval__head { display: flex; align-items: center; justify-content: space-between;
  padding: 11px 16px; border-bottom: 1px solid rgba(245,158,11,0.25); }
.approval__title { display: inline-flex; align-items: center; gap: 8px; font-weight: 700; color: #fcd34d; }
.approval__badge { background: var(--amber, #f59e0b); color: #2a2008; font-weight: 700;
  font-size: 11px; padding: 3px 9px; border-radius: 10px; }
.approval__item { padding: 14px 16px; }
.approval__meta { display: flex; gap: 18px; align-items: baseline; flex-wrap: wrap; margin-bottom: 8px; }
.verb { font-size: 15px; font-weight: 700; color: var(--text, #e8edf6); font-family: monospace; }
.mp { font-size: 12px; color: var(--muted, #94a3b8); }
.mp b { color: var(--text, #e8edf6); font-weight: 600; }
.mp.time { margin-left: auto; }
.conf { color: #fca5a5 !important; }
.approval__desc { font-size: 13px; color: var(--text, #cbd5e1); line-height: 1.55; margin: 0 0 12px;
  border-top: 1px solid rgba(245,158,11,0.2); padding-top: 10px; }
.approval__btns { display: flex; gap: 10px; justify-content: flex-end; }

/* Zone 3 — Incident timeline card */
.col { background: var(--surface, #161d2e); border: 1px solid var(--border, #243049);
  border-radius: 12px; overflow: hidden; }
.col__head { display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--border, #243049);
  font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--muted, #94a3b8); font-weight: 600; }
.col__hint { letter-spacing: 0; text-transform: none; color: var(--muted, #64748b); }
.col__head-right { display: inline-flex; align-items: center; gap: 10px; }
.feed-filter {
  display: inline-flex; align-items: center; gap: 6px; text-transform: none; letter-spacing: 0;
  background: rgba(79,140,255,0.12); border: 1px solid var(--accent-2, #4f8cff);
  color: #bcd2ff; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 999px; cursor: pointer;
}
.feed-filter:hover { background: rgba(79,140,255,0.2); }
.feed-filter__x { font-size: 10px; opacity: 0.8; }
.col__body { padding: 4px 0; }

.state-msg { padding: 28px 16px; text-align: center; font-size: 13px; color: var(--muted, #94a3b8); }
.state-msg.error { color: var(--red, #ef4444); }

.skeleton { padding: 8px 16px; }
.skeleton__row { height: 44px; border-radius: 8px; margin-bottom: 8px;
  background: linear-gradient(90deg, #1b1f2a 25%, #232838 37%, #1b1f2a 63%); background-size: 400% 100%;
  animation: shimmer 1.4s ease infinite; }
@keyframes shimmer { 0% { background-position: 100% 0; } 100% { background-position: 0 0; } }
@media (prefers-reduced-motion: reduce) { .skeleton__row { animation: none; } }
</style>
