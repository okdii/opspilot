# Process Monitoring + Agent Status (Phase 2 follow-on / unblocks deferred §3.10–§3.11)

**Date:** 2026-06-02
**Status:** Approved — ready for planning
**Base spec:** `specs/04-dashboard.md` §3.10 (Processes tab), §3.11 (Agent Status footer)
**Builds on:** `docs/superpowers/specs/2026-06-02-server-detail-metrics-design.md` (deferred these two items)

Unblocks the two items deferred from the Server Detail build by adding the agent
data they need, plus a per-core CPU fix and a DB-growth-control pass.

---

## 1. Scope (locked)

In scope:
1. **Live full process snapshot** — on-demand SSH, ALL processes, no storage.
2. **Top-N process history** — Telegraf `exec`, bounded, stored as `proctop.*`.
3. **Processes tab** (spec §3.10) — full process table + top-CPU/top-mem tables + "updated Xs ago / ● Live" badge + a top-consumers trend chart.
4. **Agent Status footer** (spec §3.11) — telegraf/fluent-bit health strip + warning toast when an agent is down, via `systemd_units`.
5. **Per-core CPU** — fixes the CpuTab "Per-Core Usage" empty state.
6. **DB-growth control** — collection-interval/field limits + a TimescaleDB compression policy.

Out of scope: process kill/signal actions; per-process drill-down history beyond the top-N trend.

---

## 2. Two complementary data sources

The snapshot and the history answer different questions and never collide
(one is pull/no-storage, the other push/stored).

### 2.1 Live full snapshot — on-demand SSH (no storage)
`GET /api/servers/:id/processes` opens `SSHSession(server)` (decrypts creds on
demand — `backend/app/services/ssh.py`) and runs **one** `top -bn1` command,
returning the **entire** current process list plus pre-sorted top tables.

- **`top -bn1`, not `ps`** — `ps %cpu` is a lifetime average; `top -bn1` gives
  instantaneous CPU. Both captures use `top -bn1` for correct "right now" values.
- Command (root not required; run as the onboarding ssh_user):
  `top -bn1 -o %CPU | awk '...'` → parse PID, USER, %CPU, %MEM, COMMAND.
- **5-second server-side cache** per server (`{server_id: (ts, payload)}`) so
  rapid polls / multiple viewers reuse one result.
- **Single-flight** per server: one in-flight SSH run at a time; concurrent
  callers await the same future (avoids SSH stampede).
- **Graceful failure:** SSH/connection error → `200` with
  `{ "reachable": false, "collected_at": null, "processes": [], "top_cpu": [], "top_mem": [] }`
  so the tab shows "agent unreachable" instead of a 500.

**Response (200):**
```json
{
  "reachable": true,
  "collected_at": "2026-06-02T10:00:00Z",
  "processes": [ { "pid": 1024, "name": "nginx", "user": "www-data", "cpu_pct": 12.3, "mem_pct": 2.1 } ],
  "top_cpu": [ ...top 10 by cpu_pct... ],
  "top_mem": [ ...top 10 by mem_pct... ]
}
```
`processes` is the full list (sorted by cpu desc); `top_cpu`/`top_mem` are the
first 10 of each sort, computed server-side.

### 2.2 Top-N history — Telegraf `exec` (stored)
A new `[[inputs.exec]]` block in `telegraf.conf.j2` runs every **30s** (not 10s):
an inline `top -bn1` + `awk` one-liner emitting influx line protocol for the
top ~10 by CPU and top ~10 by mem:
```
proctop,by=cpu,pid=1024,name=nginx cpu_pct=12.3,mem_pct=2.1
proctop,by=mem,pid=3012,name=mysqld cpu_pct=8.2,mem_pct=18.3
```
- `data_format = "influx"`, `interval = "30s"`, `timeout = "5s"`.
- **Name sanitization in awk:** strip/replace spaces, commas, `=` in COMMAND so
  line protocol stays valid (tags can't contain unescaped separators).
- Fits the existing numeric-only ingestion exactly (fields cpu_pct/mem_pct;
  tags by/pid/name → JSONB labels). No ingestion code change.
- Served by the **existing** `GET /metrics?metrics=proctop.cpu_pct` — no new
  history endpoint. The tab's trend chart reads it via the metrics store.

---

## 3. Agent Status (spec §3.11)

Add a **scoped** `[[inputs.systemd_units]]` to `telegraf.conf.j2`:
```toml
[[inputs.systemd_units]]
  pattern = "telegraf.service fluent-bit.service"
  # scoped to 2 units → ~6 rows/flush, NOT the hundreds an unscoped collector emits
```
This emits `systemd_units.active_code` (and load/sub codes) tagged by `name`
(`active_code = 0` means active/running). The footer reads the latest values
from `GET /metrics/latest` (already returns labeled arrays), so **no new
backend endpoint** — `systemd_units.active_code` simply appears in `latestValues`.

Footer behavior (persistent strip on all Server Detail tabs):
- Telegraf ● running (green) when its `active_code = 0`, else red.
- Fluent Bit ● running likewise.
- If either is not active → red badge + a one-time warning toast:
  *"Telegraf is not running on <server> — metrics may be stale."*
- Interface throughput summary (↓↑ rates) reuses the existing network gauge logic.

---

## 4. Per-core CPU (growth-controlled)

Today `[[inputs.cpu]]` has `percpu = false` → no per-core data (CpuTab shows an
empty state). Fix with a **second** cpu input limited to one field, so per-core
storage stays tiny:
```toml
[[inputs.cpu]]                      # existing — total, all fields
  percpu = false
  totalcpu = true
  report_active = true

[[inputs.cpu]]                      # NEW — per-core, single field only
  percpu = true
  totalcpu = false
  report_active = true
  fieldpass = ["usage_active"]
  [inputs.cpu.tags]
    scope = "percore"               # disambiguate from the total input's series
```
CpuTab's per-core bars only need `usage_active`, so 1 field × cores (e.g. 4 rows/
flush on a 4-core box) instead of ~10 × cores. Frontend reads per-core series as
`cpu.usage_active` rows where `labels.cpu != 'cpu-total'` (already implemented).

