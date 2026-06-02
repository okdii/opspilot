# Module Spec 04 — Dashboard

**Version:** 1.0  
**Date:** 2026-06-01  
**PRD Reference:** §5.4, §5.16.4, §5.16.5  
**Status:** Ready for Development

---

## 1. Overview

This spec covers two screens:

| Screen | Route | Description |
|---|---|---|
| Global Dashboard | `/` | Org-level overview — all servers, recent alerts, summary stats |
| Server Detail | `/servers/:id` | Deep-dive into one server — live gauges + historical charts |

Both screens receive real-time updates via the shared WebSocket connection. REST API is used for initial page load and historical chart data.

---

## 2. Global Dashboard (`/`)

The landing page after login. Shows a bird's-eye view of the active organization.

### 2.1 Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  Overview — Acme Corp                                               │
├───────────┬───────────┬───────────┬───────────────────────────────┤
│ SERVERS   │ SERVICES  │ ALERTS    │ SSL / DOMAINS                  │
│ 12 total  │ 48 up     │ 3 firing  │ 2 expiring soon               │
│ 11 ✓  1✗  │  2 down   │ 1 snoozed │ 0 expired                     │
└───────────┴───────────┴───────────┴───────────────────────────────┘

[Search servers...]          [Status ▾]  [Tags ▾]   [Grid | Table]

┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ ● web-01 [prod] │ │ ● db-01  [prod] │ │ ○ api-01 [prod] │
│ CPU  ████░ 72%  │ │ CPU  ██░░░ 38%  │ │                 │
│ RAM  █████ 84%  │ │ RAM  ████░ 61%  │ │    OFFLINE      │
│ Disk ████░ 67%  │ │ Disk ███░░ 52%  │ │   8 min ago     │
│ 3 svc  2 alerts │ │ 2 svc  0 alerts │ │ 1 alert [firing]│
└─────────────────┘ └─────────────────┘ └─────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Recent Alerts                                      [View All →] │
├─────────────────────────────────────────────────────────────────┤
│ 🔴 web-01  CPU usage > 85%          firing    2 min ago  [Ack] │
│ 🟡 web-03  SSL expiring in 14 days  firing    1 hr ago   [Ack] │
│ 🔴 api-01  Service down (HTTP)      snoozed   3 hr ago         │
│ ✅ db-01   RAM usage resolved                 5 hr ago         │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Summary Stat Cards (top row)

Four clickable cards. Clicking navigates to the relevant module page.

| Card | Primary number | Secondary info | Navigates to |
|---|---|---|---|
| Servers | Total servers in org | `N online · N offline · N maintenance` | `/servers` |
| Services | Total services up | `N down` (red if > 0) | `/services` |
| Alerts | Count in `firing` state | `N snoozed · N acknowledged` | `/alerts` |
| SSL / Domains | Count expiring within warn threshold | `N expired` (red if > 0) | `/ssl-domains` |

Cards update live via WebSocket — no page refresh needed.

**Alert card colour rules:**
- 0 firing → green
- 1–2 firing → amber
- 3+ firing → red (pulsing border)

### 2.3 Server Cards Grid

Same grid as described in spec 02, but with **live metric bars added**:

```
┌──────────────────────────────────┐
│  ● web-01                  [⋮]  │
│  192.168.1.10  [production]      │
│  ────────────────────────────    │
│  CPU   [████████░░░░░░░] 72%     │
│  RAM   [█████████░░░░░░] 84%  ⚠  │  ← amber warning icon (>80%)
│  Disk  [███████░░░░░░░░] 67%     │
│  ────────────────────────────    │
│  3 services · 2 alerts           │
│  Last seen: 18s ago              │
└──────────────────────────────────┘
```

**Progress bar colour rules:**
- 0–69% → green
- 70–84% → amber
- 85–100% → red

**Cards update live** — metric bars re-render each time a new `server_metrics` push arrives on the server's WebSocket channel.

**All Organizations view (Admin):** Org name badge appears on each card below the server name. Summary cards show aggregate totals across all orgs.

### 2.4 Recent Alerts Panel

Shows last 10 alerts across all servers in the active org, ordered by `sent_at DESC`.

