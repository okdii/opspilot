# Process Monitoring + Agent Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unblock the deferred Processes tab (§3.10) and Agent Status footer (§3.11) by adding agent data — a live full-process snapshot (on-demand SSH), bounded top-N process history + systemd unit status + per-core CPU (Telegraf), and a DB compression policy — then build the two UI pieces.

**Architecture:** Two complementary process sources. (1) `GET /servers/:id/processes` opens an on-demand `SSHSession` and runs `top -bn2` for the full instantaneous list (no storage, 5s cache, single-flight, graceful-offline). (2) Telegraf gains an `exec` input emitting top-N `proctop` rows every 30s, a single-field per-core `cpu` input, and a scoped `systemd_units` input — all stored, growth-controlled, with a new TimescaleDB compression policy.

**Tech Stack:** FastAPI + asyncssh (`SSHSession`), TimescaleDB (compression), Telegraf (`exec`/`cpu`/`systemd_units` inputs), Vue 3 + Pinia + Vuestic + ApexCharts.

> **Verification model:** No unit-test harness in this repo (per CLAUDE.md Rule 1) → every unit is **smoke-verified** against the live `lima-ubuntu` agent (lima instance name: `ubuntu`; server id `fd772547-2f05-4d93-9ed2-9ddbe3e3646c`). Backend at `http://127.0.0.1:8765`, frontend `http://127.0.0.1:5173`, postgres container `opspilot-postgres`. Browser checks use the host Playwright (`import pw from '/Users/pocketdata/.npm/_npx/9833c18b2d85bc59/node_modules/playwright/index.js'; const {chromium}=pw;`) and login `smoketest_admin` / `SmokeTest!2026`.

---

## File Structure

**Backend**
- Modify `backend/app/services/templates/telegraf.conf.j2` — add `exec` (proctop), second `cpu` input (per-core single-field), scoped `systemd_units`.
- Create `backend/app/services/process_snapshot.py` — `top -bn2` parse + 5s cache + single-flight.
- Modify `backend/app/routers/metrics.py` — replace `/processes` 501 stub with the live snapshot endpoint.
- Create `backend/migrations/versions/0005_server_metrics_compression.py` — compression policy.

**Frontend**
- Create `frontend/src/components/servers/tabs/ProcessesTab.vue` — replaces the disabled stub behavior.
- Create `frontend/src/components/servers/AgentStatusFooter.vue` — §3.11 footer strip.
- Modify `frontend/src/views/servers/ServerDetail.vue` — enable Processes tab + mount footer.
- Modify `frontend/src/services/api.ts` + `frontend/src/types/index.ts` — `getProcesses` + `ProcessSnapshot` types.

---

## SLICE 1 — Telegraf config: proctop exec + per-core + systemd_units

### Task 1: Add the three input blocks to telegraf.conf.j2

**Files:** Modify `backend/app/services/templates/telegraf.conf.j2`

- [ ] **Step 1: Add the blocks** after the existing `[[inputs.cpu]]` / before `{% if mysql_dsn %}`.

Per-core CPU (single field, growth-controlled):
```toml
# ── Per-core CPU (single field — keeps per-core storage tiny) ────────────────
[[inputs.cpu]]
  percpu = true
  totalcpu = false
  collect_cpu_time = false
  report_active = true
  fieldpass = ["usage_active"]
  [inputs.cpu.tags]
    scope = "percore"
```

Scoped systemd unit status (Agent footer):
```toml
# ── Agent service health (scoped to our two agents only) ─────────────────────
[[inputs.systemd_units]]
  pattern = "telegraf.service fluent-bit.service"
```

