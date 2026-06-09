<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useMetricsStore } from '@/stores/metrics'
import { useOrgStore } from '@/stores/org'
import { useNotify } from '@/composables/useNotify'
import {
  getAlertRules,
  createMetricRule, patchMetricRule, deleteMetricRule,
  createLogRule, patchLogRule, deleteLogRule,
} from '@/services/api'
import MetricRuleModal from '@/components/alerts/MetricRuleModal.vue'
import LogRuleModal from '@/components/alerts/LogRuleModal.vue'
import type { MetricRule, LogRule } from '@/types'

const metrics = useMetricsStore()
const orgStore = useOrgStore()
const notify = useNotify()

const props = withDefaults(defineProps<{ logsSupported?: boolean }>(), { logsSupported: true })

type SubTab = 'metric' | 'log'
const subTab = ref<SubTab>('metric')

const allMetric = ref<MetricRule[]>([])
const allLog = ref<LogRule[]>([])
const loading = ref(false)

const serverId = computed(() => metrics.activeServerId ?? '')
const metricRules = computed(() => allMetric.value.filter(r => r.server_id === serverId.value))
const logRules = computed(() => allLog.value.filter(r => r.server_id === serverId.value))

// single-entry array locks the modal's server dropdown to this server
const serverEntry = computed(() => {
  const name = metricRules.value[0]?.server_name ?? logRules.value[0]?.server_name ?? serverId.value
  return [{ id: serverId.value, name: name || serverId.value }]
})