| Column | Content |
|---|---|
| Severity dot | 🔴 critical · 🟡 warning |
| Server + description | `web-01 — CPU usage > 85%` |
| State badge | `firing` / `snoozed` / `acknowledged` / `✅ resolved` |
| Timestamp | Relative: `2 min ago` |
| Quick action | `[Ack]` button (visible for `firing` alerts only, Admin/Operator) |

`[View All →]` navigates to `/alerts`.

### 2.5 Empty State (No Servers)

When no servers exist in the active org:

```
│              🖥                                     │
│    No servers in Acme Corp                          │
│    Add your first server to start seeing data.      │
│    [ + Add Server ]                 ← Admin only    │
```

---

## 3. Server Detail Page (`/servers/:id`)

Deep-dive into a single server. Accessed by clicking any server card on the dashboard or server list.

### 3.1 Page Header

```
┌─────────────────────────────────────────────────────────────────────┐
│  ← Back to Servers                                                  │
│                                                                     │
│  ● web-01                                    [Re-deploy] [⋮]        │
│  192.168.1.10  ·  Ubuntu 22.04 LTS  ·  Linux 5.15.0               │
│  [production]  [web]                                                │
│  Online  ·  Last seen 12s ago  ·  Uptime: 47 days                  │
└─────────────────────────────────────────────────────────────────────┘
```

- `← Back to Servers` navigates back (preserves org filter)
- Status dot + badge live-updated via WebSocket
- Tags shown as chips
- `[Re-deploy]` — Admin only (triggers agent re-deploy, same as spec 03)
- `[⋮]` menu — Edit, Toggle Maintenance, View Onboarding Log, Delete (Admin only)
- Uptime shown as `X days X hours` formatted from `uptime_seconds` metric

#### Maintenance Mode Toggle

`[⋮] → Toggle Maintenance` opens a slide-over panel (480px):

```
┌────────────────────────────────────────────────────┐
│  Maintenance Mode — web-01                         │
│                                                    │
│  Enable maintenance mode to suppress all alerts    │
│  for this server. Metric and log collection        │
│  continues uninterrupted.                          │
│                                                    │
│  Reason (optional):                                │
│  [____________________________________]            │
│                                                    │
│  Auto-end maintenance after:                       │
│  ○ No end time (manual off)                        │
│  ● Duration: [2h ▼]  (30m / 1h / 2h / 4h / 8h)   │
│  ○ Specific time: [date] [time]                    │
│                                                    │
│           [Cancel]  [Enable Maintenance]           │
└────────────────────────────────────────────────────┘
```

When maintenance is **already active**, the panel shows the current status instead:

```
┌────────────────────────────────────────────────────┐
│  Maintenance Active — web-01                       │
│                                                    │
│  Reason:  OS kernel upgrade                        │
│  Started: 2026-06-01 14:00 UTC                     │
│  Ends:    2026-06-01 16:00 UTC (in 1h 14m)         │
│                                                    │
│           [Cancel]  [End Maintenance Now]          │
└────────────────────────────────────────────────────┘
```

While maintenance is active, the server header shows a blue **Maintenance** badge replacing the green status dot.

