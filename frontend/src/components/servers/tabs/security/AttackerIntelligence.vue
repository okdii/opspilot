<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useAttackersStore, type Attacker, type AttackerSort } from '@/stores/attackers'
import type { SecurityEvent } from '@/stores/security'
import { relativeTime } from '@/utils/time'
import Pager from '@/components/ui/Pager.vue'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import AttackTrendChart from './AttackTrendChart.vue'

const props = defineProps<{ serverId: string }>()
const store = useAttackersStore()

const expanded = ref<string | null>(null)
const events = ref<SecurityEvent[]>([])
const eventsLoading = ref(false)

let poll: ReturnType<typeof setInterval> | undefined

onMounted(async () => {
  await Promise.all([store.fetchAttackers(props.serverId, 0), store.fetchTrend(props.serverId)])
  poll = setInterval(() => {
    store.fetchAttackers(props.serverId)
    store.fetchTrend(props.serverId)
  }, 60_000)
})
onUnmounted(() => { if (poll) clearInterval(poll) })

const SORTS: { key: AttackerSort; label: string }[] = [
  { key: 'last_seen', label: 'Recent' },
  { key: 'events', label: 'Most events' },
  { key: 'severity', label: 'Most severe' },
]

async function toggle(ip: string) {
  if (expanded.value === ip) { expanded.value = null; return }
  expanded.value = ip
  eventsLoading.value = true
  events.value = []
  try {
    events.value = (await store.fetchAttackerEvents(props.serverId, ip)).items
  } catch {
    events.value = []
  } finally {
    eventsLoading.value = false
  }
}

// AbuseIPDB 0–100 confidence → colour band.
function scoreTone(score: number | null): string {
  if (score == null) return 'unknown'
  if (score >= 75) return 'high'
  if (score >= 25) return 'mid'
  return 'low'
}

function flag(cc: string | null): string {
  if (!cc || cc.length !== 2) return ''
  return String.fromCodePoint(...[...cc.toUpperCase()].map(c => 0x1f1e6 + c.charCodeAt(0) - 65))
}

const STAGE_ORDER = ['Recon', 'Exploit', 'Upload', 'Execute', 'Persist', 'Cover-tracks']
function reached(a: Attacker, stage: string): boolean {
  return a.stages.includes(stage)
}
</script>

<template>
  <div class="attackers">
    <AttackTrendChart :trend="store.trend" />

    <section class="card">
      <header class="head">
        <h3>Top Attackers</h3>
        <div class="sortbar">
          <button v-for="s in SORTS" :key="s.key" class="sort"
                  :class="{ active: store.sort === s.key }"
                  @click="store.setSort(serverId, s.key)">{{ s.label }}</button>
        </div>
      </header>

      <div v-if="store.loading && !store.attackers.length" class="state">Loading attackers…</div>
      <div v-else-if="store.error" class="state err">{{ store.error }}</div>
      <div v-else-if="!store.total" class="state">No attackers detected on this server.</div>

      <ul v-else class="list">
        <li v-for="a in store.attackers" :key="a.ip" class="row" :class="{ open: expanded === a.ip }">
          <button class="row__main" @click="toggle(a.ip)">
            <span class="ip">{{ a.ip }}</span>
            <span class="rep" :class="`rep--${scoreTone(a.intel?.abuse_score ?? null)}`">
              <template v-if="a.intel?.abuse_score != null">{{ a.intel.abuse_score }}</template>
              <template v-else>—</template>
            </span>
            <span v-if="a.intel?.country_code" class="geo">{{ flag(a.intel.country_code) }} {{ a.intel.isp || a.intel.country_code }}</span>
            <span class="count">{{ a.event_count }} events</span>
            <span class="chain" aria-label="kill-chain stages reached">
              <span v-for="st in STAGE_ORDER" :key="st" class="seg"
                    :class="{ hit: reached(a, st) }" :title="st" />
            </span>
            <StatusBadge v-if="a.blocked" status="resolved" kind="alert" class="blk" />
            <time class="seen">{{ relativeTime(a.last_seen) }}</time>
          </button>

          <div v-if="expanded === a.ip" class="detail">
            <dl class="intel" v-if="a.intel">
              <div><dt>Abuse score</dt><dd>{{ a.intel.abuse_score ?? '—' }}/100</dd></div>
              <div><dt>Reports</dt><dd>{{ a.intel.total_reports ?? '—' }}</dd></div>
              <div><dt>ISP</dt><dd>{{ a.intel.isp ?? '—' }}</dd></div>
              <div><dt>Usage</dt><dd>{{ a.intel.usage_type ?? '—' }}</dd></div>
            </dl>
            <p v-else class="intel-off">AbuseIPDB disabled — enable it in Settings → General for reputation scoring.</p>

            <div v-if="eventsLoading" class="state">Loading events…</div>
            <ul v-else class="evs">
              <li v-for="e in events" :key="e.id" class="ev" :class="`sev-${e.severity}`">
                <span class="ev__stage">{{ e.stage }}</span>
                <span class="ev__type">{{ e.type }}</span>
                <span class="ev__msg" :title="e.message">{{ e.message }}</span>
                <time class="ev__at">{{ relativeTime(e.at) }}</time>
              </li>
            </ul>
          </div>
        </li>
      </ul>

      <Pager
        v-if="store.total > store.pageSize"
        :page="store.page"
        :page-size="store.pageSize"
        :total="store.total"
        @update:page="(p: number) => store.fetchAttackers(serverId, p)"
      />
    </section>
  </div>
