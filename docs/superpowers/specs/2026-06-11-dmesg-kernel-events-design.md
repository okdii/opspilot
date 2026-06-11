# dmesg / Kernel Events — Design Spec
**Date:** 2026-06-11
**Status:** Approved

---

## Overview

Extract kernel messages from monitored servers and surface them in the System tab as a forensics trail. When something goes wrong — OOM kill, disk I/O error, hardware fault — operators can see what the kernel reported without SSH access.

---

## Placement

A new **Kernel Events card** is added as the 5th card at the bottom of the **System tab** (after System Info). No new tab. No new page.

---

## Data Collection

### Source 1 — Fluent Bit `kmsg` input (real-time)

Add one `[INPUT]` block to `fluent-bit.conf.j2`:

```
[INPUT]
    Name              kmsg
    Tag               kernel
    Prio_Level        warning
    DB                /var/lib/fluent-bit/kernel.db
```

- `Prio_Level warning` captures warn / err / crit / alert / emerg only — suppresses boot-time info/debug noise
- Fluent Bit already runs as root so `/dev/kmsg` is readable without extra permissions
- The existing Lua `set_source` filter stamps `source = 'kernel'` onto every record
- The backend already accepts `source = 'kernel'` in `ALLOWED_SOURCES` (`logs.py:28`) — **no backend schema changes required**
- Messages flow through the existing Fluent Bit → `/api/ingest/logs` → `server_logs` hypertable pipeline

### Source 2 — SSH dmesg poll (historical backfill)

New APScheduler job: `dmesg_collector`. Runs every **15 minutes** per active server.

Command executed via SSH:
```bash
dmesg -T -l warn,err,crit,alert,emerg
```

Parse output format: `[Day Mon DD HH:MM:SS YYYY] message text`

- Extract wall-clock timestamp, severity (from first word pattern matching), message body
- Insert into `server_logs` with `source='kernel'`, `server_id`, `severity`, `message`, `logged_at`
- Severity mapping from dmesg keyword detection:
  - `Out of memory`, `oom_kill` → `crit`
  - `I/O error`, `EXT4-fs error`, `EDAC`, `Machine check`, `Kernel panic` → `err`
  - `Link is Down`, `remount-ro`, `Critical temperature` → `warn`
  - Default: preserve dmesg level as severity string

**Deduplication:** Per poll cycle, for each parsed line check whether a row already exists in `server_logs` with `source='kernel'`, same `server_id`, `logged_at` within ±2 seconds, and identical `message`. Skip rows that match. No new columns required — the check is a lightweight `EXISTS` query against the TimescaleDB hypertable scoped to a narrow time window.

### Agent Reconfiguration

Existing servers have Fluent Bit installed without the `kmsg` block. Add a **"Reconfigure agents"** button to the server Info tab (admin only) that re-runs onboarding steps 6 + 7 (`configure_telegraf` + `configure_fluent_bit`) and restarts the services. This pushes the updated template to the server.

---

## API

### New endpoint

```
GET /api/servers/{server_id}/kernel-events?range={range}
```

**Authorization:** same as existing server endpoints (org membership check)

**Query params:**
- `range` — one of `1h | 6h | 24h | 7d | 30d` (default: `24h`). Backend converts to `now() - interval` using the same helper as the metrics router.

**Response:**
```json
{
  "counts": {
    "emerg": 0,
    "alert": 0,
    "crit": 1,
    "err": 3,
    "warn": 4
  },
  "events": [
    {
      "ts": "2026-06-11T03:14:22Z",
      "severity": "crit",
      "message": "Out of memory: Kill process 1234 (php-fpm) score 892 or sacrifice child"
    }
  ]
}
```

- Events ordered newest-first, capped at **50**
- Queries `server_logs WHERE source='kernel' AND server_id=? AND logged_at BETWEEN ? AND ?`
- Single call returns both counts and event list — no N+1 from the frontend

---

## Frontend

### New component: `KernelEventsCard.vue`

Location: `frontend/src/components/servers/tabs/KernelEventsCard.vue`

**Props:**
- `serverId: string`
- `range: MetricRange` (from RangePicker — `'1h' | '6h' | '24h' | '7d' | '30d'`)

**Behaviour:**
- Fetches on mount and whenever `range` changes
- Follows the System tab's existing `RangePicker` (tab-key `'System'`) — no independent range control
- Parent (`SystemTab.vue`) passes `metrics.rangeFor('System')` as the `range` prop

**Layout (top to bottom):**

1. **Header row** — "⚡ Kernel Events" title (left) + "View all in Logs →" link (right)
   - "View all" navigates via `router.push({ query: { tab: 'Logs', source: 'kernel' } })` — the existing `ServerDetail.vue` tab-from-query logic switches to the Logs tab; `LogsTab.vue` reads `route.query.source` on mount to pre-select the kernel source chip

2. **Summary strip** — 4 count tiles in a grid row:
   - emerg/alert (red) · crit (red) · err (orange) · warn (yellow)
   - Zero counts shown as `0` in muted tone — not hidden

3. **Section label** — "Recent events (last Xh)" where X matches the selected range

4. **Event list** — one row per event:
   - Severity badge (colored pill: crit=red, err=orange, warn=yellow)
   - Timestamp (HH:MM, local time)
   - Message text (truncated at 120 chars, full text on hover/title)

5. **Empty state** — "✓ No kernel warnings or errors in this period" (centered, muted)

6. **Loading state** — 3 skeleton rows

7. **Unsupported state** — shown when the server has never had any kernel events ingested AND Fluent Bit kmsg is not yet configured: "Kernel log collection not configured — reconfigure agents to enable"

**Severity color mapping:**
| Level | Badge bg | Text color |
|-------|----------|------------|
| emerg / alert | `#3d1f1f` | `#e74c3c` |
| crit | `#3d1f1f` | `#e74c3c` |
| err | `#3d2e1f` | `#f39c12` |
| warn | `#2a2920` | `#f1c40f` |

### SystemTab.vue changes

- Import `KernelEventsCard`
- Append `<KernelEventsCard :server-id="serverId" :from="rangeFrom" :to="rangeTo" />` as the last card
- Derive `rangeFrom` / `rangeTo` from the existing `metrics.rangeFor('System')` value (same pattern used by charts)

### LogsTab.vue

The `source=kernel` filter chip already works via the existing logs router — `'kernel'` is already in `ALLOWED_SOURCES`. Add handling in `LogsTab.vue` `onMounted` to read `route.query.source` and pre-select it if present.

---

## What Is Explicitly Out of Scope

- Automated alert rules on kernel events (users can create them manually via the existing alert rules UI — `source=kernel` already works)
- Kernel event categorisation / tagging (OOM vs disk vs network) — raw messages are sufficient
- `/var/log/kern.log` fallback — `kmsg` is available on all Linux kernels ≥ 3.5 (2012), covers all supported distros
- Kernel panic crash dumps or `kdump` integration
- Cross-reboot history (dmesg ring buffer only covers current boot; kmsg stream covers from when Fluent Bit started)
