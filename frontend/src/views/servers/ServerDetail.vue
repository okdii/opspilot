<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MetricChart from '@/components/charts/MetricChart.vue'
import { PageHeader, StatusBadge } from '@/components/ui'
import MaintenanceSlideOver from '@/components/servers/MaintenanceSlideOver.vue'
import OverviewTab from '@/components/servers/tabs/OverviewTab.vue'
import CpuTab from '@/components/servers/tabs/CpuTab.vue'
import MemoryTab from '@/components/servers/tabs/MemoryTab.vue'
import DiskTab from '@/components/servers/tabs/DiskTab.vue'
import NetworkTab from '@/components/servers/tabs/NetworkTab.vue'
import SystemTab from '@/components/servers/tabs/SystemTab.vue'
import ProcessesTab from '@/components/servers/tabs/ProcessesTab.vue'
import { getServer } from '@/services/api'
import { useMetricsStore } from '@/stores/metrics'
import { useOrgStore } from '@/stores/org'
import { useAuthStore } from '@/stores/auth'
import { wsClient } from '@/utils/ws'
import {
  cpuTotal, humanBytes, humanRate, labeledList, maxLabeled, pickLabel,
  realMounts, relativeTime, scalarValue, usageColor,
} from '@/utils/metrics'
import type { MetricRange, Server } from '@/types'

const route = useRoute()
const router = useRouter()
const metrics = useMetricsStore()
const orgStore = useOrgStore()
const auth = useAuthStore()

const serverId = computed(() => route.params.id as string)
const server = ref<Server | null>(null)
const maintenanceOpen = ref(false)
const menuOpen = ref(false)

// --- Tabs ------------------------------------------------------------------
const TABS = ['Overview', 'CPU', 'Memory', 'Disk', 'Network', 'System', 'Processes'] as const
type Tab = (typeof TABS)[number]
const TAB_COMPONENTS = {
  Overview: OverviewTab, CPU: CpuTab, Memory: MemoryTab,
  Disk: DiskTab, Network: NetworkTab, System: SystemTab, Processes: ProcessesTab,
}
const activeTab = ref<Tab>('Overview')
const RANGES: MetricRange[] = ['1h', '6h', '24h', '7d', '30d']
const currentRange = computed(() => metrics.rangeFor(activeTab.value))
function setRange(r: MetricRange) {
  metrics.setRange(activeTab.value, r)
}

// --- Header / status -------------------------------------------------------
const displayStatus = computed(() =>
  metrics.maintenance.active ? 'maintenance' : (server.value?.status ?? 'pending'),
)
const subtitle = computed(() => {
  if (!server.value) return ''
  const parts = [server.value.host, server.value.os_distro, server.value.kernel_version].filter(Boolean)
  return parts.join('  ·  ')
})

// --- Gauges (live from latestValues) ---------------------------------------
const cpu = computed(() => cpuTotal(metrics.latestValues))
const cpuUser = computed(() => pickLabel(metrics.latestValues, 'cpu.usage_user', 'cpu', 'cpu-total'))
const cpuSys = computed(() => pickLabel(metrics.latestValues, 'cpu.usage_system', 'cpu', 'cpu-total'))
const cpuWait = computed(() => pickLabel(metrics.latestValues, 'cpu.usage_iowait', 'cpu', 'cpu-total'))

const ram = computed(() => scalarValue(metrics.latestValues, 'mem.used_percent'))
const ramUsed = computed(() => scalarValue(metrics.latestValues, 'mem.used'))
const ramTotal = computed(() => scalarValue(metrics.latestValues, 'mem.total'))

const diskMax = computed(() => maxLabeled(metrics.latestValues, 'disk.used_percent'))
const diskMounts = computed(() => realMounts(labeledList(metrics.latestValues, 'disk.used_percent')))

// Network rate: latest gives cumulative counters → diff consecutive samples.
const rxRate = ref<number | null>(null)
const txRate = ref<number | null>(null)
const ifaceName = ref<string>('—')
let prevRx: { value: number; t: number } | null = null
let prevTx: { value: number; t: number } | null = null