**API endpoints for maintenance mode:**

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/servers/:id/maintenance` | Admin | Enable maintenance (body: `{ reason, ends_at }`) |
| DELETE | `/api/servers/:id/maintenance` | Admin | End maintenance immediately |
| GET | `/api/servers/:id/maintenance` | Required | Current maintenance state |

`ends_at` is optional ISO timestamp. If omitted, maintenance runs indefinitely until manually ended. Backend APScheduler job (`maintenance_expiry`, 60s tick) auto-ends maintenance when `ends_at` passes.

When maintenance is enabled, the backend immediately moves all `firing`, `acknowledged`, and `snoozed` alerts for this server to `suppressed` state — no emails are sent for this state change. For the full maintenance alert lifecycle, see spec 10 §16.

### 3.2 Live Metrics Row

Four large gauge cards below the header, updated every 10 seconds via WebSocket:

```
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│     CPU      │ │     RAM      │ │     DISK     │ │   NETWORK    │
│              │ │              │ │              │ │              │
│    (gauge)   │ │    (gauge)   │ │    (gauge)   │ │  ↓ 2.3 MB/s │
│    72%       │ │    84%       │ │    67%       │ │  ↑ 0.8 MB/s │
│              │ │              │ │  /  — 67%   │ │              │
│ user  55%    │ │ 13.4 GB used │ │ /data — 45% │ │  eth0        │
│ sys    8%    │ │  1.2 GB swap │ │              │ │              │
│ iowait 9%   │ │              │ │              │ │              │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
```

- **CPU gauge**: radial gauge, 0–100%, colour thresholds (green/amber/red). Below the gauge: `user`, `sys`, `iowait` percentages in small text
- **RAM gauge**: radial gauge showing `ram_usage_pct`. Below: `X GB used of Y GB total`. Swap shown only if `swap_total_gb > 0`
- **Disk gauge**: shows the **highest** `disk_usage_pct` across all mount points. Below: one line per mount with label and percentage
- **Network gauge**: not a radial — shows ↓ inbound and ↑ outbound throughput per second (human-formatted: KB/s, MB/s, GB/s). Interface name below

### 3.3 Tab Navigation

Below the live metrics row:

```
[ Overview | CPU | Memory | Disk | Network | System | Processes ]
```

Time range selector (top-right of tab content, persisted per-tab in Pinia):
```
[ 1h ]  [ 6h ]  [ 24h ]  [ 7d ]  [ 30d ]
```

Data source by range:
| Range | Table used | Resolution |
|---|---|---|
| 1h | `server_metrics` (raw) | 10s (every row) |
| 6h | `server_metrics` (raw) | 10s |
| 24h | `server_metrics_hourly` | 1h averages |
| 7d | `server_metrics_daily` | 24h averages |
| 30d | `server_metrics_daily` | 24h averages |

All charts use **ApexCharts via `VaChart`**. Time on x-axis, formatted relative to selected range (HH:MM for 1h/6h, DD MMM for 7d/30d).

---

### 3.4 Overview Tab

Summary of the most important info across all metric categories on a single scrollable page.

```
┌──────────────────────────────────────────────────────────────────┐
│  CPU Usage (1h)                                       [ 1h ▾ ]  │
│  [area line chart — single line — 100% height, 300px]            │
├──────────────────────────────────────────────────────────────────┤
│  Memory Usage (1h)                                               │
│  [area line chart — used% line + available% line]                │
├──────────────────────────────────────────────────────────────────┤
│  Disk Space                                                      │
│  [horizontal progress bars — one per mount, with label]          │
├──────────────────────────────────────────────────────────────────┤
│  Network Throughput (1h)                                         │
│  [dual line chart — ↓ inbound green, ↑ outbound blue]            │
├──────────────────────────────────────────────────────────────────┤
│  Load Average (1h)                                               │
│  [3-line chart — 1m / 5m / 15m, dashed reference at core count] │
└──────────────────────────────────────────────────────────────────┘
```

The Overview tab has its own time range selector. Default: `1h`.

---

### 3.5 CPU Tab

```
┌──────────────────────────────────────────────────────────────────┐
│  CPU Usage History                                    [ 1h ▾ ]  │
│  [area line chart — cpu_usage_total — gradient fill]             │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  CPU Breakdown                                                   │
│  [stacked area chart — user / system / iowait / steal layers]    │
│  Tooltip: hover shows breakdown at that point in time            │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  Per-Core Usage (current)                                        │
│  [horizontal bar chart — one bar per core, live-updated]         │
│  Core 0  [████████░░] 78%                                        │
│  Core 1  [██████░░░░] 61%                                        │
│  Core 2  [███░░░░░░░] 32%                                        │
│  Core 3  [█████░░░░░] 54%                                        │
└──────────────────────────────────────────────────────────────────┘
```

**Threshold overlay:** A dashed red horizontal line at the alert threshold (from the server's `AlertRule` for `cpu_usage_total`). If no rule exists, no line shown.

---

### 3.6 Memory Tab

```
┌──────────────────────────────────────────────────────────────────┐
│  RAM Usage History                                    [ 1h ▾ ]  │
│  [area line chart — ram_usage_pct]                               │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  RAM Breakdown (current)                                         │
│  [stacked horizontal bar — used / cached / buffers / free]       │
│  13.4 GB used  /  2.1 GB cached  /  0.4 GB buffers  /  0.1 free │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  Swap Usage History                    [shown only if swap > 0]  │
│  [area line chart — swap_usage_pct]                              │
│  Note: High swap usage = RAM pressure, risk of slowdown          │
└──────────────────────────────────────────────────────────────────┘
```

If `swap_total_gb = 0`: swap section hidden entirely, replaced with note: *"No swap configured on this server."*

---

### 3.7 Disk Tab

```
┌──────────────────────────────────────────────────────────────────┐
│  Disk Space — Current                                            │
│  [donut chart per mount — each donut shows used/free]            │
│  /        67%  (45.2 GB / 67.4 GB)                              │
│  /data     45%  (90.3 GB / 200 GB)                              │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  Disk Space History                               [ 1h ▾ ]      │
│  [area line chart — one line per mount point]                    │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  Disk I/O Throughput (sda)                        [ 1h ▾ ]      │
│  [dual line chart — read bytes/s (green) + write bytes/s (blue)] │
│  Device selector dropdown if multiple block devices              │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  IOPS (sda)                                                      │
│  [dual line chart — read IOPS + write IOPS]                      │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  I/O Utilisation % (sda)                                         │
│  [area line chart — disk_io_util_pct — fills red above 80%]      │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  I/O Latency (sda)                                               │
│  [dual line chart — avg read latency ms + avg write latency ms]  │
└──────────────────────────────────────────────────────────────────┘
```

**Inode usage:** Shown as an extra row under Disk Space if any mount has `disk_inode_usage_pct > 50%`. Otherwise hidden (inodes rarely matter unless approaching 100%).

---

### 3.8 Network Tab

```
┌──────────────────────────────────────────────────────────────────┐
│  Interface: [ eth0 ▾ ]          (dropdown if multiple)          │
├──────────────────────────────────────────────────────────────────┤
│  Throughput                                       [ 1h ▾ ]      │
│  [dual line chart — ↓ inbound (green) + ↑ outbound (blue)]       │
│  Y-axis formatted in human units (KB/s, MB/s, GB/s)             │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  Packets/sec                                                     │
│  [dual line chart — inbound + outbound packets per second]       │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  Errors & Drops                                                  │
│  [grouped bar chart — errors_in / errors_out / drops_in /        │
│   drops_out — one group per time bucket]                         │
│  Note: All values displayed as rate (delta per interval)         │
└──────────────────────────────────────────────────────────────────┘
```

If only one network interface exists, the dropdown is hidden and the interface name shown as plain text.

---

### 3.9 System Tab

```
┌──────────────────────────────────────────────────────────────────┐
│  Load Average                                     [ 1h ▾ ]      │
│  [3-line chart — load_avg_1m / load_avg_5m / load_avg_15m]       │
│  Dashed reference line at number-of-vCPUs (e.g. at y=4 for 4c)  │
│  Tooltip: "Load > vCPU count = potential CPU saturation"         │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  Process Count                                                   │
│  [area line chart — process_total over time]                     │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  Zombie Processes                                                │
│  [bar chart — process_zombie — threshold line at 1]              │
│  Any non-zero value = orange bar                                 │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  System Info (static)                                            │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  OS:       Ubuntu 22.04 LTS                              │   │
│  │  Kernel:   5.15.0-91-generic                             │   │
│  │  Uptime:   47 days, 3 hours, 22 minutes                  │   │
│  │  vCPUs:    4                                             │   │
│  │  RAM:      16 GB                                         │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