async function load() {
  const orgId = orgStore.activeOrgId
  if (!orgId) return
  loading.value = true
  try {
    const data = await getAlertRules(orgId)
    allMetric.value = data.metric_rules
    allLog.value = data.log_rules
  } catch {
    notify.error('Could not load alert rules')
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => orgStore.activeOrgId, load)

// Modal state
const metricModalOpen = ref(false)
const logModalOpen = ref(false)
const editingMetric = ref<MetricRule | null>(null)
const editingLog = ref<LogRule | null>(null)
const metricModalRef = ref<InstanceType<typeof MetricRuleModal> | null>(null)
const logModalRef = ref<InstanceType<typeof LogRuleModal> | null>(null)

function openNewMetric() { editingMetric.value = null; metricModalOpen.value = true }
function openEditMetric(r: MetricRule) { editingMetric.value = r; metricModalOpen.value = true }
function openNewLog() { editingLog.value = null; logModalOpen.value = true }
function openEditLog(r: LogRule) { editingLog.value = r; logModalOpen.value = true }

async function submitMetric(payload: { id?: string; body: Record<string, unknown> }) {
  try {
    if (payload.id) await patchMetricRule(payload.id, payload.body)
    else await createMetricRule(payload.body)
    metricModalOpen.value = false
    notify.success('Metric rule saved')
    await load()
  } catch (err) {
    metricModalRef.value?.setError(err)
  }
}

async function submitLog(payload: { id?: string; body: Record<string, unknown> }) {
  try {
    if (payload.id) await patchLogRule(payload.id, payload.body)
    else await createLogRule(payload.body)
    logModalOpen.value = false
    notify.success('Log rule saved')
    await load()
  } catch (err) {
    logModalRef.value?.setError(err)
  }
}

async function toggleMetric(r: MetricRule) {
  try {
    await patchMetricRule(r.id, { enabled: !r.enabled })
    const idx = allMetric.value.findIndex(x => x.id === r.id)
    if (idx !== -1) allMetric.value[idx] = { ...allMetric.value[idx], enabled: !r.enabled }
  } catch {
    notify.error('Could not update rule')
  }
}

async function toggleLog(r: LogRule) {
  try {
    await patchLogRule(r.id, { enabled: !r.enabled })
    const idx = allLog.value.findIndex(x => x.id === r.id)
    if (idx !== -1) allLog.value[idx] = { ...allLog.value[idx], enabled: !r.enabled }
  } catch {
    notify.error('Could not update rule')
  }
}

async function removeMetric(r: MetricRule) {
  if (!confirm(`Delete the ${r.metric} alert rule?`)) return
  try {
    await deleteMetricRule(r.id)
    allMetric.value = allMetric.value.filter(x => x.id !== r.id)
    notify.success('Rule deleted')
  } catch {
    notify.error('Could not delete rule')
  }
}

async function removeLog(r: LogRule) {
  if (!confirm(`Delete the ${r.source} log rule?`)) return
  try {
    await deleteLogRule(r.id)
    allLog.value = allLog.value.filter(x => x.id !== r.id)
    notify.success('Rule deleted')
  } catch {
    notify.error('Could not delete rule')
  }
}

const METRIC_LABELS: Record<string, string> = {
  cpu: 'CPU usage %', ram: 'RAM usage %', disk: 'Disk usage %',
  disk_inode: 'Disk inodes %', db_connections: 'DB connections',
  db_replication_lag: 'DB replication lag',
}
function metricLabel(key: string) { return METRIC_LABELS[key] ?? key }
function fmtWindow(min: number) { return min >= 60 ? `${min / 60}h` : `${min}m` }
function fmtWindowSec(sec: number) { return sec >= 60 ? `${Math.round(sec / 60)}m` : `${sec}s` }
</script>

<template>
  <div v-if="serverId" class="alerts-tab">
    <div class="sub-tabbar">
      <div class="sub-tabs">
        <button class="sub-tab" :class="{ active: subTab === 'metric' }" @click="subTab = 'metric'">
          Metric Rules <span class="count">{{ metricRules.length }}</span>
        </button>
        <button class="sub-tab" :class="{ active: subTab === 'log' }" @click="subTab = 'log'">
          Log Pattern Rules <span class="count">{{ logRules.length }}</span>
        </button>
      </div>
      <button v-if="subTab === 'metric'" class="btn-add" @click="openNewMetric">+ New Metric Rule</button>
      <button v-else class="btn-add" @click="openNewLog">+ New Log Rule</button>
    </div>

    <div v-if="loading" class="loading-row">Loading…</div>

    <template v-else-if="subTab === 'metric'">
      <div v-if="metricRules.length === 0" class="empty">
        <p class="empty-msg">No metric rules for this server.</p>
        <button class="btn-add" @click="openNewMetric">Create one</button>
      </div>
      <table v-else class="rules-table">
        <thead>
          <tr>
            <th>Metric</th><th>Threshold</th><th>Window</th><th>Cooldown</th><th>Status</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in metricRules" :key="r.id">
            <td class="metric-name">{{ metricLabel(r.metric) }}</td>
            <td>{{ r.threshold }}%</td>
            <td>{{ fmtWindow(r.rolling_window_min) }}</td>
            <td>{{ fmtWindow(r.cooldown_min) }}</td>
            <td>
              <button class="toggle" :class="r.enabled ? 'on' : 'off'" @click="toggleMetric(r)">
                {{ r.enabled ? 'On' : 'Off' }}
              </button>
            </td>
            <td class="actions">
              <button class="act-btn" @click="openEditMetric(r)">Edit</button>
              <button class="act-btn danger" @click="removeMetric(r)">Delete</button>
            </td>
          </tr>
        </tbody>
      </table>
    </template>

    <template v-else>
      <div v-if="!props.logsSupported" class="unsupported-notice">
        Log collection is not available on this server (Debian 9 / stretch). Log pattern rules can be created but will never fire — upgrade to Debian 10+ to enable log monitoring.
      </div>
      <div v-if="logRules.length === 0" class="empty">
        <p class="empty-msg">No log rules for this server.</p>
        <button class="btn-add" @click="openNewLog">Create one</button>
      </div>
      <table v-else class="rules-table">
        <thead>
          <tr>
            <th>Source</th><th>Pattern</th><th>Severity</th><th>Threshold</th><th>Window</th><th>Status</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in logRules" :key="r.id">
            <td class="source-name">{{ r.source }}</td>
            <td class="pattern">{{ r.pattern }}</td>
            <td><span class="sev-badge" :class="r.severity">{{ r.severity }}</span></td>
            <td>{{ r.threshold }} hit{{ r.threshold !== 1 ? 's' : '' }}</td>
            <td>{{ fmtWindowSec(r.window_sec) }}</td>
            <td>
              <button class="toggle" :class="r.enabled ? 'on' : 'off'" @click="toggleLog(r)">
                {{ r.enabled ? 'On' : 'Off' }}
              </button>
            </td>
            <td class="actions">
              <button class="act-btn" @click="openEditLog(r)">Edit</button>
              <button class="act-btn danger" @click="removeLog(r)">Delete</button>
            </td>
          </tr>
        </tbody>
      </table>
    </template>

    <MetricRuleModal
      ref="metricModalRef"
      v-model="metricModalOpen"
      :rule="editingMetric"
      :servers="serverEntry"
      @submit="submitMetric"
    />
    <LogRuleModal
      ref="logModalRef"
      v-model="logModalOpen"
      :rule="editingLog"
      :servers="serverEntry"
      @submit="submitLog"
    />
  </div>
</template>

<style scoped>
.alerts-tab { padding: 4px 0 32px; }
.unsupported-notice { background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.35); border-radius: 6px; color: #f59e0b; font-size: 13px; padding: 10px 14px; margin-bottom: 14px; }

.sub-tabbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 10px;
}
.sub-tabs { display: flex; gap: 2px; }
.sub-tab {
  background: none; border: none; color: var(--muted);
  font-size: 13px; padding: 6px 12px; cursor: pointer;
  border-bottom: 2px solid transparent; margin-bottom: -11px;
}
.sub-tab:hover { color: var(--text); }
.sub-tab.active { color: var(--accent-2); border-bottom-color: var(--accent-2); }
.count {
  display: inline-block; background: var(--surface-2); color: var(--muted);
  font-size: 11px; padding: 1px 6px; border-radius: 10px; margin-left: 4px;
}