function busiest(name: string): { value: number; t: number; iface: string } | null {
  const list = labeledList(metrics.latestValues, name).filter((e) => e.value != null)
  if (!list.length) return null
  const top = list.reduce((a, b) => ((b.value ?? 0) > (a.value ?? 0) ? b : a))
  return { value: top.value as number, t: Date.parse(top.time), iface: top.labels.interface ?? '—' }
}

watch(() => metrics.latestValues, () => {
  const rx = busiest('net.bytes_recv')
  const tx = busiest('net.bytes_sent')
  if (rx) {
    if (prevRx && rx.t > prevRx.t) rxRate.value = Math.max(0, (rx.value - prevRx.value) / ((rx.t - prevRx.t) / 1000))
    prevRx = { value: rx.value, t: rx.t }
    ifaceName.value = rx.iface
  }
  if (tx) {
    if (prevTx && tx.t > prevTx.t) txRate.value = Math.max(0, (tx.value - prevTx.value) / ((tx.t - prevTx.t) / 1000))
    prevTx = { value: tx.value, t: tx.t }
  }
}, { deep: true })

function radial(v: number | null): number[] {
  return [v == null ? 0 : Math.round(v)]
}

// --- WebSocket -------------------------------------------------------------
let unbindWs: (() => void) | null = null
function startWs(id: string) {
  unbindWs = wsClient.on((msg: any) => {
    const channel: string | undefined = msg?.channel
    if (channel === `server_metrics:${id}`) metrics.applyLivePush(msg.rows ?? [])
  })
  wsClient.send({ action: 'subscribe', server_id: id })
}
function stopWs(id: string) {
  wsClient.send({ action: 'unsubscribe', server_id: id })
  unbindWs?.()
  unbindWs = null
}

async function load(id: string) {
  try {
    server.value = await getServer(id)
  } catch {
    void router.replace('/servers')
    return
  }
  await metrics.loadServer(id)
}

onMounted(async () => {
  const id = serverId.value
  await load(id)
  startWs(id)
})

onUnmounted(() => {
  if (serverId.value) stopWs(serverId.value)
  metrics.reset()
})

// Org switch while viewing → server may not belong to new org → back to list.
// Guard against the initial null→value population during org load: only redirect
// when the active org actually changes to a *different* org than this server's.
watch(() => orgStore.activeOrgId, (newId) => {
  if (server.value && newId && newId !== server.value.org_id) {
    void router.replace('/servers')
  }
})
</script>

<template>
  <div class="detail" v-if="server">
    <router-link to="/servers" class="back">← Back to Servers</router-link>

    <PageHeader :title="server.name" :subtitle="subtitle">
      <template #actions>
        <div class="hdr-status">
          <StatusBadge kind="server" :status="displayStatus" />
          <span class="seen">Last seen {{ relativeTime(server.last_seen_at) }}</span>
        </div>
        <div class="menu-wrap">
          <button class="kebab" @click="menuOpen = !menuOpen" aria-label="Server actions">⋮</button>
          <div v-if="menuOpen" class="menu" @click="menuOpen = false">
            <button v-if="auth.isAdmin" class="menu-item" @click="maintenanceOpen = true">
              {{ metrics.maintenance.active ? 'End Maintenance' : 'Toggle Maintenance' }}
            </button>
            <span v-else class="menu-item muted">Admin only</span>
          </div>
        </div>
      </template>
    </PageHeader>

    <div class="tags" v-if="server.tags.length">
      <span v-for="t in server.tags" :key="t" class="tag">{{ t }}</span>
    </div>

    <!-- Live gauges -->
    <div class="gauges">
      <div class="gauge">
        <span class="g-title">CPU</span>
        <MetricChart type="radialBar" :series="radial(cpu)" :labels="['CPU']" :height="170" />
        <div class="g-sub">
          <span>user {{ cpuUser?.toFixed(0) ?? '—' }}%</span>
          <span>sys {{ cpuSys?.toFixed(0) ?? '—' }}%</span>
          <span>iowait {{ cpuWait?.toFixed(0) ?? '—' }}%</span>
        </div>
      </div>

      <div class="gauge">
        <span class="g-title">RAM</span>
        <MetricChart type="radialBar" :series="radial(ram)" :labels="['RAM']" :height="170" />
        <div class="g-sub">
          <span>{{ humanBytes(ramUsed) }} / {{ humanBytes(ramTotal) }}</span>
        </div>
      </div>

      <div class="gauge">
        <span class="g-title">Disk</span>
        <MetricChart type="radialBar" :series="radial(diskMax)" :labels="['Disk']" :height="170" />
        <div class="g-sub g-sub-col">
          <span v-for="d in diskMounts" :key="d.labels.path" :style="{ color: usageColor(d.value) }">
            {{ d.labels.path }} — {{ d.value?.toFixed(0) ?? '—' }}%
          </span>
        </div>
      </div>

      <div class="gauge net">
        <span class="g-title">Network</span>
        <div class="net-rates">
          <div class="net-row down">↓ {{ humanRate(rxRate) }}</div>
          <div class="net-row up">↑ {{ humanRate(txRate) }}</div>
        </div>
        <div class="g-sub"><span>{{ ifaceName }}</span></div>
      </div>
    </div>

    <!-- Tabs -->
    <div class="tabbar">
      <div class="tabs">
        <button
          v-for="t in TABS" :key="t"
          class="tab" :class="{ active: activeTab === t }"
          @click="activeTab = t"
        >{{ t }}</button>
      </div>
      <div class="ranges">
        <button
          v-for="r in RANGES" :key="r"
          class="range" :class="{ active: currentRange === r }"
          @click="setRange(r)"
        >{{ r }}</button>
      </div>
    </div>

    <component :is="TAB_COMPONENTS[activeTab]" :range="currentRange" />

    <MaintenanceSlideOver v-model="maintenanceOpen" :server-name="server.name" />
  </div>