vCPU count and total RAM are derived from the first `cpu_usage_per_core` row count and `ram_total_gb` respectively — they do not change so they are fetched once on page load.

---

### 3.10 Processes Tab

Live snapshot of top processes. No time range selector — always shows the **most recent** `top_processes` row.

```
┌──────────────────────────────────────────────────────────────────┐
│  Top Processes by CPU                  Updated 8s ago  [⟳ Live] │
├──────────────────────────────────────────────────────────────────┤
│  Process           PID      CPU %     MEM %                      │
│  nginx             1024     12.3%      2.1%                      │
│  php-fpm           2048      9.7%      4.5%                      │
│  mysqld            3012      8.2%     18.3%                      │
│  telegraf          4001      1.1%      0.8%                      │
│  ...                                                             │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  Top Processes by Memory                                         │
├──────────────────────────────────────────────────────────────────┤
│  Process           PID      MEM %     CPU %                      │
│  mysqld            3012     18.3%      8.2%                      │
│  php-fpm           2048      4.5%      9.7%                      │
│  ...                                                             │
└──────────────────────────────────────────────────────────────────┘
```

- "Updated Xs ago" counter ticks up every second; resets to `0s ago` when new data arrives
- `[⟳ Live]` badge pulses green when WebSocket is connected; turns grey with `[Paused]` label if WS disconnects
- Data sourced from latest `top_processes` row (`metric_name = 'top_processes'`) in `server_metrics` — reads `labels.top_cpu` and `labels.top_mem` JSON arrays
- Horizontal bar charts (from §5.16.5) are rendered below each table — bars proportional to CPU/MEM % value

