<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import MetricChart, { type MetricThreshold } from '@/components/charts/MetricChart.vue'
import { useMetricsStore } from '@/stores/metrics'
import { getServer } from '@/services/api'
import { formatUptime, humanBytes, scalarValue, toApexSeries } from '@/utils/metrics'
import type { MetricRange, Server } from '@/types'
import RangePicker from './RangePicker.vue'
import KernelEventsCard from './KernelEventsCard.vue'

const metrics = useMetricsStore()

const KEY = {
  load: 'sys.load',
  proc: 'sys.proc',
  zombie: 'sys.zombie',
}

const server = ref<Server | null>(null)

async function loadAll(range: MetricRange) {
  await Promise.all([
    metrics.loadChartData(['system.load1', 'system.load5', 'system.load15'], range, KEY.load),
    metrics.loadChartData(['processes.total'], range, KEY.proc),
    metrics.loadChartData(['processes.zombies'], range, KEY.zombie),
  ])
}

onMounted(async () => {
  loadAll(metrics.rangeFor('System'))
  const id = metrics.activeServerId
  if (id) {
    try {
      server.value = await getServer(id)
    } catch {
      /* static info card degrades to em-dashes */
    }
  }
})
watch(() => metrics.rangeFor('System'), (r) => loadAll(r))

const loadSeries = computed(() =>
  toApexSeries(metrics.chartData[KEY.load]?.series ?? [], {
    name: (s) => s.metric_name.replace('system.load', '') + 'm',
  }),
)
const procSeries = computed(() =>
  toApexSeries(metrics.chartData[KEY.proc]?.series ?? [], { name: () => 'Processes' }),
)
const zombieSeries = computed(() =>
  toApexSeries(metrics.chartData[KEY.zombie]?.series ?? [], { name: () => 'Zombies' }),
)

const nCpus = computed(() => scalarValue(metrics.latestValues, 'system.n_cpus'))

const loadThresholds = computed<MetricThreshold[]>(() =>
  nCpus.value != null ? [{ value: nCpus.value, color: '#f59e0b', label: 'vCPUs' }] : [],
)
const zombieThresholds: MetricThreshold[] = [{ value: 1, color: '#f59e0b' }]

const info = computed(() => ({
  os: server.value?.os_distro ?? '—',
  kernel: server.value?.kernel_version ?? '—',
  uptime: formatUptime(scalarValue(metrics.latestValues, 'system.uptime')),
  vcpus: nCpus.value != null ? String(nCpus.value) : '—',
  ram: humanBytes(scalarValue(metrics.latestValues, 'mem.total')),
}))
</script>

<template>
  <div class="sys">
    <RangePicker tab-key="System" />
    <section class="card">
      <h3>Load Average</h3>
      <MetricChart
        type="line"
        unit="count"
        :series="loadSeries"
        :thresholds="loadThresholds"
        :height="240"
      />
    </section>

    <section class="card">
      <h3>Process Count</h3>
      <MetricChart type="area" unit="count" :series="procSeries" :height="240" />
    </section>

    <section class="card">
      <h3>Zombie Processes</h3>
      <MetricChart
        type="bar"
        unit="count"
        :series="zombieSeries"
        :thresholds="zombieThresholds"
        :height="240"
      />
    </section>

    <section class="card">
      <h3>System Info</h3>
      <dl class="info">
        <dt>OS</dt>
        <dd>{{ info.os }}</dd>
        <dt>Kernel</dt>
        <dd>{{ info.kernel }}</dd>
        <dt>Uptime</dt>
        <dd>{{ info.uptime }}</dd>
        <dt>vCPUs</dt>
        <dd>{{ info.vcpus }}</dd>
        <dt>RAM</dt>
        <dd>{{ info.ram }}</dd>
      </dl>
    </section>

    <KernelEventsCard
      v-if="metrics.activeServerId"
      :server-id="metrics.activeServerId"
      :range="metrics.rangeFor('System')"
    />
  </div>
</template>

<style scoped>
.sys { display: flex; flex-direction: column; gap: 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }
.card h3 { font-size: 13px; color: var(--text); margin-bottom: 12px; font-weight: 600; }
.info {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 10px 24px;
  margin: 0;
  font-size: 13px;
}
.info dt { color: var(--muted); font-weight: 500; }
.info dd { color: var(--text); margin: 0; }
</style>
