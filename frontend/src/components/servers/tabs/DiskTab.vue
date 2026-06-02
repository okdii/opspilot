<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import MetricChart from '@/components/charts/MetricChart.vue'
import { useMetricsStore } from '@/stores/metrics'
import { humanBytes, labeledList, realMounts, toApexSeries } from '@/utils/metrics'
import type { LatestLabeled, MetricRange } from '@/types'

const props = defineProps<{ range: MetricRange }>()
const metrics = useMetricsStore()

const KEY = {
  space: 'disk.history',
  io: 'disk.io',
}

async function loadAll(range: MetricRange) {
  await Promise.all([
    metrics.loadChartData(['disk.used_percent'], range, KEY.space),
    metrics.loadChartData(
      [
        'diskio.read_bytes',
        'diskio.write_bytes',
        'diskio.reads',
        'diskio.writes',
        'diskio.io_util',
        'diskio.io_await',
      ],
      range,
      KEY.io,
    ),
  ])
}

onMounted(() => loadAll(props.range))
watch(() => props.range, (r) => loadAll(r))

// ── 1. Disk Space — Current (donut) ─────────────────────────────────────────
const mounts = computed<LatestLabeled[]>(() =>
  realMounts(labeledList(metrics.latestValues, 'disk.used_percent')),
)

/** Latest used/total/free bytes for a given mount path, for the caption row. */
function bytesFor(path: string, metric: string): number | null {
  const hit = realMounts(labeledList(metrics.latestValues, metric)).find(
    (e) => e.labels.path === path,
  )
  return hit?.value ?? null
}

interface DonutMount {
  path: string
  pct: number
  used: number | null
  total: number | null
}

const donutMounts = computed<DonutMount[]>(() => {
  const list = mounts.value
    .map((m) => ({
      path: m.labels.path ?? m.labels.device ?? 'disk',
      pct: m.value ?? 0,
      used: bytesFor(m.labels.path ?? '', 'disk.used'),
      total: bytesFor(m.labels.path ?? '', 'disk.total'),
    }))
    .sort((a, b) => b.pct - a.pct)
  // Group all but the top 3 (by used %) into an "Other" slice.
  if (list.length <= 3) return list
  const top = list.slice(0, 3)
  const rest = list.slice(3)
  const otherPct = rest.reduce((sum, m) => sum + m.pct, 0)
  return [...top, { path: 'Other', pct: otherPct, used: null, total: null }]
})

const donutSeries = computed<number[]>(() => donutMounts.value.map((m) => m.pct))
const donutLabels = computed<string[]>(() => donutMounts.value.map((m) => m.path))

// ── 2. Disk Space History (one line per mount) ───────────────────────────────
const spaceSeries = computed(() =>
  toApexSeries(metrics.chartData[KEY.space]?.series ?? [], {
    name: (s) => s.labels.path ?? s.metric_name,
  }),
)

// ── I/O device selection ─────────────────────────────────────────────────────
const ioDevices = computed<string[]>(() => {
  const names = labeledList(metrics.latestValues, 'diskio.read_bytes')
    .map((e) => e.labels.name)
    .filter((n): n is string => !!n)
  return Array.from(new Set(names)).sort()
})

const selectedDevice = ref<string>('')
watch(
  ioDevices,
  (devs) => {
    if (devs.length && !devs.includes(selectedDevice.value)) selectedDevice.value = devs[0]
  },
  { immediate: true },
)

/** Build dual-series for an I/O metric pair, filtered to the selected device. */
function ioPair(readMetric: string, writeMetric: string, readName: string, writeName: string) {
  const series = metrics.chartData[KEY.io]?.series ?? []
  return toApexSeries(series, {
    filter: (s) => {
      if (s.metric_name !== readMetric && s.metric_name !== writeMetric) return false
      // When labels are present and a device is selected, filter to it.
      if (selectedDevice.value && s.labels.name) return s.labels.name === selectedDevice.value
      return true
    },
    name: (s) => (s.metric_name === readMetric ? readName : writeName),
  })
}

// ── 3. Disk I/O Throughput ───────────────────────────────────────────────────
const throughputSeries = computed(() =>
  ioPair('diskio.read_bytes', 'diskio.write_bytes', '↓ Read', '↑ Write'),
)

// ── 4. IOPS ──────────────────────────────────────────────────────────────────
const iopsSeries = computed(() => ioPair('diskio.reads', 'diskio.writes', 'Read', 'Write'))

// ── 5. I/O Utilisation % ─────────────────────────────────────────────────────
const ioUtilSeries = computed(() =>
  toApexSeries(metrics.chartData[KEY.io]?.series ?? [], {
    filter: (s) =>
      s.metric_name === 'diskio.io_util' &&
      (!selectedDevice.value || !s.labels.name || s.labels.name === selectedDevice.value),
    name: () => 'Utilisation',
  }),
)

