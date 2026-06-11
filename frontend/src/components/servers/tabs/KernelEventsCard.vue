<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getKernelEvents, type KernelEventsResponse } from '@/services/api'
import type { MetricRange } from '@/types'

const props = defineProps<{ serverId: string; range: MetricRange }>()
const router = useRouter()

const loading = ref(false)
const data = ref<KernelEventsResponse | null>(null)
const error = ref(false)

async function load() {
  if (!props.serverId) return
  loading.value = true
  error.value = false
  try {
    data.value = await getKernelEvents(props.serverId, props.range)
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => [props.serverId, props.range], load)

function viewAll() {
  router.push({ name: 'server-detail', params: { id: props.serverId }, query: { tab: 'Logs', source: 'kernel' } })
}

const rangeLabel = computed(() => props.range)

const hasEvents = computed(() => (data.value?.events?.length ?? 0) > 0)

function severityBg(sev: string): string {
  if (['emerg', 'alert', 'crit'].includes(sev)) return '#3d1f1f'
  if (sev === 'err') return '#3d2e1f'
  return '#2a2920'
}
function severityColor(sev: string): string {
  if (['emerg', 'alert', 'crit'].includes(sev)) return '#e74c3c'
  if (sev === 'err') return '#f39c12'
  return '#f1c40f'
}
function fmtTime(ts: string): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
function truncate(msg: string): string {
  return msg.length > 120 ? msg.slice(0, 120) + '…' : msg
}
</script>

<template>
  <section class="card">
    <div class="ke-header">
      <h3>⚡ Kernel Events</h3>
      <button class="ke-view-all" @click="viewAll">View all in Logs →</button>
    </div>

    <template v-if="loading">
      <div class="ke-skeleton" v-for="i in 3" :key="i" />
    </template>

    <div v-else-if="error" class="ke-empty">Failed to load kernel events</div>

    <template v-else-if="data">
      <div class="ke-strip">
        <div class="ke-tile ke-red">
          <span class="ke-num">{{ (data.counts.emerg ?? 0) + (data.counts.alert ?? 0) }}</span>
          <span class="ke-lbl">emerg/alert</span>
        </div>
        <div class="ke-tile ke-red">
          <span class="ke-num">{{ data.counts.crit ?? 0 }}</span>
          <span class="ke-lbl">crit</span>
        </div>
        <div class="ke-tile ke-orange">
          <span class="ke-num">{{ data.counts.err ?? 0 }}</span>
          <span class="ke-lbl">err</span>
        </div>
        <div class="ke-tile ke-yellow">
          <span class="ke-num">{{ data.counts.warn ?? 0 }}</span>
          <span class="ke-lbl">warn</span>
        </div>
      </div>

      <template v-if="hasEvents">
        <div class="ke-section-lbl">Recent events (last {{ rangeLabel }})</div>
        <div class="ke-list">
          <div class="ke-row" v-for="(ev, i) in data.events" :key="i">
            <span
              class="ke-badge"
              :style="{ background: severityBg(ev.severity), color: severityColor(ev.severity) }"
            >{{ ev.severity }}</span>
            <span class="ke-time">{{ fmtTime(ev.ts) }}</span>
            <span class="ke-msg" :title="ev.message">{{ truncate(ev.message) }}</span>
          </div>
        </div>
      </template>

      <div v-else class="ke-empty">✓ No kernel warnings or errors in the last {{ rangeLabel }}</div>
    </template>
  </section>
</template>

<style scoped>
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }
.ke-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.ke-header h3 { font-size: 13px; color: var(--text); font-weight: 600; margin: 0; }
.ke-view-all { background: none; border: none; color: var(--accent-2); font-size: 12px; cursor: pointer; padding: 0; }
.ke-view-all:hover { text-decoration: underline; }

.ke-strip { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 16px; }
.ke-tile { border-radius: 6px; padding: 8px 10px; text-align: center; border: 1px solid transparent; display: flex; flex-direction: column; align-items: center; }
.ke-tile.ke-red { background: #2d1f1f; border-color: #5a2020; }
.ke-tile.ke-orange { background: #2d2414; border-color: #5a4020; }
.ke-tile.ke-yellow { background: #2a2920; border-color: #4a4820; }
.ke-num { font-size: 20px; font-weight: 700; line-height: 1.2; }
.ke-tile.ke-red .ke-num { color: #e74c3c; }
.ke-tile.ke-orange .ke-num { color: #f39c12; }
.ke-tile.ke-yellow .ke-num { color: #f1c40f; }
.ke-lbl { font-size: 9px; text-transform: uppercase; letter-spacing: .5px; margin-top: 2px; }
.ke-tile.ke-red .ke-lbl { color: #e74c3c; }
.ke-tile.ke-orange .ke-lbl { color: #f39c12; }
.ke-tile.ke-yellow .ke-lbl { color: #f1c40f; }

.ke-section-lbl { font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: .5px; margin-bottom: 8px; }
.ke-list { display: flex; flex-direction: column; }
.ke-row { display: flex; align-items: flex-start; gap: 8px; padding: 7px 0; border-bottom: 1px solid var(--border); }
.ke-row:last-child { border-bottom: none; }
.ke-badge { padding: 2px 6px; border-radius: 3px; font-size: 9px; white-space: nowrap; min-width: 36px; text-align: center; margin-top: 1px; font-family: monospace; }
.ke-time { color: var(--muted); font-size: 10px; white-space: nowrap; margin-top: 2px; }
.ke-msg { color: var(--text); font-size: 11px; line-height: 1.4; font-family: monospace; word-break: break-all; }

.ke-empty { text-align: center; padding: 24px 0; color: var(--muted); font-size: 12px; }
.ke-skeleton { height: 28px; background: var(--border); border-radius: 4px; margin-bottom: 6px; animation: pulse 1.5s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .4; } }
</style>