---

### 3.11 Agent Status Section

Shown at the bottom of all tabs as a persistent footer strip:

```
┌──────────────────────────────────────────────────────────────────┐
│  Agents:  Telegraf ● running    Fluent Bit ● running    eth0 ↓↑ │
└──────────────────────────────────────────────────────────────────┘
```

- **Telegraf status**: derived from `systemd_units` metric — checks `telegraf.service` active state
- **Fluent Bit status**: same — `fluent-bit.service`
- If either is `stopped` / `failed` → badge turns red + warning toast: *"Telegraf is not running on web-01 — metrics may be stale"*
- Network interface throughput summary: interface name + live ↓↑ arrows with rate

---

## 4. WebSocket Data Flow

### 4.1 Global Dashboard Subscriptions

The global dashboard subscribes to **all servers in the active org** simultaneously. This is feasible for 10–50 servers.

Subscribe message sent on dashboard mount:
```json
{ "action": "subscribe_org", "org_id": "uuid" }
```

Backend subscribes to `server_metrics:{server_id}` for every server in the org and fans pushes out to the client.

On org switch: frontend sends:
```json
{ "action": "unsubscribe_org", "org_id": "old-uuid" }
{ "action": "subscribe_org",   "org_id": "new-uuid" }
```

### 4.2 Server Detail Subscriptions

On server detail mount:
```json
{ "action": "subscribe", "server_id": "uuid" }
```

On unmount:
```json
{ "action": "unsubscribe", "server_id": "uuid" }
```

### 4.3 WebSocket Push Payload

Each push from backend contains a **batch** of new metric rows for one server (batched for up to 500ms):

```json
{
  "channel": "server_metrics:550e8400-...",
  "rows": [
    { "metric_name": "cpu_usage_total",   "value": 72.3,  "labels": {},                     "time": "2026-06-01T12:00:00Z" },
    { "metric_name": "cpu_user",          "value": 55.1,  "labels": {},                     "time": "2026-06-01T12:00:00Z" },
    { "metric_name": "ram_usage_pct",     "value": 84.1,  "labels": {},                     "time": "2026-06-01T12:00:00Z" },
    { "metric_name": "disk_usage_pct",    "value": 67.2,  "labels": {"mount": "/"},         "time": "2026-06-01T12:00:00Z" },
    { "metric_name": "top_processes",     "value": null,  "labels": {"top_cpu": [...], ...}, "time": "2026-06-01T12:00:00Z" }
  ]
}
```

Frontend processes the batch:
1. Updates live gauge values for the server
2. Appends or updates the active chart's dataset (if on server detail):
   - **Raw ranges (1h, 6h):** Append new data points directly to the series array
   - **24h aggregate view:** Chart data is served as 1h averages from `server_metrics_hourly`. WS values are raw (10s resolution). Do NOT append raw points. Instead maintain a running sum + count for the current hour bucket, recompute the average, and replace (in place) the rightmost data point in the series. Do not re-fetch from the API.
   - **7d/30d views:** These show closed daily buckets — WS values do not update them. No chart change needed.