Top-N process snapshot every 30s (bounded history). `top -bn2 -d0.3` takes two
samples 0.3s apart so the second iteration's `%CPU` is instantaneous; awk keeps
only that last block, sanitizes COMMAND (drop spaces/commas/`=`), then prints the
top-10 by CPU and top-10 by MEM as influx line protocol:
```toml
# ── Top-N processes (proctop) — bounded, 30s ─────────────────────────────────
[[inputs.exec]]
  interval = "30s"
  timeout = "5s"
  data_format = "influx"
  commands = [
    "sh -c \"top -bn2 -d0.3 -w512 | awk 'BEGIN{b=\\\"\\\"} /^[[:space:]]*PID/{b=\\\"\\\";next} {b=b $0 \\\"\\n\\\"} END{printf \\\"%s\\\",b}' | awk 'NF>=12 && $1 ~ /^[0-9]+$/ {name=$12; gsub(/[ ,=]/,\\\"_\\\",name); print $9\\\" \\\"$10\\\" \\\"$1\\\" \\\"name}' | sort -k1 -rn | head -10 | awk '{printf \\\"proctop,by=cpu,pid=%s,name=%s cpu_pct=%s,mem_pct=%s\\n\\\",$3,$4,$1,$2}'; top -bn2 -d0.3 -w512 | awk 'BEGIN{b=\\\"\\\"} /^[[:space:]]*PID/{b=\\\"\\\";next} {b=b $0 \\\"\\n\\\"} END{printf \\\"%s\\\",b}' | awk 'NF>=12 && $1 ~ /^[0-9]+$/ {name=$12; gsub(/[ ,=]/,\\\"_\\\",name); print $10\\\" \\\"$9\\\" \\\"$1\\\" \\\"name}' | sort -k1 -rn | head -10 | awk '{printf \\\"proctop,by=mem,pid=%s,name=%s cpu_pct=%s,mem_pct=%s\\n\\\",$3,$4,$2,$1}'\""
  ]
```
> The `top` column order assumed is the Linux/procps default: `PID USER PR NI VIRT RES SHR S %CPU %MEM TIME+ COMMAND` (cols 1,9,10,12). If smoke shows misaligned values, adjust the awk column indices — verify against the live VM output in Step 3.

- [ ] **Step 2: Validate template still renders.**

Run:
```bash
docker exec opspilot-backend python3 -c "
from app.services.onboarding import _template_env
print(_template_env.get_template('telegraf.conf.j2').render(server_name='x',server_id='y',ingest_url='http://h',ingestion_token='t',mysql_dsn=None)[:1] and 'render-ok')"
```
Expected: `render-ok`

- [ ] **Step 3: Verify the top/awk pipeline produces valid line protocol on the VM** (before redeploy — proves the one-liner).

Run (the inner shell command, executed directly on the VM):
```bash
limactl shell ubuntu -- sh -c "top -bn2 -d0.3 -w512 | awk 'BEGIN{b=\"\"} /^[[:space:]]*PID/{b=\"\";next} {b=b \$0 \"\n\"} END{printf \"%s\",b}' | awk 'NF>=12 && \$1 ~ /^[0-9]+\$/ {name=\$12; gsub(/[ ,=]/,\"_\",name); print \$9\" \"\$10\" \"\$1\" \"name}' | sort -k1 -rn | head -3 | awk '{printf \"proctop,by=cpu,pid=%s,name=%s cpu_pct=%s,mem_pct=%s\n\",\$3,\$4,\$1,\$2}'"
```
Expected: 3 lines like `proctop,by=cpu,pid=1234,name=telegraf cpu_pct=3.4,mem_pct=1.2` with plausible numbers and sanitized names (no spaces/commas).

- [ ] **Step 4: Commit.**
```bash
git add backend/app/services/templates/telegraf.conf.j2
git commit -m "Phase 2: telegraf — proctop top-N exec, per-core cpu, scoped systemd_units"
```

### Task 2: Redeploy the agent + verify new metrics flow

**Files:** none (operational)