</template>

<style scoped>
.detail { padding: 24px 28px; max-width: 1300px; }
.back { display: inline-block; color: var(--muted); text-decoration: none; font-size: 13px; margin-bottom: 12px; }
.back:hover { color: var(--text); }
.hdr-status { display: flex; align-items: center; gap: 10px; }
.seen { color: var(--muted); font-size: 12px; }
.menu-wrap { position: relative; }
.kebab { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; width: 32px; height: 32px; color: var(--text); cursor: pointer; font-size: 16px; }
.menu { position: absolute; right: 0; top: calc(100% + 6px); background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 4px; min-width: 170px; z-index: 20; box-shadow: 0 12px 30px rgba(0,0,0,0.4); }
.menu-item { display: block; width: 100%; text-align: left; background: none; border: none; color: var(--text); font-size: 13px; padding: 8px 10px; border-radius: 6px; cursor: pointer; }
.menu-item:hover { background: rgba(99,102,241,0.12); color: var(--accent-2); }
.menu-item.muted { color: var(--muted); cursor: default; }
.tags { display: flex; gap: 6px; margin: 10px 0 18px; }
.tag { font-size: 11px; padding: 2px 8px; border-radius: 4px; background: var(--surface-2); color: var(--muted); border: 1px solid var(--border); }
.gauges { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 20px; }
.gauge { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px; display: flex; flex-direction: column; align-items: center; }
.g-title { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; align-self: flex-start; }
.g-sub { display: flex; gap: 10px; font-size: 11px; color: var(--muted); margin-top: 4px; flex-wrap: wrap; justify-content: center; }
.g-sub-col { flex-direction: column; align-items: center; gap: 2px; }
.net { justify-content: space-between; }
.net-rates { display: flex; flex-direction: column; gap: 8px; margin: 24px 0; }
.net-row { font-size: 20px; font-weight: 700; font-variant-numeric: tabular-nums; }
.net-row.down { color: var(--green, #22c55e); }
.net-row.up { color: var(--blue, #3b82f6); }
.tabbar { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); margin-bottom: 18px; }
.tabs { display: flex; gap: 2px; }
.tab { background: none; border: none; color: var(--muted); font-size: 13px; padding: 10px 14px; cursor: pointer; border-bottom: 2px solid transparent; }
.tab:hover { color: var(--text); }
.tab.active { color: var(--accent-2); border-bottom-color: var(--accent-2); }
.tab.disabled { color: var(--border); cursor: not-allowed; }
.ranges { display: flex; gap: 4px; }
.range { background: var(--surface-2); border: 1px solid var(--border); color: var(--muted); font-size: 12px; padding: 5px 10px; border-radius: 6px; cursor: pointer; }
.range.active { background: rgba(99,102,241,0.15); color: var(--accent-2); border-color: var(--accent); }
</style>