3. Trims raw-range chart datasets to the visible time window
4. Triggers chart re-render

### 4.4 Initial State on Page Load

WebSocket only delivers new data going forward. On page load, frontend fetches initial state via REST:

| Screen | REST call | What it populates |
|---|---|---|
| Global dashboard | `GET /api/organizations/:org_id/servers/summary` | Latest metric values for all server cards |
| Server detail | `GET /api/servers/:id/metrics?range=1h&metrics=cpu_usage_total,ram_usage_pct,...` | Initial chart dataset |

Then WebSocket takes over for live updates.

---

## 5. API Endpoints

### Global Dashboard

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/organizations/:org_id/dashboard` | Required | Summary stats + all server latest metrics |
| `GET` | `/api/organizations/:org_id/alerts/recent` | Required | Last 10 alerts for the org |

### GET /api/organizations/:org_id/dashboard

**Response (200):**
```json
{
  "summary": {
    "servers_total": 12,
    "servers_online": 11,
    "servers_offline": 1,
    "servers_maintenance": 0,
    "services_up": 48,
    "services_down": 2,
    "alerts_firing": 3,
    "alerts_snoozed": 1,
    "ssl_expiring": 2,
    "ssl_expired": 0
  },
  "servers": [
    {
      "id": "uuid",
      "name": "web-01",
      "status": "online",
      "last_seen_at": "2026-06-01T12:00:00Z",
      "active_alert_count": 2,
      "tags": ["production"],
      "latest_metrics": {
        "cpu_usage_total": 72.3,
        "ram_usage_pct": 84.1,
        "disk_usage_pct_max": 67.2
      }
    }
  ]
}
```

`disk_usage_pct_max` = highest `disk_usage_pct` across all mount points for that server — backend computes this.

---

### GET /api/organizations/:org_id/alerts/recent

Returns the last 10 alerts (any state except resolved) ordered by `sent_at DESC`. Includes full alert objects with IDs so the dashboard `[Ack]` button can call `POST /api/alerts/:id/acknowledge` directly.

**Response (200):**
```json
[
  {
    "id": "uuid",
    "type": "cpu",
    "severity": "critical",
    "message": "CPU rolling 5-min average reached 91.2% — threshold is 85%",
    "state": "firing",
    "server_id": "uuid",
    "server_name": "web-01",
    "service_id": null,
    "service_name": null,
    "domain_id": null,
    "domain_name": null,
    "sent_at": "2026-06-01T14:08:22Z",
    "acknowledged_at": null,
    "snoozed_until": null,
    "resolved_at": null
  }
]
```

Resolved alerts are excluded — the panel only shows actionable state. If all 10 most recent alerts are resolved, the panel shows the empty state.

---

### Server Detail

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/servers/:id/metrics` | Required | Historical metric data for charts |
| `GET` | `/api/servers/:id/metrics/latest` | Required | Latest value for each metric (live gauge initial state) |
| `GET` | `/api/servers/:id/processes` | Required | Most recent top_processes snapshot |

### GET /api/servers/:id/metrics

**Query parameters:**

| Param | Type | Required | Description |
|---|---|---|---|
| `range` | string | Yes | `1h`, `6h`, `24h`, `7d`, `30d` |
| `metrics` | string | Yes | Comma-separated metric names |
| `label_filter` | string | No | e.g. `mount=/` or `device=sda` — filter label values |

**Response (200):**
```json
{
  "range": "1h",
  "resolution": "10s",
  "series": [
    {
      "metric_name": "cpu_usage_total",
      "labels": {},
      "data": [
        { "time": "2026-06-01T11:00:00Z", "value": 68.1 },
        { "time": "2026-06-01T11:00:10Z", "value": 71.4 }
      ]
    },
    {
      "metric_name": "disk_usage_pct",
      "labels": { "mount": "/" },
      "data": [ ... ]
    }
  ]
}
```

### GET /api/servers/:id/metrics/latest

Returns the single most recent value for every metric name for this server. Used to populate live gauges on page load.