- [ ] **Step 1: Trigger redeploy** (re-renders config + restarts telegraf; ~seconds of collection pause).
```bash
docker exec -i opspilot-backend python3 -c "
import asyncio; from app.services.onboarding import run_onboarding
asyncio.run(run_onboarding('fd772547-2f05-4d93-9ed2-9ddbe3e3646c', redeploy_only=True))"
```
Expected: completes without exception (or use `POST /api/servers/:id/redeploy` with an admin cookie).

- [ ] **Step 2: Wait ~40s, then confirm the three new metric families arrived.**
```bash
docker exec opspilot-postgres psql -U opspilot -d opspilot -t -c "
SELECT metric_name, count(*) FROM server_metrics
WHERE time > now() - interval '90 seconds'
  AND (metric_name LIKE 'proctop.%' OR metric_name='systemd_units.active_code'
       OR (metric_name='cpu.usage_active' AND labels->>'scope'='percore'))
GROUP BY metric_name ORDER BY 1;"
```
Expected: `proctop.cpu_pct`, `proctop.mem_pct` (~10–20 rows each per 30s), `systemd_units.active_code` (2 rows: telegraf+fluent-bit), and per-core `cpu.usage_active` (one per core, e.g. 4).

- [ ] **Step 3: Sanity-check proctop values + systemd active state.**
```bash
docker exec opspilot-postgres psql -U opspilot -d opspilot -c "
SELECT labels->>'name' AS proc, value FROM server_metrics
WHERE metric_name='proctop.cpu_pct' ORDER BY time DESC LIMIT 5;
SELECT labels->>'name' AS unit, value AS active_code FROM server_metrics
WHERE metric_name='systemd_units.active_code' ORDER BY time DESC LIMIT 2;"
```
Expected: real process names with cpu_pct values; both units `active_code = 0` (running). No commit (operational task).

---

## SLICE 2 — TimescaleDB compression policy

### Task 3: Compression migration

**Files:** Create `backend/migrations/versions/0005_server_metrics_compression.py`

- [ ] **Step 1: Write the migration.**
```python
"""server_metrics compression policy (compress chunks > 2 days)

Revision ID: 0005_server_metrics_compression
Revises: 0004_maintenance_ends_nullable
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_server_metrics_compression"
down_revision = "0004_maintenance_ends_nullable"
branch_labels = None
depends_on = None

def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        ALTER TABLE server_metrics SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'server_id, metric_name',
            timescaledb.compress_orderby   = 'time DESC'
        )
    """))
    conn.execute(sa.text("SELECT add_compression_policy('server_metrics', INTERVAL '2 days')"))

def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("SELECT remove_compression_policy('server_metrics', if_exists => true)"))
    conn.execute(sa.text("ALTER TABLE server_metrics SET (timescaledb.compress = false)"))
```

- [ ] **Step 2: Apply it.**
```bash
docker exec opspilot-backend alembic upgrade head
```
Expected: `Running upgrade 0004_maintenance_ends_nullable -> 0005_server_metrics_compression`.

- [ ] **Step 3: Verify the policy exists and the table is compress-enabled.**
```bash
docker exec opspilot-postgres psql -U opspilot -d opspilot -c "
SELECT hypertable_name, attname, segmentby_column_index, orderby_column_index
FROM timescaledb_information.compression_settings WHERE hypertable_name='server_metrics';
SELECT j.proc_name FROM timescaledb_information.jobs j WHERE j.hypertable_name='server_metrics' AND j.proc_name='policy_compression';"
```
Expected: compression_settings rows for server_id/metric_name/time; a `policy_compression` job present.

- [ ] **Step 4: Confirm reads still work + continuous aggregates unaffected.**
```bash
docker exec opspilot-postgres psql -U opspilot -d opspilot -c "
SELECT count(*) FROM server_metrics WHERE time > now() - interval '1 hour';
SELECT count(*) FROM server_metrics_hourly WHERE bucket > now() - interval '6 hours';"
```
Expected: both return counts without error (compression coexists with retention + aggregates).

