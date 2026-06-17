<script setup lang="ts">
import type { Incident } from '@/stores/security'
import type { SecurityActionRow } from '@/stores/securityActions'
import { relativeTime } from '@/utils/time'
import StatusBadge from '@/components/ui/StatusBadge.vue'

defineProps<{ incidents: Incident[]; isAdmin: boolean }>()
const emit = defineEmits<{
  (e: 'approve', a: SecurityActionRow): void
  (e: 'reject', a: SecurityActionRow): void
  (e: 'undo', a: SecurityActionRow): void
}>()

// HH:MM clock — anchors each row in the chronology so the stream reads in order.
function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

// Mitigation status → StatusBadge alert-tone vocabulary (shared severity colours).
function tone(s: string): string {
  return ({ executed: 'resolved', reverted: 'snoozed', expired: 'snoozed',
            rejected: 'suppressed', failed: 'firing' } as Record<string, string>)[s] ?? 'snoozed'
}

function tierLabel(a: SecurityActionRow): string {
  const bits = [`Tier ${a.tier}`, a.actor]
  if (a.confidence) bits.push(a.confidence)
  return bits.join(' · ')
}
</script>

<template>
  <ol class="tl">
    <li v-for="inc in incidents" :key="inc.id"
        class="inc" :class="[`sev-${inc.severity}`, { 'inc--resolved': inc.state === 'resolved' }]">
      <!-- Detection node -->
      <div class="det">
        <span class="det__dot" aria-hidden="true" />
        <div class="det__main">
          <div class="det__line">
            <time class="det__clock" :datetime="inc.at">{{ clock(inc.at) }}</time>
            <span class="det__type">{{ inc.type }}</span>
            <span class="det__stage">{{ inc.stage }}</span>
            <span class="det__sev">{{ inc.severity }}</span>
            <span v-if="inc.state === 'resolved'" class="det__resolved">resolved</span>
            <time class="det__rel">{{ relativeTime(inc.at) }}</time>
          </div>
          <p class="det__msg" :title="inc.message">{{ inc.message }}</p>
        </div>
      </div>

      <!-- Response chronology (indented under the attack, oldest first) -->
      <ul v-if="inc.actions.length" class="resp">
        <li v-for="a in inc.actions" :key="a.id" class="resp__item">
          <div class="resp__line">
            <time class="resp__clock" :datetime="a.created_at">{{ clock(a.created_at) }}</time>
            <span class="resp__verb">{{ a.action_type }}</span>
            <span v-if="a.target" class="resp__target">{{ a.target }}</span>
            <StatusBadge v-if="a.status !== 'pending_approval'"
                         :status="tone(a.status)" kind="alert" class="resp__chip" />
            <span v-else class="resp__pend">pending approval</span>
          </div>
          <div class="resp__foot">
            <span class="resp__tier">{{ tierLabel(a) }}</span>
            <p v-if="a.detail" class="resp__detail" :title="a.detail">{{ a.detail }}</p>
            <div class="resp__btns">
              <template v-if="a.status === 'pending_approval'">
                <VaButton size="small" color="success" :disabled="!isAdmin" @click="emit('approve', a)">Approve</VaButton>
                <VaButton size="small" preset="secondary" :disabled="!isAdmin" @click="emit('reject', a)">Reject</VaButton>
              </template>
              <VaButton v-else-if="a.status === 'executed' && a.reversible" size="small" preset="secondary"
                        :disabled="!isAdmin" @click="emit('undo', a)">Undo</VaButton>
              <span v-else-if="a.status === 'executed' && !a.reversible" class="muted not-rev">not reversible</span>
            </div>
          </div>
        </li>
      </ul>
      <p v-else class="resp resp--none">monitored — no automated response</p>
    </li>
  </ol>
</template>

<style scoped>
.tl { list-style: none; margin: 0; padding: 0; }

