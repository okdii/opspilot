# ECharts Response Time Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ApexCharts response time chart in `ServiceDetail.vue` with an ECharts `ResponseTimeChart.vue` component using a confidence band (avg→P95 shaded band) with client-side zoom aggregation and auto-scaling tick labels.

**Architecture:** New self-contained `ResponseTimeChart.vue` owns the chart, range buttons, zoom state, and client-side aggregation. Parent `ServiceDetail.vue` continues to own data fetching. Four ECharts line series use the stack trick to fill only the band between avg and P95. DataZoom tracks zoom position in refs so option recomputes don't reset the user's zoom window.

**Tech Stack:** `echarts ^5.x` (tree-shaken), `vue-echarts ^6.x`, Vue 3 `<script setup>`, TypeScript.

---

## File Map

| File | Change |
|------|--------|
| `frontend/package.json` | Add `echarts`, `vue-echarts` |
| `frontend/package-lock.json` | Updated by npm install |
| `frontend/src/components/services/ResponseTimeChart.vue` | **Create** — full chart component |
| `frontend/src/views/services/ServiceDetail.vue` | Remove ApexCharts resp-time block; wire in ResponseTimeChart |

`MetricChart.vue` and all other ApexCharts usage: **no changes.**

---

## Task 1: Install ECharts Dependencies

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install packages**

Run from inside the frontend container (or local node_modules):

```bash
cd /Users/pocketdata/Code/Work/opspilot/frontend
npm install echarts vue-echarts
```

Expected output: packages added, no peer dependency errors.

- [ ] **Step 2: Verify versions installed**

```bash
grep -E '"echarts"|"vue-echarts"' /Users/pocketdata/Code/Work/opspilot/frontend/package.json
```

Expected output (versions may differ):
```
"echarts": "^5.x.x",
"vue-echarts": "^6.x.x",
```

- [ ] **Step 3: Commit**

```bash
cd /Users/pocketdata/Code/Work/opspilot
git add frontend/package.json frontend/package-lock.json
git commit -m "chore(frontend): add echarts + vue-echarts dependencies"
```

---

## Task 2: Create ResponseTimeChart.vue

**Files:**
- Create: `frontend/src/components/services/ResponseTimeChart.vue`

- [ ] **Step 1: Create the component file**

Create `frontend/src/components/services/ResponseTimeChart.vue` with the full content below:

```vue
<script setup lang="ts">
import { use, graphic } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  MarkAreaComponent,
  LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import { ref, computed, watch } from 'vue'
import type { ResponseRange, ResponseTimeData } from '@/stores/services'

use([
  LineChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  MarkAreaComponent,
  LegendComponent,
  CanvasRenderer,
])

const props = defineProps<{
  data: ResponseTimeData | null
  range: ResponseRange
  downPeriods: Array<{ start: number; end: number }>
  loading?: boolean
}>()

const emit = defineEmits<{
  'range-change': [r: ResponseRange]
}>()

const RANGES: ResponseRange[] = ['1h', '6h', '24h', '7d', '30d']
const TWO_HOURS = 2 * 3600_000

// Internal tuple type: [timestamp_ms, avg_ms|null, p95_ms|null]
type Point = [number, number | null, number | null]

// Raw data mapped to Point tuples
const rawPoints = computed<Point[]>(() =>
  (props.data?.data ?? []).map((p): Point => [
    new Date(p.time).getTime(),
    p.avg_ms,
    p.p95_ms,
  ])
)

// Aggregated subset shown at current zoom level
const displayPoints = ref<Point[]>([])

// Tracked zoom window timestamps (null = use 2h-from-end defaults)
const zoomStart = ref<number | null>(null)
const zoomEnd = ref<number | null>(null)

// Effective zoom boundaries fed into the option
const effectiveZoomStart = computed(() => {
  if (zoomStart.value !== null) return zoomStart.value
  const pts = rawPoints.value
  const last = pts.length ? pts[pts.length - 1][0] : Date.now()
  return last - TWO_HOURS
})
const effectiveZoomEnd = computed(() => {
  if (zoomEnd.value !== null) return zoomEnd.value
  const pts = rawPoints.value
  return pts.length ? pts[pts.length - 1][0] : Date.now()
})

// Client-side time-bucket average
function aggregate(pts: Point[], bucketMs: number): Point[] {
  const buckets = new Map<number, { sumAvg: number; sumP95: number; count: number }>()
  for (const [t, avg, p95] of pts) {
    const key = Math.floor(t / bucketMs) * bucketMs
    if (!buckets.has(key)) buckets.set(key, { sumAvg: 0, sumP95: 0, count: 0 })
    const b = buckets.get(key)!
    if (avg != null) { b.sumAvg += avg; b.count++ }
    if (p95 != null) b.sumP95 += p95
  }
  return [...buckets.entries()]
    .sort(([a], [b]) => a - b)
    .map(([t, b]): Point => [
      t,
      b.count ? Math.round(b.sumAvg / b.count) : null,
      b.count ? Math.round(b.sumP95 / b.count) : null,
    ])
}

function applyAggregation(spanMs: number) {
  // 7d/30d data already hourly from backend — no client aggregation
  if (props.range === '7d' || props.range === '30d') {
    displayPoints.value = [...rawPoints.value]
    return
  }
  const bucketMs =
    spanMs > 6 * 3600_000 ? 30 * 60_000
    : spanMs > 1 * 3600_000 ? 5 * 60_000
    : 60_000
  displayPoints.value = aggregate(rawPoints.value, bucketMs)
}

// Reset zoom window when range prop changes (new fetch incoming)
watch(() => props.range, () => {
  zoomStart.value = null
  zoomEnd.value = null
})

// Rebuild display data whenever raw data changes
watch(rawPoints, (pts) => {
  if (!pts.length) { displayPoints.value = []; return }
  applyAggregation(TWO_HOURS)
}, { immediate: true })

// Chart instance ref — vue-echarts exposes setOption/getOption
const chartRef = ref()

// Handle zoom event: track position + re-aggregate
function onDataZoom() {
  try {
    const opt = chartRef.value?.getOption()
    const dz = opt?.dataZoom?.[0]
    if (!dz) return
    zoomStart.value = dz.startValue as number
    zoomEnd.value = dz.endValue as number
    const spanMs = (dz.endValue as number) - (dz.startValue as number)
    if (spanMs > 0) applyAggregation(spanMs)
  } catch { /* chart not ready */ }
}

function formatMs(v: number | null): string {
  if (v == null) return '—'
  if (v === 0) return '0 ms'
  if (v < 1) return `${v.toFixed(2)} ms`
  if (v < 10) return `${v.toFixed(1)} ms`
  return `${Math.round(v)} ms`
}

// Series data arrays — ECharts null sentinel is '-' for line gaps
const avgData = computed(() =>
  displayPoints.value.map(([t, avg]): [number, number | string] => [t, avg ?? '-'])
)
const spreadData = computed(() =>
  displayPoints.value.map(([t, avg, p95]): [number, number | string] => {
    if (avg == null || p95 == null) return [t, '-']
    return [t, Math.max(0, p95 - avg)]
  })
)
const p95Data = computed(() =>
  displayPoints.value.map(([t, , p95]): [number, number | string] => [t, p95 ?? '-'])
)

const hasData = computed(() => displayPoints.value.some(([, avg]) => avg != null))

const option = computed(() => ({
  backgroundColor: 'transparent',
  grid: { top: 16, right: 16, bottom: 32, left: 60, containLabel: false },
  xAxis: {
    type: 'time',
    axisLine: { lineStyle: { color: '#2e3354' } },
    axisTick: { lineStyle: { color: '#2e3354' } },
    axisLabel: {
      color: '#64748b',
      fontSize: 11,
      hideOverlap: true,
      // ECharts time formatter object — each key is the granularity shown
      formatter: {
        year: '{yyyy}',
        month: '{MMM} {d}',
        day: '{d} {MMM}',
        hour: '{HH}:{mm}',
        minute: '{HH}:{mm}',
      },
    },
    splitLine: { lineStyle: { color: '#2e3354', type: 'dashed' } },
  },
  yAxis: {
    type: 'value',
    min: 0,
    minInterval: 0.1,   // prevents sub-1ms values collapsing to "0.0 ms"
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: '#64748b',
      fontSize: 11,
      formatter: (v: number) => {
        if (v === 0) return '0'
        if (v < 1) return v.toFixed(2)
        if (v < 10) return v.toFixed(1)
        return String(Math.round(v))
      },
    },
    name: 'ms',
    nameLocation: 'end',
    nameTextStyle: { color: '#64748b', fontSize: 10 },
    splitLine: { lineStyle: { color: '#2e3354', type: 'dashed' } },
  },
  tooltip: {
    trigger: 'axis',
    backgroundColor: '#1e2235',
    borderColor: '#2e3354',
    borderWidth: 1,
    textStyle: { color: '#e2e8f0', fontSize: 12 },
    axisPointer: { type: 'cross', crossStyle: { color: '#475569', width: 1 } },
    // Filter out internal band series (_baseline, _spread) from tooltip display
    formatter: (params: any[]) => {
      const visible = (params as any[]).filter((p) => !p.seriesName.startsWith('_'))
      if (!visible.length) return ''
      const t = new Date(visible[0].value[0])
      const hh = String(t.getHours()).padStart(2, '0')
      const mm = String(t.getMinutes()).padStart(2, '0')
      const rows = visible.map((p: any) => {
        const raw = p.value[1]
        const val = raw === '-' ? null : (raw as number)
        return `<div style="margin-top:3px">${p.marker} ${p.seriesName}: <strong>${formatMs(val)}</strong></div>`
      })
      return `<div style="color:#94a3b8;font-size:11px;margin-bottom:2px">${hh}:${mm}</div>${rows.join('')}`
    },
  },
  // dataZoom uses tracked position so option recomputes don't reset user zoom
  dataZoom: [
    {
      type: 'inside',
      startValue: effectiveZoomStart.value,
      endValue: effectiveZoomEnd.value,
      minValueSpan: 15 * 60_000,   // closest zoom: 15 minutes
    },
  ],
  legend: {
    data: ['Avg', 'P95'],
    bottom: 0,
    textStyle: { color: '#94a3b8', fontSize: 12 },
    itemHeight: 8,
  },
  series: [
    // Series 1: invisible stack base at avg values (lower boundary of band)
    {
      name: '_baseline',
      type: 'line',
      data: avgData.value,
      stack: 'band',
      lineStyle: { opacity: 0 },
      areaStyle: { opacity: 0 },
      symbol: 'none',
      silent: true,
      legendHoverLink: false,
    },
    // Series 2: (p95 - avg) stacked on baseline — visible indigo band
    {
      name: '_spread',
      type: 'line',
      data: spreadData.value,
      stack: 'band',
      lineStyle: { opacity: 0 },
      areaStyle: {
        color: new graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(99,102,241,0.30)' },
          { offset: 1, color: 'rgba(99,102,241,0.06)' },
        ]),
      },
      symbol: 'none',
      silent: true,
      legendHoverLink: false,
    },
    // Series 3: avg solid green line (central metric)
    {
      name: 'Avg',
      type: 'line',
      data: avgData.value,
      smooth: true,
      lineStyle: { color: '#22c55e', width: 2 },
      itemStyle: { color: '#22c55e' },
      symbol: 'none',
      markArea: {
        silent: true,
        itemStyle: { color: 'rgba(239,68,68,0.10)' },
        label: { show: true, color: '#ef4444', fontSize: 10, formatter: () => 'Down' },
        data: props.downPeriods.map((p) => [{ xAxis: p.start }, { xAxis: p.end }]),
      },
    },
    // Series 4: P95 dashed indigo line (upper boundary reference)
    {
      name: 'P95',
      type: 'line',
      data: p95Data.value,
      smooth: true,
      lineStyle: { color: '#6366f1', width: 1, type: 'dashed' },
      itemStyle: { color: '#6366f1' },
      symbol: 'none',
    },
  ],
}))
</script>

<template>
  <div class="resp-chart">
    <div class="resp-chart__header">
      <div class="ranges">
        <button
          v-for="r in RANGES"
          :key="r"
          class="range"
          :class="{ active: range === r }"
          @click="emit('range-change', r)"
        >{{ r }}</button>
      </div>
    </div>
    <div v-if="loading" class="placeholder">Loading…</div>
    <VChart
      v-else-if="hasData"
      ref="chartRef"
      class="chart"
      :option="option"
      :autoresize="true"
      :update-options="{ notMerge: false }"
      @datazoom="onDataZoom"
    />
    <p v-else class="placeholder">No response time data for this period.</p>
  </div>
</template>

<style scoped>
.resp-chart { display: flex; flex-direction: column; gap: 8px; }
.resp-chart__header { display: flex; justify-content: flex-end; }
.ranges { display: flex; gap: 4px; }
.range {
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--muted);
  font-size: 12px;
  padding: 5px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.range:hover { border-color: var(--accent); color: var(--accent-2); }
.range.active { background: rgba(99,102,241,0.15); color: var(--accent-2); border-color: var(--accent); }
.chart { height: 280px; }
.placeholder { color: var(--muted); font-size: 13px; text-align: center; padding: 40px 0; margin: 0; }
</style>
```