- [ ] **Step 5: Commit.**
```bash
git add backend/migrations/versions/0005_server_metrics_compression.py
git commit -m "Phase 2: TimescaleDB compression policy on server_metrics (>2d chunks)"
```

---

## SLICE 3 — Live process snapshot endpoint

### Task 4: process_snapshot service (parse + cache + single-flight)

**Files:** Create `backend/app/services/process_snapshot.py`

- [ ] **Step 1: Write the service.**
```python
"""On-demand full process snapshot via SSH `top -bn2` (instantaneous CPU).

No storage — pure read. A 5s per-server cache + single-flight lock prevents an
SSH stampede when the Processes tab polls or multiple viewers watch one server."""
import asyncio
import time
from datetime import datetime, timezone

from app.models.server import Server
from app.services.ssh import SSHSession

_CACHE_TTL = 5.0
_cache: dict[str, tuple[float, dict]] = {}
_locks: dict[str, asyncio.Lock] = {}

# top -bn2: two samples 0.3s apart; the 2nd iteration's %CPU is instantaneous.
_TOP_CMD = "top -bn2 -d0.3 -w512"


def _parse_last_iteration(stdout: str) -> list[dict]:
    """Parse the LAST top iteration's process table into dicts."""
    procs: list[dict] = []
    started = False
    header_seen = 0
    lines = stdout.splitlines()
    # find the index of the last header row ("  PID USER ...")
    last_header = -1
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("PID"):
            last_header = i
    if last_header < 0:
        return procs
    for ln in lines[last_header + 1:]:
        parts = ln.split(None, 11)  # COMMAND may contain spaces → keep as one field
        if len(parts) < 12 or not parts[0].isdigit():
            continue
        try:
            procs.append({
                "pid": int(parts[0]),
                "user": parts[1],
                "cpu_pct": float(parts[8].replace(",", ".")),
                "mem_pct": float(parts[9].replace(",", ".")),
                "name": parts[11].strip(),
            })
        except (ValueError, IndexError):
            continue
    return procs


async def _collect(server: Server) -> dict:
    async with SSHSession(server) as ssh:
        res = await ssh.run(_TOP_CMD, timeout=10)
    procs = _parse_last_iteration(res.stdout)
    procs.sort(key=lambda p: p["cpu_pct"], reverse=True)
    top_cpu = procs[:10]
    top_mem = sorted(procs, key=lambda p: p["mem_pct"], reverse=True)[:10]
    return {
        "reachable": True,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "processes": procs,
        "top_cpu": top_cpu,
        "top_mem": top_mem,
    }


async def get_snapshot(server: Server) -> dict:
    sid = str(server.id)
    now = time.monotonic()
    cached = _cache.get(sid)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]
    lock = _locks.setdefault(sid, asyncio.Lock())
    async with lock:
        cached = _cache.get(sid)  # re-check: another caller may have filled it
        if cached and time.monotonic() - cached[0] < _CACHE_TTL:
            return cached[1]
        try:
            payload = await _collect(server)
        except Exception:
            payload = {"reachable": False, "collected_at": None,
                       "processes": [], "top_cpu": [], "top_mem": []}
        _cache[sid] = (time.monotonic(), payload)
        return payload
```
> Verify `ssh.run` accepts a `timeout` kwarg (see `backend/app/services/ssh.py` `run` signature); if not, drop the kwarg — asyncssh has its own timeout. Verify `SSHResult.stdout` is the attribute name.

- [ ] **Step 2: Import-check.**
```bash
docker exec opspilot-backend python3 -c "import app.services.process_snapshot; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit.**
```bash
git add backend/app/services/process_snapshot.py
git commit -m "Phase 2: process_snapshot service (top -bn2 parse, 5s cache, single-flight)"
```

### Task 5: Replace the /processes 501 stub

**Files:** Modify `backend/app/routers/metrics.py`

- [ ] **Step 1: Replace the stub** (the `get_processes` handler that currently raises 501).
```python
from app.models.server import Server
from app.services import process_snapshot
from sqlalchemy import select