// ── 6. I/O Latency ───────────────────────────────────────────────────────────
const ioAwaitSeries = computed(() =>
  toApexSeries(metrics.chartData[KEY.io]?.series ?? [], {
    filter: (s) =>
      s.metric_name === 'diskio.io_await' &&
      (!selectedDevice.value || !s.labels.name || s.labels.name === selectedDevice.value),
    name: () => 'Await',
  }),
)

// ── 7. Inode usage (only if any mount > 50%) ─────────────────────────────────
const showInodes = computed(() =>
  realMounts(labeledList(metrics.latestValues, 'disk.inodes_used_percent')).some(
    (e) => (e.value ?? 0) > 50,
  ),
)
const inodeSeries = computed(() => {
  if (!showInodes.value) return []
  return realMounts(labeledList(metrics.latestValues, 'disk.inodes_used_percent')).map((e) => ({
    name: e.labels.path ?? 'inodes',
    data: [[Date.now(), e.value] as [number, number | null]],
  }))
})

const deviceLabel = computed(() => (ioDevices.value.length ? selectedDevice.value : ''))
</script>

<template>
  <div class="disk">
    <!-- 1. Disk Space — Current -->
    <section class="card">
      <h3>Disk Space — Current</h3>
      <div v-if="donutMounts.length" class="space-current">
        <MetricChart
          type="donut"
          unit="%"
          :series="donutSeries"
          :labels="donutLabels"
          :height="260"
        />
        <ul class="mount-list">
          <li v-for="m in donutMounts" :key="m.path">
            <span class="mount-path">{{ m.path }}</span>
            <span class="mount-pct">{{ Math.round(m.pct) }}%</span>
            <span v-if="m.used != null && m.total != null" class="mount-bytes">
              {{ humanBytes(m.used) }} / {{ humanBytes(m.total) }}
            </span>
          </li>
        </ul>
      </div>
      <p v-else class="empty">No disk data.</p>
    </section>

    <!-- 2. Disk Space History -->
    <section class="card">
      <h3>Disk Space History</h3>
      <MetricChart type="area" unit="%" :series="spaceSeries" :height="240" />
    </section>

    <!-- 3. Disk I/O Throughput -->
    <section class="card">
      <div class="card-head">
        <h3>Disk I/O Throughput<span v-if="deviceLabel" class="dev"> ({{ deviceLabel }})</span></h3>
        <select v-if="ioDevices.length > 1" v-model="selectedDevice" class="dev-select">
          <option v-for="d in ioDevices" :key="d" :value="d">{{ d }}</option>
        </select>
      </div>
      <MetricChart type="line" unit="bytes/s" :series="throughputSeries" :height="240" />
    </section>

    <!-- 4. IOPS -->
    <section class="card">
      <h3>IOPS<span v-if="deviceLabel" class="dev"> ({{ deviceLabel }})</span></h3>
      <MetricChart type="line" unit="count" :series="iopsSeries" :height="240" />
    </section>

    <!-- 5. I/O Utilisation % -->
    <section class="card">
      <h3>I/O Utilisation %<span v-if="deviceLabel" class="dev"> ({{ deviceLabel }})</span></h3>
      <MetricChart type="area" unit="%" :series="ioUtilSeries" :height="240" />
    </section>

    <!-- 6. I/O Latency -->
    <section class="card">
      <h3>I/O Latency<span v-if="deviceLabel" class="dev"> ({{ deviceLabel }})</span></h3>
      <MetricChart type="line" unit="ms" :series="ioAwaitSeries" :height="240" />
    </section>

    <!-- 7. Inode usage (only if any mount > 50%) -->
    <section v-if="showInodes" class="card">
      <h3>Inode Usage</h3>
      <MetricChart type="bar" unit="%" :series="inodeSeries" :height="200" />
    </section>
  </div>
</template>

<style scoped>
.disk { display: flex; flex-direction: column; gap: 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }
.card h3 { font-size: 13px; color: var(--text); margin-bottom: 12px; font-weight: 600; }
.card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.card-head h3 { margin-bottom: 0; }
.dev { color: var(--muted); font-weight: 400; }
.dev-select {
  background: var(--surface2, #22263a);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 12px;
}
.space-current { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: center; }
.mount-list { list-style: none; display: flex; flex-direction: column; gap: 8px; }
.mount-list li { display: flex; align-items: baseline; gap: 10px; font-size: 13px; }
.mount-path { color: var(--text); font-weight: 600; min-width: 64px; }
.mount-pct { color: var(--text); }
.mount-bytes { color: var(--muted); font-size: 12px; }
.empty { color: var(--muted); font-size: 13px; }
@media (max-width: 720px) {
  .space-current { grid-template-columns: 1fr; }
}
</style>
