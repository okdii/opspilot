<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useOrgStore } from '@/stores/org'
import { useNotify } from '@/composables/useNotify'
import {
  getAlertRules,
  createMetricRule,
  patchMetricRule,
  deleteMetricRule,
  createLogRule,
  patchLogRule,
  deleteLogRule,
} from '@/services/api'
import { PageHeader, EmptyState } from '@/components/ui'
import MetricRuleModal from '@/components/alerts/MetricRuleModal.vue'
import LogRuleModal from '@/components/alerts/LogRuleModal.vue'
import type { MetricRule, LogRule } from '@/types'

const orgStore = useOrgStore()
const notify = useNotify()

type Tab = 'metric' | 'log'
const tab = ref<Tab>('metric')

const metricRules = ref<MetricRule[]>([])
const logRules = ref<LogRule[]>([])
const loading = ref(false)

const metricModalOpen = ref(false)
const logModalOpen = ref(false)
const editingMetric = ref<MetricRule | null>(null)
const editingLog = ref<LogRule | null>(null)
const metricModalRef = ref<InstanceType<typeof MetricRuleModal> | null>(null)
const logModalRef = ref<InstanceType<typeof LogRuleModal> | null>(null)

const orgId = computed(() => orgStore.activeOrgId)

const servers = computed(() => {
  const m = new Map<string, string>()
  for (const r of metricRules.value) if (r.server_id) m.set(r.server_id, r.server_name || r.server_id)
  for (const r of logRules.value) if (r.server_id) m.set(r.server_id, r.server_name || r.server_id)
  return [...m.entries()].map(([id, name]) => ({ id, name }))
})

async function load(id: string) {
  loading.value = true
  try {
    const data = await getAlertRules(id)
    metricRules.value = data.metric_rules
    logRules.value = data.log_rules
  } catch {
    notify.error('Could not load alert rules')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (orgId.value) load(orgId.value)
})
watch(orgId, (id) => {
  if (id) load(id)
})

function openNewMetric() {
  editingMetric.value = null
  metricModalOpen.value = true
}
function openEditMetric(r: MetricRule) {
  editingMetric.value = r
  metricModalOpen.value = true
}
function openNewLog() {
  editingLog.value = null
  logModalOpen.value = true
}
function openEditLog(r: LogRule) {
  editingLog.value = r
  logModalOpen.value = true
}

async function submitMetric(payload: { id?: string; body: Record<string, unknown> }) {
  try {
    if (payload.id) await patchMetricRule(payload.id, payload.body)
    else await createMetricRule(payload.body)
    metricModalOpen.value = false
    notify.success('Metric rule saved')
    if (orgId.value) await load(orgId.value)
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
    if (orgId.value) await load(orgId.value)
  } catch (err) {
    logModalRef.value?.setError(err)
  }
}

async function toggleMetric(r: MetricRule) {
  try {
    await patchMetricRule(r.id, { enabled: !r.enabled })
    r.enabled = !r.enabled
  } catch {
    notify.error('Could not update rule')
  }
}
async function toggleLog(r: LogRule) {
  try {
    await patchLogRule(r.id, { enabled: !r.enabled })
    r.enabled = !r.enabled
  } catch {
    notify.error('Could not update rule')
  }
}

async function removeMetric(r: MetricRule) {
  if (!confirm(`Delete the ${r.metric} rule for ${r.server_name}?`)) return
  try {
    await deleteMetricRule(r.id)
    metricRules.value = metricRules.value.filter((x) => x.id !== r.id)
    notify.success('Rule deleted')
  } catch {
    notify.error('Could not delete rule')
  }
}
async function removeLog(r: LogRule) {
  if (!confirm(`Delete the ${r.source} log rule for ${r.server_name}?`)) return
  try {
    await deleteLogRule(r.id)
    logRules.value = logRules.value.filter((x) => x.id !== r.id)
    notify.success('Rule deleted')
  } catch {
    notify.error('Could not delete rule')
  }
}
</script>