@router.get("/{server_id}/processes")
async def get_processes(server_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_server_access(server_id, user, db)
    server = await db.scalar(select(Server).where(Server.id == server_id))
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})
    return await process_snapshot.get_snapshot(server)
```
Remove the old `status_code=501` decorator/body for this route.

- [ ] **Step 2: Smoke test against the live VM.**
```bash
BASE=http://127.0.0.1:8765; SID=fd772547-2f05-4d93-9ed2-9ddbe3e3646c
TOKEN=$(curl -s -c /tmp/cj $BASE/api/auth/login -H 'Content-Type: application/json' -d '{"username":"smoketest_admin","password":"SmokeTest!2026"}' >/dev/null; echo cookie)
curl -s -b /tmp/cj "$BASE/api/servers/$SID/processes" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("reachable",d["reachable"]);print("n_procs",len(d["processes"]));print("top_cpu[0]",d["top_cpu"][0] if d["top_cpu"] else None)'
```
Expected: `reachable True`, `n_procs` in the dozens-hundreds, `top_cpu[0]` a real process with non-null cpu_pct.

- [ ] **Step 3: Verify graceful offline** (simulate by temporarily pointing at a bad host is heavy; instead trust the try/except — confirm a second rapid call is cache-served).
```bash
time curl -s -b /tmp/cj "$BASE/api/servers/$SID/processes" -o /dev/null   # 2nd call < ~50ms = cache hit
```
Expected: near-instant (cache hit within 5s window).

- [ ] **Step 4: Commit.**
```bash
git add backend/app/routers/metrics.py
git commit -m "Phase 2: GET /servers/:id/processes — live SSH snapshot (replaces 501 stub)"
```

---

## SLICE 4 — Processes tab (frontend)

### Task 6: API client + types

**Files:** Modify `frontend/src/services/api.ts`, `frontend/src/types/index.ts`

- [ ] **Step 1: Add types** to `types/index.ts`.
```ts
export interface ProcessRow {
  pid: number
  user?: string
  name: string
  cpu_pct: number
  mem_pct: number
}
export interface ProcessSnapshot {
  reachable: boolean
  collected_at: string | null
  processes: ProcessRow[]
  top_cpu: ProcessRow[]
  top_mem: ProcessRow[]
}
```

- [ ] **Step 2: Add API method** to `services/api.ts` (import `ProcessSnapshot`).
```ts
export async function getProcesses(serverId: string): Promise<ProcessSnapshot> {
  const { data } = await api.get<ProcessSnapshot>(`/api/servers/${serverId}/processes`)
  return data
}
```

- [ ] **Step 3: Type-check + commit.**
```bash
docker exec opspilot-frontend npx vue-tsc --noEmit   # expect exit 0
git add frontend/src/services/api.ts frontend/src/types/index.ts
git commit -m "Phase 2: getProcesses API + ProcessSnapshot types"
```

### Task 7: ProcessesTab.vue

**Files:** Create `frontend/src/components/servers/tabs/ProcessesTab.vue`

- [ ] **Step 1: Build the component.** Contract mirrors other tabs: `defineProps<{ range: MetricRange }>()`. On mount: start a 5s `setInterval` calling `getProcesses(metrics.activeServerId)` into a local `snapshot` ref + a `lastUpdated` ts; also `metrics.loadChartData(['proctop.cpu_pct'], props.range, 'proc.trend')` and `watch(range)` for the trend chart. Clear the interval on unmount. Render:
  - Header row: "Top Processes by CPU" + `Updated {{ago}}s ago` (a 1s ticker; amber >60s, red >120s) + `● Live` badge (green when `snapshot.reachable && lastPollOk`, else grey `Paused`).
  - **Top by CPU** table (snapshot.top_cpu): columns Process / PID / CPU% / MEM% + a `MetricBar` (label=name, value=cpu_pct) per row.
  - **Top by Memory** table (snapshot.top_mem): same, bar value=mem_pct.
  - **All Processes** table (snapshot.processes): Process / PID / User / CPU% / MEM%, with a text filter input and client-side sort (default cpu desc). Use a plain table (DataGrid is server-paginated; a simple `<table>` with computed filter/sort is lighter here).
  - **Top CPU consumers (trend)** `MetricChart type="area" stacked unit="%"` from `toApexSeries(metrics.chartData['proc.trend']?.series ?? [], { name: s => s.labels.name })`.
  - When `snapshot.reachable === false`: show `ui/EmptyState` "Agent unreachable — can't read live processes."
  Match OverviewTab card styling + dark theme (invoke ui-ux-pro-max).

- [ ] **Step 2: Type-check.**
```bash
docker exec opspilot-frontend npx vue-tsc --noEmit
```
Expected: exit 0, no ProcessesTab errors.

- [ ] **Step 3: Commit.**
```bash
git add frontend/src/components/servers/tabs/ProcessesTab.vue
git commit -m "Phase 2: ProcessesTab — top tables, full list, live badge, trend chart"
```

### Task 8: Enable the Processes tab in ServerDetail

**Files:** Modify `frontend/src/views/servers/ServerDetail.vue`

- [ ] **Step 1: Wire it in.** Import `ProcessesTab`; add `'Processes'` to the `TABS` array and to `TAB_COMPONENTS`; remove the separate disabled `<button class="tab disabled">Processes</button>` (it's now a real tab). Keep the tooltip off.

- [ ] **Step 2: Browser smoke (Playwright, lima-ubuntu).** Script `/tmp/proc_smoke.mjs`: login; goto `/servers/<SID>`; click `button.tab:has-text("Processes")`; wait 6s (≥1 poll). Assert: a top-CPU table with ≥1 row, the full-process table has more rows than the top table, `● Live` badge present, `.apexcharts-canvas` ≥ 4 (3 gauges + trend), no `pageerror`. Screenshot `/tmp/proc_tab.png`.
Expected: PASS.

- [ ] **Step 3: Commit + push.**
```bash
git add frontend/src/views/servers/ServerDetail.vue
git commit -m "Phase 2: enable Processes tab in ServerDetail"
git push origin main
```

---

## SLICE 5 — Agent Status footer

### Task 9: AgentStatusFooter.vue

**Files:** Create `frontend/src/components/servers/AgentStatusFooter.vue`

- [ ] **Step 1: Build it.** No props beyond reading the store. Reads `metrics.latestValues['systemd_units.active_code']` (a `LatestLabeled[]` keyed by `labels.name`). Helper: `unitActive(name)` → find entry with `labels.name === name`, running when `value === 0`. Render a persistent strip: `Telegraf ● running|stopped` (green/red via `StatusBadge` or a dot), `Fluent Bit ● running|stopped`, and the interface ↓↑ throughput summary (reuse the network-rate logic shape from ServerDetail — read busiest `net.bytes_recv/sent`; OR keep it minimal: show the active interface name). On a stopped/failed agent, call `useNotify().warning('<Agent> is not running on <server> — metrics may be stale')` **once** per transition (track previous state in a ref to avoid repeat toasts).

- [ ] **Step 2: Type-check.**
```bash
docker exec opspilot-frontend npx vue-tsc --noEmit
```
Expected: exit 0.

- [ ] **Step 3: Commit.**
```bash
git add frontend/src/components/servers/AgentStatusFooter.vue
git commit -m "Phase 2: AgentStatusFooter — telegraf/fluent-bit health + warning toast"
```

### Task 10: Mount footer in ServerDetail + verify both agents + downed-agent toast

**Files:** Modify `frontend/src/views/servers/ServerDetail.vue`

- [ ] **Step 1: Mount** `<AgentStatusFooter />` below the `<component :is>` tab area (persistent across tabs), inside the `v-if="server"` block. Import it.

- [ ] **Step 2: Browser smoke — healthy state.** Playwright `/tmp/footer_smoke.mjs`: login; goto detail; wait 3s; assert footer shows Telegraf + Fluent Bit as running (green). Screenshot.
Expected: both green (active_code=0 from Slice 1).

- [ ] **Step 3: Downed-agent smoke.** Stop fluent-bit on the VM, wait for next flush, reload:
```bash
limactl shell ubuntu -- sudo systemctl stop fluent-bit
sleep 15
```
Re-run a Playwright check: footer shows Fluent Bit red + a warning toast appears. Then restore:
```bash
limactl shell ubuntu -- sudo systemctl start fluent-bit
```
Expected: red badge + toast while stopped; back to green after restart.

- [ ] **Step 4: Commit + push.**
```bash
git add frontend/src/views/servers/ServerDetail.vue
git commit -m "Phase 2: mount AgentStatusFooter on Server Detail"
git push origin main
```

---

## SLICE 6 — Per-core verification + progress reconcile

### Task 11: Verify per-core CPU now populates CpuTab + update dashboards

**Files:** Modify `pm/PROGRESS.md`, `pm/DASHBOARD.html`

- [ ] **Step 1: Confirm per-core data + CpuTab bars.** Playwright: login; goto detail; click CPU tab; wait 2s; assert the "Per-Core Usage" section now renders ≥1 `MetricBar` (no longer the "No per-core data" empty state). (Per-core `cpu.usage_active` with `labels.cpu != 'cpu-total'` now flows from Slice 1.)
Expected: per-core bars present (one per core).

- [ ] **Step 2: Flip PROGRESS.md** — change the deferred items to done:
  - `🔄 GET /api/servers/:id/processes` → `✅ ... (live SSH snapshot — full list + top-CPU/top-mem)`
  - Add `✅ Processes tab (top tables + full list + live badge + top-consumers trend)`
  - Add `✅ Agent Status footer (telegraf/fluent-bit health + warning toast)`
  - Update the CPU per-core note from "graceful empty state" to "✅ per-core bars populate (percpu input)".
  Mirror these in `pm/DASHBOARD.html` (`status: 'pending'`→`'done'` for matching tasks); bump the `Generated:` date if needed.

- [ ] **Step 3: Final full smoke** — run `/tmp/final_smoke.mjs` (from the prior plan) extended to also click the Processes tab; assert all 7 tabs render, Processes enabled, 0 pageerrors, footer present.
Expected: PASS.

- [ ] **Step 4: Commit + push.**
```bash
git add pm/PROGRESS.md pm/DASHBOARD.html
git commit -m "Phase 2: Processes tab + Agent footer + per-core complete; reconcile progress"
git push origin main
```

---

## Self-Review

- **Spec coverage:** §2.1 live snapshot → Tasks 4–5; §2.2 proctop history → Task 1 + trend in Task 7; §3 Agent footer → Tasks 1 (systemd_units) + 9–10; §4 per-core → Task 1 + Task 11; §5 growth control → Task 1 (intervals/fieldpass/scoped) + Task 3 (compression); §6 frontend → Tasks 6–10; §7 deployment → Task 2; §8 verification → smoke steps throughout. All covered.
- **Placeholder scan:** no TBD/TODO; the one judgement note (top column indices) is an explicit verify-against-live instruction, not a gap.
- **Type consistency:** `ProcessSnapshot`/`ProcessRow` field names (`pid,user,name,cpu_pct,mem_pct`,`reachable`,`collected_at`,`processes`,`top_cpu`,`top_mem`) match between backend `_collect`, the TS types, and ProcessesTab usage. `proctop.cpu_pct`/`proctop.mem_pct` metric names match between the telegraf awk output and the trend-chart load. `systemd_units.active_code` matches between Task 1 and the footer. `metrics.loadChartData(metrics, range, key)` / `chartData[key]?.series` / `toApexSeries` reused exactly as in OverviewTab.
