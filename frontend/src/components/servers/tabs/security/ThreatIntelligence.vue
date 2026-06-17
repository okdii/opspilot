<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useSecurityStore } from '@/stores/security'
import { useSecurityActionsStore, type SecurityActionRow } from '@/stores/securityActions'
import { useAuthStore } from '@/stores/auth'
import { useNotify } from '@/composables/useNotify'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import Pager from '@/components/ui/Pager.vue'

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

onMounted(() => {
  events.fetchEvents(props.serverId, 0)
  actions.fetchActions(props.serverId, 0)
  actions.fetchPending(props.serverId)
  actions.fetchSummary(props.serverId)
  loadSettings()
  // Poll the current page in place so live updates appear without losing the page.
  evPoll = setInterval(() => {
    events.fetchEvents(props.serverId)
    actions.fetchSummary(props.serverId)
  }, 60 * 1000)
  acPoll = setInterval(() => {
    actions.fetchActions(props.serverId)
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

// Server returns the ledger newest-first, already paginated.
const ledger = computed(() => actions.actions)

const settingsOn = computed(() => actions.settings?.auto_response_enabled ?? false)

// ── Pagination ────────────────────────────────────────────────────────────────
function goEvents(p: number) { events.fetchEvents(props.serverId, p) }
function goLedger(p: number) { actions.fetchActions(props.serverId, p) }

// ── Helpers ─────────────────────────────────────────────────────────────────
function rel(ts: string): string {
  const s = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000)
  if (s < 60) return `${Math.floor(s)}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

// Ledger status → StatusBadge alert tone vocabulary (matches the prior panel).
function tone(s: string): string {
  return ({ executed: 'resolved', reverted: 'snoozed', expired: 'snoozed',
            rejected: 'suppressed', failed: 'firing' } as Record<string, string>)[s] ?? 'snoozed'
}

function tierLabel(a: SecurityActionRow): string {
  const bits = [`Tier ${a.tier}`, a.actor]
  if (a.confidence) bits.push(a.confidence)
  return bits.join(' · ')
}

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
  try { await actions.approve(props.serverId, a.id); notify.success('Action approved and executed') }
  catch (e) { notify.error(e as Error) }
}
async function reject(a: SecurityActionRow) {
  try { await actions.reject(props.serverId, a.id); notify.info('Action rejected') }
  catch (e) { notify.error(e as Error) }
}
async function undo(a: SecurityActionRow) {
  const label = `${a.action_type} ${a.target ?? ''}`.trim()
  if (!window.confirm(`Undo: ${label}?`)) return
  try { await actions.undo(props.serverId, a.id); notify.success('Action reverted') }
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

    <!-- ZONE 3 — Feed + Ledger -->
    <div class="grid">
      <!-- Threat detection feed -->
      <section class="col">
        <header class="col__head"><span>Threat Detection Feed</span><span class="col__hint">live · 1m</span></header>
        <div class="col__body">
          <div v-if="events.loading && !events.events.length" class="skeleton">
            <div v-for="n in 3" :key="n" class="skeleton__row" />
          </div>
          <p v-else-if="events.error" class="state-msg error" role="alert">{{ events.error }}</p>
          <div v-else-if="!events.events.length" class="state-msg empty">No security events detected.</div>
          <ul v-else class="feed">
            <li v-for="e in events.events" :key="e.id" class="event" :class="{ 'event--resolved': e.state === 'resolved' }">
              <StatusBadge :status="e.severity" kind="severity" class="event__sev" />
              <div class="event__body">
                <div class="event__top">
                  <span class="event__type">{{ e.type }}</span>
                  <span class="event__stage">{{ e.stage }}</span>
                </div>
                <p class="event__msg" :title="e.message">{{ e.message }}</p>
              </div>
              <time class="event__time" :datetime="e.at">{{ rel(e.at) }}</time>
            </li>
          </ul>
        </div>
        <Pager :page="events.page" :page-size="events.pageSize" :total="events.total"
               :disabled="events.loading" @update:page="goEvents" />
      </section>

      <!-- Response activity ledger -->
      <section class="col">
        <header class="col__head"><span>Response Activity</span><span class="col__hint">ledger</span></header>
        <div class="col__body">
          <div v-if="!ledger.length" class="state-msg empty">No response actions taken.</div>
          <ul v-else class="ledger">
            <li v-for="a in ledger" :key="a.id" class="action"
                :class="{ 'action--pending': a.status === 'pending_approval' }">
              <div class="action__top">
                <StatusBadge v-if="a.status !== 'pending_approval'" :status="tone(a.status)" kind="alert" class="action__chip" />
                <span v-else class="action__pendchip">Pending</span>
                <span class="action__type">{{ a.action_type }}</span>
                <time class="action__time">{{ rel(a.created_at) }}</time>
              </div>
              <p v-if="a.target" class="action__target">{{ a.target }}</p>
              <p v-if="a.detail" class="action__detail" :title="a.detail">{{ a.detail }}</p>
              <div class="action__foot">
                <span class="action__tier">{{ tierLabel(a) }}</span>
                <div class="action__btns">
                  <template v-if="a.status === 'pending_approval'">
                    <VaButton size="small" color="success" :disabled="!auth.isAdmin" @click="approve(a)">Approve</VaButton>
                    <VaButton size="small" preset="secondary" :disabled="!auth.isAdmin" @click="reject(a)">Reject</VaButton>
                  </template>
                  <VaButton v-else-if="a.status === 'executed' && a.reversible" size="small" preset="secondary"
                            :disabled="!auth.isAdmin" @click="undo(a)">Undo</VaButton>
                  <span v-else-if="a.status === 'executed' && !a.reversible" class="muted not-rev">not reversible</span>
                </div>
              </div>
            </li>
          </ul>
        </div>
        <Pager :page="actions.page" :page-size="actions.pageSize" :total="actions.total"
               :disabled="actions.loading" @update:page="goLedger" />
      </section>
    </div>
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

/* Zone 3 */
.grid { display: grid; grid-template-columns: 1.15fr 1fr; gap: 16px; }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
.col { background: var(--surface, #161d2e); border: 1px solid var(--border, #243049);
  border-radius: 12px; overflow: hidden; }
.col__head { display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--border, #243049);
  font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--muted, #94a3b8); font-weight: 600; }
.col__hint { letter-spacing: 0; text-transform: none; color: var(--muted, #64748b); }
.col__body { padding: 4px 0; }

.feed, .ledger { list-style: none; margin: 0; padding: 0; }

.event { display: flex; gap: 12px; padding: 12px 16px; border-bottom: 1px solid var(--border, #1c2638); }
.event:last-child { border-bottom: none; }
.event--resolved { opacity: 0.6; }
.event__sev { flex: none; margin-top: 2px; }
.event__body { flex: 1; min-width: 0; }
.event__top { display: flex; align-items: center; gap: 9px; margin-bottom: 3px; }
.event__type { font-weight: 600; font-size: 13.5px; color: var(--text, #e8edf6); }
.event__stage { font-size: 11px; padding: 1px 7px; border-radius: 5px;
  background: var(--surface-2, #1a2336); color: var(--muted, #9aa4b2); border: 1px solid var(--border, #243049); }
.event__msg { font-size: 12.5px; color: var(--muted, #b6c2d6); margin: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.event__time { font-size: 11px; color: var(--muted, #64748b); flex: none; font-variant-numeric: tabular-nums; }

.action { padding: 12px 16px; border-bottom: 1px solid var(--border, #1c2638); }
.action:last-child { border-bottom: none; }
.action--pending { background: rgba(245,158,11,0.06); }
.action__top { display: flex; align-items: center; gap: 9px; margin-bottom: 5px; }
.action__chip { flex: none; }
.action__pendchip { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
  padding: 3px 8px; border-radius: 4px; background: rgba(245,158,11,0.15); color: var(--amber, #fbbf24); }
.action__type { font-weight: 600; font-size: 13.5px; color: var(--text, #e8edf6); font-family: monospace; }
.action__time { margin-left: auto; font-size: 11px; color: var(--muted, #64748b); flex: none; font-variant-numeric: tabular-nums; }
.action__target { font-size: 12.5px; color: var(--text, #b6c2d6); margin: 0 0 3px; word-break: break-all; font-family: monospace; }
.action__detail { font-size: 12px; color: var(--muted, #94a3b8); margin: 0 0 7px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.action__foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.action__tier { font-size: 11px; color: var(--muted, #64748b); }
.action__btns { display: flex; gap: 8px; align-items: center; }
.not-rev { font-size: 11px; }

.muted { color: var(--muted, #94a3b8); }
.state-msg { padding: 28px 16px; text-align: center; font-size: 13px; color: var(--muted, #94a3b8); }
.state-msg.error { color: var(--red, #ef4444); }

.skeleton { padding: 8px 16px; }
.skeleton__row { height: 44px; border-radius: 8px; margin-bottom: 8px;
  background: linear-gradient(90deg, #1b1f2a 25%, #232838 37%, #1b1f2a 63%); background-size: 400% 100%;
  animation: shimmer 1.4s ease infinite; }
@keyframes shimmer { 0% { background-position: 100% 0; } 100% { background-position: 0 0; } }
@media (prefers-reduced-motion: reduce) { .skeleton__row { animation: none; } }
</style>