.btn-add {
  background: var(--accent); color: #fff; border: none;
  border-radius: 7px; padding: 6px 14px; font-size: 13px; cursor: pointer;
}
.btn-add:hover { opacity: 0.88; }

.loading-row { color: var(--muted); font-size: 13px; padding: 32px 0; text-align: center; }

.empty { text-align: center; padding: 40px 0; }
.empty-msg { color: var(--muted); font-size: 13px; margin-bottom: 12px; }

.rules-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.rules-table th {
  text-align: left; color: var(--muted); font-weight: 500;
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
  padding: 0 12px 8px; border-bottom: 1px solid var(--border);
}
.rules-table td { padding: 11px 12px; border-bottom: 1px solid var(--border); color: var(--text); }
.rules-table tr:last-child td { border-bottom: none; }

.metric-name, .source-name { font-weight: 500; }
.pattern { font-family: monospace; font-size: 12px; color: var(--muted); }

.sev-badge {
  font-size: 11px; padding: 2px 8px; border-radius: 4px;
  font-weight: 600; text-transform: uppercase;
}
.sev-badge.critical { background: rgba(239,68,68,0.15); color: #f87171; }
.sev-badge.warning  { background: rgba(245,158,11,0.15); color: #fbbf24; }

.toggle { border: none; border-radius: 5px; font-size: 11px; font-weight: 600; padding: 3px 10px; cursor: pointer; }
.toggle.on  { background: rgba(34,197,94,0.15); color: #4ade80; }
.toggle.off { background: var(--surface-2); color: var(--muted); }

.actions { display: flex; gap: 6px; }
.act-btn {
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: 5px; color: var(--text); font-size: 12px; padding: 3px 10px; cursor: pointer;
}
.act-btn:hover { background: rgba(99,102,241,0.12); color: var(--accent-2); }
.act-btn.danger:hover { background: rgba(239,68,68,0.12); color: #f87171; border-color: rgba(239,68,68,0.3); }
</style>