- [ ] **Step 2: Verify the file was created**

```bash
ls -la /Users/pocketdata/Code/Work/opspilot/frontend/src/components/services/ResponseTimeChart.vue
```

Expected: file exists with non-zero size.

- [ ] **Step 3: Check TypeScript compiles without errors**

```bash
cd /Users/pocketdata/Code/Work/opspilot/frontend
npx vue-tsc --noEmit 2>&1 | head -30
```

Expected: no errors related to `ResponseTimeChart.vue`. If there are type errors, fix them before continuing.

- [ ] **Step 4: Commit**

```bash
cd /Users/pocketdata/Code/Work/opspilot
git add frontend/src/components/services/ResponseTimeChart.vue
git commit -m "feat(services): add ResponseTimeChart.vue using ECharts confidence band"
```

---

## Task 3: Wire ResponseTimeChart into ServiceDetail.vue

**Files:**
- Modify: `frontend/src/views/services/ServiceDetail.vue`

The current response time block spans two areas in the file:

**Script section — lines to remove:**
- Line 6: `import MetricChart from '@/components/charts/MetricChart.vue'`
- Lines 132–172: `const RANGES`, `RANGE_MS`, `withNullBreaks()`, `respSeries` computed
- Lines 173: `const hasRespData` computed
- Lines 175–183: `RANGE_TICKS`, `tickAmount` computed