**Response (200):**
```json
{
  "cpu_usage_total":  { "value": 72.3, "time": "2026-06-01T12:00:00Z" },
  "cpu_user":         { "value": 55.1, "time": "2026-06-01T12:00:00Z" },
  "cpu_system":       { "value":  8.2, "time": "2026-06-01T12:00:00Z" },
  "cpu_iowait":       { "value":  9.0, "time": "2026-06-01T12:00:00Z" },
  "ram_usage_pct":    { "value": 84.1, "time": "2026-06-01T12:00:00Z" },
  "ram_total_gb":     { "value": 16.0, "time": "2026-06-01T12:00:00Z" },
  "disk_usage_pct":   [
    { "value": 67.2, "labels": { "mount": "/"     }, "time": "..." },
    { "value": 45.1, "labels": { "mount": "/data" }, "time": "..." }
  ]
}
```

Multi-label metrics (disk per mount, network per interface) return arrays.

### GET /api/servers/:id/processes

**Response (200):**
```json
{
  "collected_at": "2026-06-01T12:00:00Z",
  "top_cpu": [
    { "pid": 1024, "name": "nginx",  "cpu_pct": 12.3, "mem_pct": 2.1 }
  ],
  "top_mem": [
    { "pid": 3012, "name": "mysqld", "cpu_pct":  8.2, "mem_pct": 18.3 }
  ]
}
```

---

## 6. Pinia Stores

### `useDashboardStore`

| State | Type | Description |
|---|---|---|
| `summary` | `DashboardSummary \| null` | Org-level counts for stat cards |
| `serverSummaries` | `ServerSummary[]` | Latest metrics per server for cards |
| `recentAlerts` | `Alert[]` | Last 10 alerts |
| `loading` | `boolean` | Initial load state |

| Action | Description |
|---|---|
| `fetchDashboard(orgId)` | GET org dashboard endpoint, populates all state |
| `applyMetricPush(serverId, rows)` | Called by WS handler — updates `serverSummaries[serverId].latest_metrics` |

### `useMetricsStore`

| State | Type | Description |
|---|---|---|
| `activeServerId` | `string \| null` | Server currently being viewed |
| `selectedRange` | `'1h' \| '6h' \| '24h' \| '7d' \| '30d'` | Per-tab, persisted |
| `chartData` | `Record<string, Series[]>` | Keyed by metric name |
| `latestValues` | `Record<string, MetricValue>` | Latest value per metric — drives gauges |
| `processes` | `ProcessSnapshot \| null` | Most recent top_processes |

| Action | Description |
|---|---|
| `loadServer(serverId)` | Fetches latest values + default range chart data |
| `loadChartData(metrics, range)` | GET `/api/servers/:id/metrics` |
| `applyLivePush(rows)` | Called by WS handler — updates `latestValues`; for raw ranges (1h/6h) appends new points to `chartData`; for 24h view, updates the rightmost hourly bucket using a running average (no re-fetch) |
| `trimChartData()` | Called after each push — removes data points outside visible window |

---

## 7. Empty & Edge States Summary

| Scenario | Behaviour |
|---|---|
| Server is offline | Card shows red dot, OFFLINE badge, grayed-out metric bars. `Last seen: X min ago` |
| Server is `pending` (not onboarded) | Card shows no metric bars — replaced by onboarding progress indicator (spec 03) |
| No metrics received for a viewed server | Gauges show `—` dash; charts show "No data for this time range" empty state |
| WebSocket disconnects while on dashboard | All cards stop updating; `[Reconnecting...]` banner appears in top nav (spec 01 WS reconnect flow) |
| Admin selects 30d range but server added 3 days ago | Chart renders 3 days of data; x-axis starts at server's first metric, not 30 days ago |
| Disk has 5+ mount points | Donut chart groups all but top-3 into `Other` segment |
| Network has multiple interfaces | Interface dropdown in Network tab; global dashboard card shows the interface with highest throughput |
| `top_processes` row is older than 60s | "Updated Xs ago" counter turns amber; after 120s turns red with note: "Agent may be offline" |
| All servers online, 0 alerts | Alert stat card shows green `0 firing` |
| Org switched while on server detail | Redirect to `/servers` (the server may not belong to the new org) |