<template>
  <div class="page">
    <PageHeader title="Alert Rules" subtitle="Metric thresholds and log pattern triggers">
      <template #actions>
        <router-link to="/alerts" class="back-link">← Back to Alerts</router-link>
        <button v-if="tab === 'metric'" class="btn primary" @click="openNewMetric">New Metric Rule</button>
        <button v-else class="btn primary" @click="openNewLog">New Log Rule</button>
      </template>
    </PageHeader>

    <div class="tabs" role="tablist">
      <button class="tab" :class="{ active: tab === 'metric' }" role="tab" @click="tab = 'metric'">
        Metric Rules <span class="tab-count">{{ metricRules.length }}</span>
      </button>
      <button class="tab" :class="{ active: tab === 'log' }" role="tab" @click="tab = 'log'">
        Log Pattern Rules <span class="tab-count">{{ logRules.length }}</span>
      </button>
    </div>

    <div v-if="loading" class="loading">Loading…</div>

    <!-- Metric rules -->
    <section v-else-if="tab === 'metric'" class="panel">
      <EmptyState
        v-if="!metricRules.length"
        title="No metric rules"
        message="Add a rule to alert on CPU, RAM, disk or other metric thresholds."
      />
      <table v-else class="rules-table">
        <thead>
          <tr>
            <th>Server</th><th>Metric</th><th>Threshold</th><th>Window</th><th>Cooldown</th><th>Status</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in metricRules" :key="r.id">
            <td>{{ r.server_name }}</td>
            <td>
              <span class="metric-name">{{ r.metric }}</span>
              <span v-if="r.is_auto" class="auto-chip">Auto</span>
            </td>
            <td class="num">{{ r.threshold }}</td>
            <td class="num">{{ r.rolling_window_min }}m</td>
            <td class="num">{{ r.cooldown_min }}m</td>
            <td>
              <button class="toggle" :class="{ on: r.enabled }" @click="toggleMetric(r)">
                <span class="toggle-knob"></span>
              </button>
            </td>
            <td class="actions">
              <button class="link-btn" @click="openEditMetric(r)">Edit</button>
              <button class="link-btn danger" @click="removeMetric(r)">Delete</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- Log rules -->
    <section v-else class="panel">
      <EmptyState
        v-if="!logRules.length"
        title="No log pattern rules"
        message="Add a rule to alert when log patterns appear above a threshold."
      />
      <table v-else class="rules-table">
        <thead>
          <tr>
            <th>Server</th><th>Source</th><th>Pattern</th><th>Sev</th><th>Threshold</th><th>Window</th><th>Status</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in logRules" :key="r.id">
            <td>{{ r.server_name }}</td>
            <td>{{ r.source }}</td>
            <td class="pattern"><code>{{ r.pattern }}</code></td>
            <td><span class="sev" :class="r.severity">{{ r.severity }}</span></td>
            <td class="num">{{ r.threshold }}</td>
            <td class="num">{{ r.window_sec }}s</td>
            <td>
              <button class="toggle" :class="{ on: r.enabled }" @click="toggleLog(r)">
                <span class="toggle-knob"></span>
              </button>
            </td>
            <td class="actions">
              <button class="link-btn" @click="openEditLog(r)">Edit</button>
              <button class="link-btn danger" @click="removeLog(r)">Delete</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <MetricRuleModal
      ref="metricModalRef"
      v-model="metricModalOpen"
      :rule="editingMetric"
      :servers="servers"
      @submit="submitMetric"
    />
    <LogRuleModal
      ref="logModalRef"
      v-model="logModalOpen"
      :rule="editingLog"
      :servers="servers"
      @submit="submitLog"
    />
  </div>
</template>

<style scoped>
.page { padding: 28px; }
@media (max-width: 1023px) { .page { padding: 20px; } }
@media (max-width: 767px)  { .page { padding: 14px; } }
.back-link { color: var(--muted); font-size: 13px; text-decoration: none; }
.back-link:hover { color: var(--text); }
.btn { padding: 8px 16px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; border: 1px solid var(--border); }
.btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn.primary:hover { opacity: 0.9; }

.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 16px; }
.tab {
  background: none; border: none; color: var(--muted); font-size: 13px; font-weight: 500;
  padding: 10px 14px; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px;
  display: inline-flex; align-items: center; gap: 7px;
}
.tab:hover { color: var(--text); }
.tab.active { color: #fff; border-bottom-color: var(--accent); }
.tab-count { background: rgba(99, 102, 241, 0.18); color: var(--accent-2); font-size: 11px; font-weight: 700; border-radius: 10px; padding: 1px 7px; }

.loading { padding: 40px; text-align: center; color: var(--muted); font-size: 13px; }
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 8px 14px; overflow-x: auto; }

.rules-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.rules-table th {
  text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
  color: var(--muted); font-weight: 600; padding: 12px 10px; border-bottom: 1px solid var(--border);
}
.rules-table td { padding: 12px 10px; border-bottom: 1px solid var(--border); color: var(--text); vertical-align: middle; }
.rules-table tr:last-child td { border-bottom: none; }
.num { font-variant-numeric: tabular-nums; }
.metric-name { font-weight: 500; }
.auto-chip {
  margin-left: 8px; font-size: 9px; text-transform: uppercase; letter-spacing: 0.05em;
  background: rgba(99, 102, 241, 0.18); color: var(--accent-2); padding: 2px 6px; border-radius: 4px;
}
.pattern code { font-size: 12px; color: #e2e8f0; background: var(--surface-2); padding: 2px 6px; border-radius: 4px; }
.sev { font-size: 10px; text-transform: uppercase; font-weight: 700; letter-spacing: 0.05em; padding: 2px 8px; border-radius: 4px; }
.sev.critical { background: rgba(239, 68, 68, 0.15); color: var(--red); }
.sev.warning { background: rgba(245, 158, 11, 0.15); color: var(--amber); }

.toggle {
  width: 36px; height: 20px; border-radius: 10px; background: var(--surface-2);
  border: 1px solid var(--border); cursor: pointer; position: relative; padding: 0; transition: background 0.15s;
}
.toggle.on { background: var(--accent); border-color: var(--accent); }
.toggle-knob {
  position: absolute; top: 2px; left: 2px; width: 14px; height: 14px; border-radius: 50%;
  background: #fff; transition: transform 0.15s;
}
.toggle.on .toggle-knob { transform: translateX(16px); }

.actions { display: flex; gap: 12px; white-space: nowrap; }
.link-btn { background: none; border: none; color: var(--accent-2); font-size: 12px; cursor: pointer; padding: 0; }
.link-btn:hover { color: #fff; }
.link-btn.danger { color: var(--muted); }
.link-btn.danger:hover { color: var(--red); }
</style>