**Script section — lines to keep:**
- `const range = ref<ResponseRange>('24h')` (line 134 area — controls fetch range)
- `const respData`, `respLoading` refs
- `loadResponse()` function
- `watch(range, (r) => loadResponse(r))` watcher
- `const downPeriods` computed (lines 185–192)

**Template section — replace lines 400–414** (the response time card).

- [ ] **Step 1: Add ResponseTimeChart import, remove MetricChart import**

In `frontend/src/views/services/ServiceDetail.vue`, replace line 6:

```typescript
// REMOVE this line:
import MetricChart from '@/components/charts/MetricChart.vue'

// ADD this line in its place:
import ResponseTimeChart from '@/components/services/ResponseTimeChart.vue'
```

`ResponseTimeData` stays in the type import on line 20 — `respData` is typed as `ref<ResponseTimeData | null>` and is still used in the parent.

- [ ] **Step 2: Remove the script blocks that move into the component**

Remove the following blocks from the `<script setup>` section (they are now internal to `ResponseTimeChart.vue`):

```typescript
// REMOVE: range buttons list (keep `range` ref itself — it drives the fetch)
const RANGES: ResponseRange[] = ['1h', '6h', '24h', '7d', '30d']

// REMOVE: RANGE_MS (was for scatter dots, no longer needed)
const RANGE_MS: Record<ResponseRange, number> = {
  '1h': 60 * 60 * 1000,
  '6h': 6 * 60 * 60 * 1000,
  '24h': 24 * 60 * 60 * 1000,
  '7d': 7 * 24 * 60 * 60 * 1000,
  '30d': 30 * 24 * 60 * 60 * 1000,
}

// REMOVE: null-break helper (ECharts uses '-' sentinel, handled in component)
function withNullBreaks(raw: [number, number | null][]): [number, number | null][] {
  const pts: [number, number | null][] = [...raw]
  for (const period of downPeriods.value) {
    pts.push([period.start, null])
    pts.push([period.end, null])
  }
  return pts.sort((a, b) => a[0] - b[0])
}

// REMOVE: respSeries computed
const respSeries = computed(() => { ... })

// REMOVE: hasRespData computed
const hasRespData = computed(() => (respData.value?.data ?? []).some((p) => p.avg_ms != null))

// REMOVE: tick amount config
const RANGE_TICKS: Record<ResponseRange, number> = { ... }
const tickAmount = computed(() => RANGE_TICKS[range.value])
```

**Keep the WS live-append block** (search for `// Live-append latest point`). It mutates `respData.value.data` directly, which Vue 3 tracks reactively. The new component's `rawPoints` computed reads `props.data?.data` and will pick up the push automatically — no changes needed there.

