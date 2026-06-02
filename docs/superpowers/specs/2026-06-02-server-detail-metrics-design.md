# Server Detail — Metrics Page (Phase 2 final block)

**Date:** 2026-06-02
**Status:** Approved — ready for planning
**Base spec:** `specs/04-dashboard.md` §3 (locked PRD v2.5)
**PRD refs:** §5.4, §5.16.4, §5.16.5

This design adapts the locked spec 04 §3 to the **actual ingested metric vocabulary**
(verified against the live lima-ubuntu DB on 2026-06-02) and defines a vertical-slice
build order. The base layout, tabs, and UX are unchanged from spec 04 §3 — read it
alongside this doc. This document records only the **adaptations and decisions** that
deviate from, or sharpen, the base spec.

---

## 1. Scope

In scope (this block = the 11 pending Phase 2 "Server Detail — Metrics" tasks, minus 2 deferred):

- Backend: `GET /api/servers/:id/metrics`, `GET /api/servers/:id/metrics/latest`,
  `GET/POST/DELETE /api/servers/:id/maintenance`
- Frontend page `views/servers/ServerDetail.vue`: header + maintenance slide-over,
  4 live gauges, tab nav, time-range selector, and tabs:
  **Overview, CPU, Memory, Disk, Network, System**
- `useMetricsStore` (Pinia) with live WS wiring
- A shared chart wrapper component (first chart use in the codebase)

**Deferred (out of scope — blocked on agent config):**

- **Processes tab (spec §3.10)** — requires a top-N per-PID list (`top_processes` /
  procstat). Telegraf currently runs only `[[inputs.processes]]` (aggregate state counts,
  no per-process list). `GET /api/servers/:id/processes` ships as a **501 stub** returning
  `{ "blocked": "agent-config" }`.
- **Agent Status footer (spec §3.11)** — requires `systemd_units` to read Telegraf/Fluent
  Bit service state. No systemd input enabled.

Both are logged as a **Phase 1 Telegraf-template follow-up**: add `[[inputs.procstat]]`
(top-N) + a systemd input to `backend/app/services/templates/telegraf.conf.j2`, then
agent re-deploy. Tracked in PROGRESS.md as blocked, not done.

---

## 2. Metric-name mapping (the core adaptation)

Spec 04 uses idealized names; Telegraf emits `measurement.field`. A single module
`backend/app/services/metric_catalog.py` owns the vocabulary — endpoints, rate logic,
and tests all import from it (single source of truth).

| Spec concept | Telegraf metric(s) | Label / notes |
|---|---|---|
| CPU total | `cpu.usage_active` | label `cpu = cpu-total` |
| CPU breakdown | `cpu.usage_user`, `cpu.usage_system`, `cpu.usage_iowait`, `cpu.usage_steal` | label `cpu = cpu-total` |
| CPU per-core | `cpu.usage_active` | one series per `cpu` label ≠ `cpu-total` (`cpu0`, `cpu1`, …) |
| RAM % | `mem.used_percent` | — |
| RAM breakdown | `mem.used`, `mem.cached`, `mem.buffered`, `mem.free`, `mem.available`, `mem.total` | bytes |
| Swap | `swap.used_percent`, `swap.used`, `swap.total` | section hidden if `swap.total = 0` |
| Disk usage | `disk.used_percent`, `disk.used`, `disk.free`, `disk.total` | label `path`; **filter** by `fstype` |
| Disk inodes | `disk.inodes_used_percent` | shown only if any mount > 50% |
| Disk I/O bytes | `diskio.read_bytes`, `diskio.write_bytes` | **counter → rate**; label `name` |
| Disk IOPS | `diskio.reads`, `diskio.writes` | **counter → rate** |
| Disk util / latency | `diskio.io_util`, `diskio.io_await` | gauge / ms |
| Net throughput | `net.bytes_recv`, `net.bytes_sent` | **counter → rate**; label `interface` |
| Net packets | `net.packets_recv`, `net.packets_sent` | **counter → rate** |
| Net errors/drops | `net.err_in/out`, `net.drop_in/out` | **counter → rate** |
| Load avg | `system.load1`, `system.load5`, `system.load15` | — |
| vCPU count | `system.n_cpus` | fetched once on load |
| Uptime | `system.uptime` | seconds → "X days X hours" |
| Process counts | `processes.total`, `processes.zombies` | aggregate counts |

