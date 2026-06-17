<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useSecurityActionsStore } from '@/stores/securityActions'
import { useAuthStore } from '@/stores/auth'
import { useNotify } from '@/composables/useNotify'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import AutoResponseSettings from './AutoResponseSettings.vue'

const props = defineProps<{ serverId: string }>()
const store = useSecurityActionsStore()
const auth = useAuthStore()
const notify = useNotify()
let poll: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  store.fetchActions(props.serverId)
  poll = setInterval(() => store.fetchActions(props.serverId), 30 * 1000)
})
onUnmounted(() => { if (poll) clearInterval(poll) })

const pending = computed(() => store.actions.filter(a => a.status === 'pending_approval'))
const history = computed(() => store.actions.filter(a => a.status !== 'pending_approval'))

// Map ledger status → StatusBadge alert tone vocabulary. executed (success) must
// read differently from failed: green for a successful remediation, red for a
// failure; reverted/expired are muted (no longer active), rejected suppressed.
function tone(s: string): string {
  return ({ executed: 'resolved', reverted: 'snoozed', expired: 'snoozed',
            rejected: 'suppressed', failed: 'firing' } as Record<string, string>)[s] ?? 'snoozed'
}

async function approve(id: number, label: string) {
  if (!window.confirm(`Approve and run: ${label}?\nThis acts on the server now.`)) return
  try { await store.approve(props.serverId, id); notify.success('Action approved and executed') }
  catch (e) { notify.error(e as Error) }
}
async function reject(id: number) {
  try { await store.reject(props.serverId, id); notify.info('Action rejected') }
  catch (e) { notify.error(e as Error) }
}
async function undo(id: number, label: string) {
  if (!window.confirm(`Undo: ${label}?`)) return
  try { await store.undo(props.serverId, id); notify.success('Action reverted') }
  catch (e) { notify.error(e as Error) }
}
</script>

<template>
  <section class="sec-actions">
    <header class="sec-actions__head"><h3>Response Actions</h3></header>

    <AutoResponseSettings :server-id="serverId" />

    <div v-if="pending.length" class="sec-actions__pending">
      <h4>Pending approval</h4>
      <div v-for="a in pending" :key="a.id" class="approve-card">
        <div class="approve-card__info">
          <strong class="danger">{{ a.action_type }}</strong>
          <span class="target">{{ a.target }}</span>
          <span class="muted">{{ a.detail }}</span>
        </div>
        <div class="approve-card__btns">
          <VaButton size="small" color="danger" :disabled="!auth.isAdmin"
                    @click="approve(a.id, `${a.action_type} ${a.target}`)">Approve</VaButton>
          <VaButton size="small" preset="secondary" :disabled="!auth.isAdmin"
                    @click="reject(a.id)">Reject</VaButton>
        </div>
      </div>
    </div>

    <div class="sec-actions__history">
      <h4>History</h4>
      <p v-if="!history.length && !pending.length" class="empty">No response actions taken.</p>
      <ul v-else class="hist-list">
        <li v-for="a in history" :key="a.id" class="hist-row">
          <StatusBadge :status="tone(a.status)" kind="alert" class="hist-row__chip" />
          <span class="hist-row__type">{{ a.action_type }}</span>
          <span class="hist-row__target" :title="a.detail ?? ''">{{ a.target }}</span>
          <span class="hist-row__status muted">{{ a.status }}</span>
          <VaButton v-if="a.status === 'executed' && a.reversible" size="small" preset="secondary"
                    :disabled="!auth.isAdmin"
                    @click="undo(a.id, `${a.action_type} ${a.target}`)">Undo</VaButton>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.sec-actions { display: flex; flex-direction: column; gap: 14px; margin-bottom: 1.5rem; }
.sec-actions__head h3, .sec-actions h4 { margin: 0; font-size: 1rem; font-weight: 600; }
.sec-actions h4 { font-size: 0.85rem; margin-bottom: 0.5rem; color: var(--va-text-secondary, #9aa4b2); }
.approve-card { display: flex; justify-content: space-between; align-items: center; gap: 12px;
  padding: 0.7rem 0.9rem; border-radius: 8px; border: 1px solid var(--red, #ef4444);
  background: rgba(239,68,68,0.06); margin-bottom: 0.4rem; }
.approve-card__info { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.approve-card__btns { display: flex; gap: 8px; flex: none; }
.danger { color: var(--red, #ef4444); }
.target { font-variant-numeric: tabular-nums; color: var(--va-text-primary, #e6e9ef); }
.muted { color: var(--va-text-secondary, #9aa4b2); font-size: 0.78rem; }
.hist-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.25rem; }
.hist-row { display: grid; grid-template-columns: auto auto 1fr auto auto; align-items: center; gap: 0.75rem;
  padding: 0.55rem 0.75rem; border-radius: 8px; background: var(--va-background-secondary, #1b1f2a); }
.hist-row__target { overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-variant-numeric: tabular-nums; }
.empty { color: var(--va-text-secondary, #9aa4b2); padding: 1rem 0; }
</style>