</template>

<style scoped>
.attackers { display: flex; flex-direction: column; gap: 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; gap: 12px; flex-wrap: wrap; }
.head h3 { font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.sortbar { display: flex; gap: 2px; }
.sort { background: none; border: none; color: var(--muted); font-size: 12px; padding: 4px 10px; cursor: pointer; border-radius: 6px; }
.sort:hover { color: var(--text); }
.sort.active { color: var(--accent-2); background: var(--surface-2, #1a2336); }

.state { color: var(--muted); font-size: 13px; padding: 20px 0; text-align: center; }
.state.err { color: var(--red, #f87171); }

.list { list-style: none; margin: 0; padding: 0; }
.row { border-bottom: 1px solid var(--border); }
.row:last-child { border-bottom: none; }
.row__main { width: 100%; display: flex; align-items: center; gap: 12px; padding: 11px 4px; background: none; border: none; cursor: pointer; text-align: left; }
.row__main:hover { background: rgba(255,255,255,0.02); }
.ip { font-family: ui-monospace, monospace; font-size: 13.5px; color: var(--text); font-weight: 600; }
.rep { font-size: 12px; font-weight: 700; min-width: 30px; text-align: center; padding: 2px 6px; border-radius: 5px; font-variant-numeric: tabular-nums; }
.rep--high { background: rgba(239,68,68,0.18); color: #f87171; }
.rep--mid { background: rgba(245,158,11,0.16); color: #fbbf24; }
.rep--low { background: rgba(74,222,128,0.14); color: #4ade80; }
.rep--unknown { background: var(--surface-2, #1a2336); color: var(--muted); }
.geo { font-size: 12px; color: var(--muted); }
.count { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.chain { display: inline-flex; gap: 3px; margin-left: auto; }
.seg { width: 14px; height: 6px; border-radius: 2px; background: var(--surface-2, #243049); }
.seg.hit { background: #ef4444; }
.blk { flex: none; }
.seen { font-size: 11px; color: var(--muted); flex: none; font-variant-numeric: tabular-nums; }

.detail { padding: 4px 8px 14px 8px; }
.intel { display: flex; flex-wrap: wrap; gap: 18px; margin: 0 0 12px; }
.intel div { display: flex; flex-direction: column; gap: 2px; }
.intel dt { font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }
.intel dd { margin: 0; font-size: 13px; color: var(--text); }
.intel-off { font-size: 12px; color: var(--muted); font-style: italic; margin: 0 0 12px; }

.evs { list-style: none; margin: 0; padding: 0; border-left: 2px solid var(--border); }
.ev { display: flex; align-items: center; gap: 10px; padding: 6px 0 6px 12px; }
.ev__stage { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); min-width: 78px; }
.ev__type { font-family: ui-monospace, monospace; font-size: 12.5px; color: var(--text); }
.ev__msg { font-size: 12px; color: var(--muted); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ev__at { font-size: 11px; color: var(--muted); flex: none; }
.sev-critical .ev__type { color: #f87171; }
</style>