### 2.1 Disk filesystem filter

Telegraf reports pseudo-filesystems (verified: `efivarfs` on `/sys/firmware/efi/efivars`,
plus `tmpfs`, `squashfs`, `overlay`, `devtmpfs`). The catalog defines a `REAL_FS_DENYLIST`
and disk queries exclude rows whose `fstype` is in it, so only real mounts surface.

### 2.2 Counter → rate computation

`diskio.*` and `net.*` are **cumulative monotonic counters**. Throughput/IOPS/packets/
errors must be presented as per-second rates. **Rate is computed server-side** in the
metrics endpoint: `rate[i] = (value[i] - value[i-1]) / (t[i] - t[i-1])`, clamped to ≥ 0
(drops a point if the counter reset / went backwards). The client always receives rates,
never raw counters. The catalog marks which metrics are counters (`is_counter: true`).

---

## 3. Backend endpoints

All reuse `_assert_org_access` and `_compute_status` from `routers/servers.py`. New router
section lives in `servers.py` (same file as the other `/api/servers/:id/*` routes) unless
it grows past ~150 lines, in which case extract `routers/metrics.py`.

### 3.1 `GET /api/servers/:id/metrics?range&metrics&label_filter`

- `range` → data source: `1h`/`6h` → `server_metrics` (raw); `24h` → `server_metrics_hourly`
  (`avg_value`, `bucket`); `7d`/`30d` → `server_metrics_daily` (`avg_value`, `bucket`).
- `metrics` → comma-separated **Telegraf** names (frontend uses catalog names).
- `label_filter` → optional `key=value` (e.g. `path=/`, `interface=eth0`, `name=vda`).
- Counter metrics → server returns rates (see §2.2).
- Multi-label metrics → one series per distinct label set.
- Response shape exactly per spec §5 (`{ range, resolution, series: [...] }`).
- Edge: server added < range window → x-axis starts at first datapoint (no padding).

### 3.2 `GET /api/servers/:id/metrics/latest`

- Latest value per metric (`DISTINCT ON (metric_name, labels)` ordered `time DESC`).
- Multi-label metrics (disk per path, net per iface) → arrays per spec §5.
- Drives the 4 gauges on page load.

### 3.3 `GET /api/servers/:id/processes` — **501 stub**

Returns `501` with `{ "blocked": "agent-config", "detail": "top_processes not collected" }`.
Frontend shows the deferred-tab placeholder. (Processes tab itself is not built this block.)

### 3.4 Maintenance — `GET/POST/DELETE /api/servers/:id/maintenance`

- `POST` body `{ reason?, ends_at? }` → sets maintenance, moves this server's
  `firing/acknowledged/snoozed` alerts → `suppressed` (no email sent for this transition).
- `DELETE` → end immediately.
- `GET` → current state.
- APScheduler job `maintenance_expiry` (60s tick) auto-ends when `ends_at` passes.
- Admin-only for POST/DELETE (`canEdit = isAdmin`).
- Defer alert-suppression specifics to spec 10 §16; here we set the state column +
  guard email send. (If the Alert/maintenance columns don't yet exist, the migration to
  add them is part of this block — verify against `models/` first.)

---

## 4. Frontend

### 4.1 Reuse first (CLAUDE.md Rule 3)