/* One incident: detection + its indented response rail. */
.inc { position: relative; padding: 14px 16px 16px 38px; border-bottom: 1px solid var(--border, #1c2638); }
.inc:last-child { border-bottom: none; }
.inc--resolved { opacity: 0.62; }

/* Detection node ----------------------------------------------------------- */
.det { position: relative; }
.det__dot {
  position: absolute; left: -25px; top: 4px; width: 11px; height: 11px; border-radius: 50%;
  background: var(--muted, #64748b); box-shadow: 0 0 0 4px var(--surface, #161d2e);
}
.sev-critical .det__dot { background: #ef4444; box-shadow: 0 0 0 4px var(--surface, #161d2e), 0 0 10px rgba(239,68,68,.5); }
.sev-warning  .det__dot { background: #f59e0b; box-shadow: 0 0 0 4px var(--surface, #161d2e); }

.det__line { display: flex; align-items: baseline; gap: 9px; flex-wrap: wrap; }
.det__clock { font-size: 12px; font-weight: 700; color: var(--text, #e8edf6);
  font-variant-numeric: tabular-nums; }
.det__type { font-weight: 600; font-size: 13.5px; color: var(--text, #e8edf6); font-family: monospace; }
.det__stage { font-size: 11px; padding: 1px 7px; border-radius: 5px;
  background: var(--surface-2, #1a2336); color: var(--muted, #9aa4b2); border: 1px solid var(--border, #243049); }
.det__sev { font-size: 10px; text-transform: uppercase; letter-spacing: .5px; font-weight: 700; }
.sev-critical .det__sev { color: #f87171; }
.sev-warning  .det__sev { color: #fbbf24; }
.det__resolved { font-size: 10px; text-transform: uppercase; letter-spacing: .5px; color: var(--green, #4ade80); }
.det__rel { margin-left: auto; font-size: 11px; color: var(--muted, #64748b);
  font-variant-numeric: tabular-nums; flex: none; }
.det__msg { font-size: 12.5px; color: var(--muted, #b6c2d6); margin: 4px 0 0; line-height: 1.5;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Response rail ------------------------------------------------------------ */
/* Vertical connector linking each mitigation back to the detection above. */
.resp { list-style: none; margin: 10px 0 0; padding: 0 0 0 4px;
  position: relative; border-left: 2px solid var(--border, #243049); }
.sev-critical .resp { border-left-color: rgba(239,68,68,.3); }
.sev-warning  .resp { border-left-color: rgba(245,158,11,.3); }

.resp__item { position: relative; padding: 7px 0 7px 16px; }
.resp__item::before {
  content: ''; position: absolute; left: 0; top: 14px; width: 11px; height: 2px;
  background: var(--border, #243049);
}
.sev-critical .resp__item::before { background: rgba(239,68,68,.3); }
.sev-warning  .resp__item::before { background: rgba(245,158,11,.3); }

.resp__line { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
.resp__clock { font-size: 11px; color: var(--muted, #94a3b8); font-variant-numeric: tabular-nums; flex: none; }
.resp__verb { font-weight: 600; font-size: 13px; color: var(--text, #e8edf6); font-family: monospace; }
.resp__target { font-size: 12px; color: var(--muted, #b6c2d6); font-family: monospace; word-break: break-all; }
.resp__chip { flex: none; }
.resp__pend { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em;
  padding: 3px 8px; border-radius: 4px; background: rgba(245,158,11,.15); color: var(--amber, #fbbf24); }

.resp__foot { display: flex; align-items: center; gap: 12px; margin-top: 5px; flex-wrap: wrap; }
.resp__tier { font-size: 11px; color: var(--muted, #64748b); flex: none; }
.resp__detail { font-size: 11.5px; color: var(--muted, #94a3b8); margin: 0; min-width: 0; flex: 1;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.resp__btns { display: flex; gap: 8px; align-items: center; margin-left: auto; flex: none; }

.resp--none { margin: 8px 0 0 4px; padding-left: 16px; border-left: 2px dashed var(--border, #243049);
  font-size: 12px; color: var(--muted, #64748b); font-style: italic; }

.muted { color: var(--muted, #94a3b8); }
.not-rev { font-size: 11px; }
</style>