---

## 5. DB-growth control + compression

Per-server additions at the controlled cadence (baseline ≈ 200 rows/10s-flush):

| Source | Cadence | Rows/flush | ~Rows/day |
|---|---|---|---|
| `proctop` (top-N) | 30s | ~40 | ~115k |
| per-core (`usage_active`) | 10s | ~cores (4) | ~35k |
| `systemd_units` (scoped) | 10s | ~6 | ~52k |
| **Total added** | | | **~200k/day/server** (~+12% over baseline) |

The live SSH snapshot adds **zero** storage.

**Compression policy (new migration `0005_server_metrics_compression`):**
```sql
ALTER TABLE server_metrics SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'server_id, metric_name',
  timescaledb.compress_orderby   = 'time DESC'
);
SELECT add_compression_policy('server_metrics', INTERVAL '2 days');
```
Compresses chunks older than 2 days (recent data stays uncompressed for live
queries). Typically 10–20× reduction on the whole table. Downgrade drops the
policy and disables compression. Verify it does not conflict with the existing
retention policy + continuous aggregates (compression + retention coexist in
TimescaleDB; aggregates read fine from compressed chunks).

---

## 6. Frontend

### 6.1 Processes tab (`ProcessesTab.vue`) — spec §3.10
Replaces the disabled placeholder; `ServerDetail.vue` enables the Processes tab.
- Polls `GET /processes` every **5s** while mounted (own timer; clears on unmount).
- "Updated Xs ago" counter ticks each second, resets on new data; amber >60s,
  red >120s. `● Live` badge green when last poll succeeded; grey `Paused` if
  `reachable=false` or a poll failed.
- **Top Processes by CPU** table (top_cpu) + horizontal `MetricBar` per row.
- **Top Processes by Memory** table (top_mem) + bars.
- **Full process list** table below (all `processes`), client-side
  sort/filter by name/cpu/mem (reuse `ui/DataGrid` if it fits, else a simple table).
- **Top CPU consumers (trend)** — a `MetricChart` stacked-area from
  `loadChartData(['proctop.cpu_pct'], range, 'proc.trend')` grouped by name.
- "agent unreachable" empty state when `reachable=false`.

### 6.2 Agent Status footer (`AgentStatusFooter.vue`) — spec §3.11
Persistent strip rendered by `ServerDetail.vue` below the tab content; reads
`systemd_units.active_code` + network rates from the metrics store; emits the
warning toast on a stopped/failed agent (use Vuestic toast / existing notify).

Both built via the `ui-ux-pro-max` skill, dark-dashboard theme; reuse existing
`ui/*`, `MetricChart`, `MetricBar`, `StatusBadge`.

---

## 7. Deployment

1. Update `telegraf.conf.j2` (exec, second cpu input, systemd_units).
2. Run the compression migration: `alembic upgrade head`.
3. Push config to the live agent: `POST /api/servers/:id/redeploy`
   (`run_onboarding(server_id, redeploy_only=True)` re-renders + restarts telegraf).
4. Confirm `proctop.*`, per-core `cpu.usage_active`, and `systemd_units.*` rows
   appear in `server_metrics` within ~30s.

Restarting telegraf on lima-ubuntu briefly pauses metric collection (~seconds) —
acceptable on a dev VM; note it before redeploying.

---

## 8. Verification (smoke)

- **Backend:** `redeploy` lima-ubuntu; psql-confirm `proctop.*` (≤~40 rows/30s),
  per-core `cpu.usage_active` (one per core, label scope=percore), and
  `systemd_units.active_code` for the 2 services appear. `GET /processes` returns
  a full list + top tables with non-zero cpu; kill SSH (stop sshd or wrong creds
  path) → `reachable:false` handled. Compression: after running migration, verify
  `SELECT * FROM timescaledb_information.compression_settings` shows the policy.
- **Frontend (Playwright, lima-ubuntu):** Processes tab enabled; top tables +
  full list render; "updated Xs ago" ticks and resets; trend chart renders;
  per-core bars in CpuTab now populate. Agent footer shows Telegraf/Fluent Bit
  green; stop fluent-bit on the VM → footer badge turns red + toast appears.
- **Growth sanity:** confirm added rows/day ≈ estimate (spot-count `proctop` rows
  over a few minutes).

---

## 9. File map

**Backend:** `routers/metrics.py` (replace `/processes` 501 with on-demand SSH +
cache + single-flight), maybe a small `services/process_snapshot.py` (top -bn1
parse + cache); `migrations/versions/0005_server_metrics_compression.py`;
`services/templates/telegraf.conf.j2` (exec + 2nd cpu input + systemd_units).
**Frontend:** `components/servers/tabs/ProcessesTab.vue` (new),
`components/servers/AgentStatusFooter.vue` (new), `ServerDetail.vue` (enable
Processes tab + mount footer), `services/api.ts` + types (ProcessSnapshot),
`stores/metrics.ts` (optional: hold latest snapshot, or tab-local state).