Existing primitives to reuse — **do not recreate**: `ui/StatCard`, `ui/SlideOver`
(maintenance panel), `ui/EmptyState` (no-data states), `ui/MetricBar` (disk horizontal
bars, per-core bars), `ui/StatusBadge` (status dot + maintenance badge), `ui/PageHeader`
(server header), `ui/DataGrid`. Reuse `servers/ServerCard` patterns for header styling.

### 4.2 New shared component — chart wrapper

No chart component exists yet (`components/charts/` is empty; no ApexCharts dep confirmed).
**First chart use → create a shared wrapper** `components/charts/MetricChart.vue` that wraps
the charting lib once (verify/install `apexcharts` + `vue3-apexcharts`, or Vuestic `VaChart`
if it bundles Apex). All tabs render through it via props (`type`, `series`, `range`,
`thresholds`, `unit`). Chart type/unit/color config comes from theme tokens, not per-page
(Rule 3 single source of truth). Supported types per spec: area, stacked area, line,
dual-line, multi-line, bar, grouped bar, radial gauge, donut, horizontal bar.

### 4.3 `useMetricsStore` (Pinia) — per spec §6

State: `activeServerId`, `selectedRange` (per-tab, persisted), `chartData` (keyed by metric),
`latestValues`, `maintenance`. Actions: `loadServer`, `loadChartData(metrics, range)`,
`applyLivePush(rows)`, `trimChartData()`.

**Live WS rules (spec §4.3):** raw ranges (1h/6h) → append points; **24h → recompute
rightmost hour bucket via running avg, replace in place, no re-fetch**; 7d/30d → no live
update. Trim raw datasets to the visible window after each push.

### 4.4 Page + routing

`views/servers/ServerDetail.vue` at route `/servers/:id`. Tab nav (Overview/CPU/Memory/Disk/
Network/System + a disabled "Processes" tab showing the deferred placeholder). On mount:
`subscribe { server_id }`; on unmount: `unsubscribe`. Org-switch while viewing → redirect to
`/servers` (spec §7). All UI built via the `ui-ux-pro-max` skill, dark-dashboard theme.

---

## 5. Build order (vertical-slice-first) & parallelism

**Slice A — Foundation (sequential, must land first):**
backend metrics + latest + maintenance endpoints + `metric_catalog.py` →
`MetricChart.vue` wrapper → `useMetricsStore` → `ServerDetail.vue` shell (header +
maintenance slide-over + 4 gauges + range selector + tab nav) + **Overview tab** + WS wiring.
Smoke-test live on lima-ubuntu, commit.

**Slices B–F — Tabs (independent, parallelizable after A):**
Each is one tab component reading the shared store/endpoints/chart wrapper — no shared
mutable state between them, so they can be built by parallel subagents once A exists:

- **B — CPU tab:** total area + breakdown stacked-area + per-core horizontal bars + threshold overlay
- **C — Memory tab:** RAM % area + breakdown stacked bar + swap area (hidden if no swap)
- **D — Disk tab:** per-mount donuts + usage history lines + I/O rate dual-lines + IOPS + util + latency
- **E — Network tab:** iface selector + throughput dual-line + packets + errors/drops grouped bar
- **F — System tab:** load avg 3-line (vCPU ref) + process count area + zombie bar + static system-info card

**Deferred:** Processes tab, Agent Status footer (Phase 1 Telegraf follow-up).

Each slice: smoke test (Rule 1) → update PROGRESS.md + DASHBOARD.html (Rule 0) →
commit + push (Rule 4).

---

## 6. Verification

- Backend: curl each endpoint against live lima-ubuntu data; confirm response shape matches
  spec §5, rates are non-negative, disk pseudo-FS excluded, 24h uses hourly avg.
- Frontend: load `/servers/:id` in browser; gauges populate; each tab's charts render with
  real data; spike CPU on the VM and confirm gauge + Overview chart update live via WS with
  no reload; 24h bucket updates in place.
- Maintenance: enable → header badge flips to Maintenance; verify alerts suppressed; end → reverts.