- [ ] **Step 3: Replace the response time card in the template**

Find this block in the template (around line 400–414):

```html
<!-- Response time -->
<section class="card">
  <div class="card-hd">
    <h3>Response Time</h3>
    <div class="ranges">
      <button
        v-for="r in RANGES" :key="r"
        class="range" :class="{ active: range === r }"
        @click="range = r"
      >{{ r }}</button>
    </div>
  </div>
  <MetricChart v-if="hasRespData" type="line" unit="ms" :series="respSeries" :height="260" :down-periods="downPeriods" :tick-amount="tickAmount" />
  <p v-else class="placeholder">No response time data for this period.</p>
</section>
```

Replace with:

```html
<!-- Response time -->
<section class="card">
  <h3>Response Time</h3>
  <ResponseTimeChart
    :data="respData"
    :range="range"
    :down-periods="downPeriods"
    :loading="respLoading"
    @range-change="(r) => (range = r)"
  />
</section>
```

Note: `watch(range, (r) => loadResponse(r))` already exists in the script — updating `range` via `@range-change` automatically triggers it. No additional handler needed.

- [ ] **Step 4: Remove now-unused CSS classes from ServiceDetail.vue styles**

At the bottom of `ServiceDetail.vue`, find and remove these CSS rules that were for the old range buttons inside the card (they now live in `ResponseTimeChart.vue`):

```css
.ranges { display: flex; gap: 4px; }
.range { background: var(--surface-2); border: 1px solid var(--border); color: var(--muted); font-size: 12px; padding: 5px 10px; border-radius: 6px; cursor: pointer; }
.range.active { background: rgba(99,102,241,0.15); color: var(--accent-2); border-color: var(--accent); }
```

- [ ] **Step 5: TypeScript check**

```bash
cd /Users/pocketdata/Code/Work/opspilot/frontend
npx vue-tsc --noEmit 2>&1 | head -30
```

Expected: zero errors. Fix any type errors before proceeding.

- [ ] **Step 6: Commit**

```bash
cd /Users/pocketdata/Code/Work/opspilot
git add frontend/src/views/services/ServiceDetail.vue
git commit -m "feat(services): wire ResponseTimeChart into ServiceDetail, remove ApexCharts resp-time block"
```

---

## Task 4: Smoke Test

**No file changes — browser verification only.**

- [ ] **Step 1: Start the dev stack**

```bash
cd /Users/pocketdata/Code/Work/opspilot
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

- [ ] **Step 2: Open a service detail page**

Navigate to `http://localhost:9090/services/<any-service-id>`. Use the URL from the conversation: `http://localhost:9090/services/4716c855-82a9-4959-99b6-2ab9011c5b61`.

- [ ] **Step 3: Verify confidence band renders**

Confirm:
- [ ] Shaded indigo band visible between avg and P95
- [ ] Solid green avg line visible through the band
- [ ] Dashed indigo P95 line at the top of the band
- [ ] Y-axis shows ms values (not collapsed to `0.0 ms`)
- [ ] X-axis shows timestamps with sensible intervals

- [ ] **Step 4: Verify default 2-hour window**

Confirm the chart opens showing approximately the last 2 hours of data, not the full 24h range.

- [ ] **Step 5: Test zoom**

Scroll on the chart to zoom in. Confirm:
- [ ] Zoom works (scroll/pinch)
- [ ] X-axis tick labels get denser as you zoom in
- [ ] At 15-min zoom, individual minute ticks are visible

- [ ] **Step 6: Test range buttons**

Click each range button (1h, 6h, 24h, 7d, 30d). Confirm:
- [ ] Active button highlights
- [ ] Chart updates with new data range
- [ ] Zoom resets to default window after range change

- [ ] **Step 7: Test tooltip**

Hover over the chart. Confirm:
- [ ] Crosshair tooltip appears
- [ ] Shows time (HH:mm)
- [ ] Shows Avg and P95 values in ms
- [ ] Does NOT show `_baseline` or `_spread` entries

- [ ] **Step 8: Verify down periods (if any outages exist)**

If the service has recorded incidents, confirm red shaded areas appear on the chart.

- [ ] **Step 9: Commit smoke test pass note and push**

```bash
cd /Users/pocketdata/Code/Work/opspilot
git push origin main
```
