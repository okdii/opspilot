# ECharts Response Time Chart — Design Spec
**Date:** 2026-06-05
**Status:** Approved

## Overview

Replace the ApexCharts response time chart in `ServiceDetail.vue` with an ECharts-based `ResponseTimeChart.vue` component. The new chart uses a confidence band visualization (avg→P95 shaded band + avg solid line), client-side zoom aggregation, and a `type:'time'` x-axis with auto-scaling tick labels.

No other charts in the app are affected. `MetricChart.vue` (ApexCharts) remains untouched.

---

## Component Interface

**File:** `frontend/src/components/services/ResponseTimeChart.vue`

```ts
// Props
data: ResponseTimeData        // { range, data: [{time, avg_ms, p95_ms}] }
range: ResponseRange          // '1h'|'6h'|'24h'|'7d'|'30d'
downPeriods: Array<{ start: number; end: number }>   // ms timestamps

// Emits
range-change: (r: ResponseRange) => void  // parent re-fetches on range button click
```

The component owns zoom state and client-side aggregation internally. The parent (`ServiceDetail.vue`) only manages data fetching.

---

## Chart Series — Confidence Band

Four ECharts series using the stack trick to fill only between avg and P95 (not from zero):

| # | Name | Type | Stack | Style | Purpose |
|---|------|------|-------|-------|---------|
| 1 | `_baseline` | line | `band` | areaStyle opacity:0, lineStyle opacity:0 | Invisible lower boundary at avg values |
| 2 | `_spread` | line | `band` | gradient indigo fill, lineStyle opacity:0 | Visible band from avg up to P95 |
| 3 | `Avg` | line | — | solid `#22c55e`, width:2, smooth:true | Central avg response time line |
| 4 | `P95` | line | — | dashed `#6366f1`, width:1, smooth:true | Upper P95 boundary reference line |

Series 1 and 2 data:
- Series 1 data: `[timestamp, avg_ms]`
- Series 2 data: `[timestamp, p95_ms - avg_ms]` (the delta, stacked on top of series 1)

Band fill gradient: `#6366f1` at 30% opacity top → 6% opacity bottom.

---

## X-Axis

```js
xAxis: {
  type: 'time',
  axisLabel: {
    hideOverlap: true,
    formatter: {
      year:   '{yyyy}',
      month:  '{MMM} {d}',
      day:    '{d} {MMM}',
      hour:   '{HH}:{mm}',
      minute: '{HH}:{mm}',
    }
  }
}
```

ECharts `type:'time'` auto-picks tick intervals based on visible span:

| Visible span | Auto tick interval |
|---|---|
| ~24h | every 2h |
| ~4h | every 30min |
| ~1h | every 5–10min |
| ~15min | every 1min |

`axisLabel.hideOverlap: true` prevents crowding. No static `minInterval` is set — the auto algorithm picks the densest non-overlapping interval for the visible window. Data points are always plotted every minute — only label density changes.

---

## Default View and Zoom

```js
dataZoom: [{
  type: 'inside',
  startValue: Date.now() - 2 * 3600 * 1000,  // default: last 2 hours
  endValue: Date.now(),
  minValueSpan: 15 * 60 * 1000,              // min zoom: 15 minutes
  // maxValueSpan: full loaded range (set dynamically)
}]
```

Scroll/pinch to zoom. No external zoom slider.

---

## Client-Side Aggregation

On `datazoom` event, compute visible span and downsample the raw data:

```
Visible span       Bucket size    Points shown (approx)
─────────────────────────────────────────────────────
> 6h               30 min         ≤ 48
1h – 6h            5 min          12 – 72
≤ 1h               1 min (raw)    ≤ 60
```

Aggregation function averages `avg_ms` and `p95_ms` within each bucket. Null values are skipped (don't distort the average).

**7d / 30d ranges:** Backend already returns hourly buckets — no client aggregation applied.

---

## Range Buttons

Five buttons: `1h | 6h | 24h | 7d | 30d`

- Rendered inside `ResponseTimeChart.vue` (self-contained)
- On click: emits `range-change(r)` → parent calls `loadResponse(r)` → passes new data back as prop
- On new data received: `dataZoom` resets to show full loaded range (not locked to last 2h)
- Default active range on mount: `24h`; dataZoom default window: last 2h within that 24h

---

## Y-Axis

```js
yAxis: {
  type: 'value',
  min: 0,
  minInterval: 0.1,
  axisLabel: {
    formatter: (v) => {
      if (v === 0) return '0'
      if (v < 1)  return v.toFixed(2) + ' ms'
      if (v < 10) return v.toFixed(1) + ' ms'
      return Math.round(v) + ' ms'
    }
  }
}
```

`minInterval: 0.1` prevents sub-1ms values from collapsing the y-axis to "0.0 ms".

---

## Tooltip

```js
tooltip: {
  trigger: 'axis',
  axisPointer: { type: 'cross', crossStyle: { color: '#475569' } },
  formatter: // custom: show timestamp + Avg Xms + P95 Xms
             // hide the _baseline and _spread series (internal band series)
}
```

Only `Avg` and `P95` values are shown in the tooltip. The two internal band series (`_baseline`, `_spread`) are excluded.

---

## Down Periods

Outage windows rendered as `markArea` on the first non-band series:

```js
markArea: {
  silent: true,
  itemStyle: { color: 'rgba(239,68,68,0.12)' },
  data: downPeriods.map(p => [
    { xAxis: p.start, label: { show: true, formatter: 'Down', color: '#ef4444' } },
    { xAxis: p.end }
  ])
}
```

---

## Null Break Handling

When a data point has `avg_ms: null` (check was down), insert `'-'` (ECharts null sentinel) rather than `0`. This creates a visual gap in the line instead of a drop to zero.

---

## Dependencies

```
echarts          ^5.x    (core library, tree-shaken)
vue-echarts      ^7.x    (Vue 3 wrapper)
```

Use tree-shaken imports to avoid bundling unused chart types:
```ts
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent, MarkAreaComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
```

---

## Files Changed

| File | Change |
|------|--------|
| `frontend/package.json` | Add `echarts`, `vue-echarts` |
| `frontend/src/components/services/ResponseTimeChart.vue` | **New** — full component |
| `frontend/src/views/services/ServiceDetail.vue` | Replace ApexCharts response time block with `<ResponseTimeChart>` |

`MetricChart.vue` and all other ApexCharts usage: **no changes.**

---

## Out of Scope

- Migrating other charts (CPU, memory, disk tabs) to ECharts
- Adding a dataZoom scrollbar/slider UI
- Backend changes (same API endpoints, same data format)
