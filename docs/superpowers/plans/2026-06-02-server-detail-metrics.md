# Server Detail — Metrics Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Server Detail metrics page (`/servers/:id`) — backend metric/maintenance endpoints + a live dark-dashboard page with 4 gauges and 6 charted tabs — completing the last pending block of Phase 2.

**Architecture:** A `metric_catalog` module maps idealized spec names → real Telegraf metric names and flags counter metrics; the metrics endpoint serves raw/hourly/daily data and computes per-second rates for counters server-side. The frontend adds a `useMetricsStore`, a single shared `MetricChart` wrapper (first chart use in the repo), and a tabbed `ServerDetail.vue`. Slice A (backend + store + page shell + Overview) lands first as the foundation; tab Slices B–F are independent and parallelizable.

**Tech Stack:** FastAPI + SQLAlchemy async + TimescaleDB (continuous aggregates), Vue 3 + Pinia + Vuestic, ApexCharts via a shared wrapper.

> **Verification model:** This repo has **no unit-test harness** (no pytest/vitest). Per CLAUDE.md Rule 1, every unit is verified by **smoke test** — curl against live data on `lima-ubuntu` (server `fd772547-2f05-4d93-9ed2-9ddbe3e3646c`) and browser walkthrough. This overrides the skill's default TDD steps. Where pure logic correctness matters (rate computation), a throwaway inline Python assertion is included.

> **Smoke-test prelude (run once per session):**
> ```bash
> BASE=http://127.0.0.1:8765
> SID=fd772547-2f05-4d93-9ed2-9ddbe3e3646c
> # Obtain an admin JWT (adjust creds to your seeded admin):
> TOKEN=$(curl -s $BASE/api/auth/login -H 'Content-Type: application/json' \
>   -d '{"email":"clacode01@pocketdata.com.my","password":"<admin-pw>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
> AUTH="Authorization: Bearer $TOKEN"
> ```

---

## File Structure

**Backend (create):**
- `backend/app/services/metric_catalog.py` — name mapping, counter flags, FS denylist, range→source map
- `backend/app/routers/metrics.py` — `GET /api/servers/:id/metrics`, `/metrics/latest`, `/processes` (stub)
- `backend/app/routers/maintenance.py` — `GET/POST/DELETE /api/servers/:id/maintenance`
- `backend/app/schemas/metrics.py` — response/request models
- `backend/migrations/versions/0004_maintenance_ends_nullable.py` — make `maintenance_window.ends_at` nullable

**Backend (modify):**
- `backend/app/main.py` — register the two new routers
- `backend/app/services/scheduler.py` (or wherever APScheduler lives) — add `maintenance_expiry` 60s job

**Frontend (create):**
- `frontend/src/components/charts/MetricChart.vue` — shared ApexCharts wrapper (+ export in a barrel)
- `frontend/src/stores/metrics.ts` — `useMetricsStore`
- `frontend/src/views/servers/ServerDetail.vue` — page shell, header, gauges, tab nav
- `frontend/src/components/servers/MaintenanceSlideOver.vue`
- `frontend/src/components/servers/tabs/OverviewTab.vue`, `CpuTab.vue`, `MemoryTab.vue`, `DiskTab.vue`, `NetworkTab.vue`, `SystemTab.vue`

**Frontend (modify):**
- `frontend/src/router/*` — add `/servers/:id` route
- `frontend/src/services/` API client — add metrics/maintenance calls
- `frontend/src/stores/server.ts` or WS dispatcher in `AppLayout.vue` — route `server_metrics:{id}` push to metrics store

---

# SLICE A — Foundation (sequential; must land before B–F)

### Task A1: Metric catalog module

**Files:**
- Create: `backend/app/services/metric_catalog.py`

- [ ] **Step 1: Write the module**

```python
"""Single source of truth mapping spec-04 metric concepts to real Telegraf
metric names (verified against live ingestion 2026-06-02). Endpoints, rate
logic, and the frontend's requested names all resolve through here."""

# Telegraf metrics that are cumulative monotonic counters → must be served as
# per-second rates (delta / dt), never raw.
COUNTER_METRICS: set[str] = {
    "diskio.read_bytes", "diskio.write_bytes", "diskio.reads", "diskio.writes",
    "net.bytes_recv", "net.bytes_sent", "net.packets_recv", "net.packets_sent",
    "net.err_in", "net.err_out", "net.drop_in", "net.drop_out",
}

# Filesystem types to exclude from disk queries (pseudo / virtual filesystems).
REAL_FS_DENYLIST: set[str] = {
    "tmpfs", "devtmpfs", "efivarfs", "squashfs", "overlay", "proc", "sysfs",
    "cgroup", "cgroup2", "devpts", "mqueue", "debugfs", "tracefs", "ramfs",
    "fusectl", "configfs", "pstore", "bpf", "autofs", "binfmt_misc", "hugetlbfs",
}

# range -> (source_table, value_column, time_column, resolution_label)
RANGE_SOURCE: dict[str, tuple[str, str, str, str]] = {
    "1h":  ("server_metrics",        "value",     "time",   "10s"),
    "6h":  ("server_metrics",        "value",     "time",   "10s"),
    "24h": ("server_metrics_hourly", "avg_value", "bucket", "1h"),
    "7d":  ("server_metrics_daily",  "avg_value", "bucket", "24h"),
    "30d": ("server_metrics_daily",  "avg_value", "bucket", "24h"),
}

# range -> lookback interval for the WHERE clause
RANGE_INTERVAL: dict[str, str] = {
    "1h": "1 hour", "6h": "6 hours", "24h": "24 hours", "7d": "7 days", "30d": "30 days",
}

def is_counter(metric_name: str) -> bool:
    return metric_name in COUNTER_METRICS

def fs_denylist_sql_array() -> list[str]:
    return sorted(REAL_FS_DENYLIST)
```

- [ ] **Step 2: Smoke-verify the names exist in live data**

Run:
```bash
docker exec opspilot-postgres psql -U opspilot -d opspilot -t -c \
"SELECT count(DISTINCT metric_name) FROM server_metrics WHERE metric_name IN \
('cpu.usage_active','mem.used_percent','disk.used_percent','diskio.read_bytes','net.bytes_recv','system.load1','system.n_cpus','swap.total');"
```
Expected: `8`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/metric_catalog.py
git commit -m "Phase 2: metric_catalog — Telegraf name map + counter/FS rules"
```

---

### Task A2: Rate computation helper

**Files:**
- Modify: `backend/app/services/metric_catalog.py`

- [ ] **Step 1: Add `to_rate`**

```python
def to_rate(points: list[dict]) -> list[dict]:
    """Convert a cumulative-counter series into per-second rates.
    points: [{"time": iso_or_dt, "value": float}, ...] sorted ascending by time.
    Returns one fewer point (first has no predecessor). Negative deltas
    (counter reset) are dropped."""
    out: list[dict] = []
    for prev, cur in zip(points, points[1:]):
        dt = (cur["_t"] - prev["_t"]).total_seconds()
        if dt <= 0:
            continue
        delta = cur["value"] - prev["value"]
        if delta < 0:            # counter reset / reboot
            continue
        out.append({"time": cur["time"], "value": round(delta / dt, 4)})
    return out
```
(Note: the endpoint attaches a parsed datetime under `_t` for each point before calling this, and strips it from the output.)

- [ ] **Step 2: Throwaway correctness check**

Run:
```bash
docker exec -i opspilot-backend python3 - <<'PY'
from datetime import datetime, timedelta
from app.services.metric_catalog import to_rate
t0=datetime(2026,1,1,0,0,0)
pts=[{"time":"a","value":100,"_t":t0},
     {"time":"b","value":160,"_t":t0+timedelta(seconds=10)},  # +60/10s = 6.0
     {"time":"c","value":10, "_t":t0+timedelta(seconds=20)}]  # reset -> dropped
r=to_rate(pts)
assert r==[{"time":"b","value":6.0}], r
print("OK", r)
PY
```
Expected: `OK [{'time': 'b', 'value': 6.0}]`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/metric_catalog.py
git commit -m "Phase 2: counter->rate helper for diskio/net metrics"
```

---

### Task A3: Metrics schemas

**Files:**
- Create: `backend/app/schemas/metrics.py`

- [ ] **Step 1: Write schemas**

```python
from pydantic import BaseModel

class SeriesPoint(BaseModel):
    time: str
    value: float | None

class MetricSeries(BaseModel):
    metric_name: str
    labels: dict
    data: list[SeriesPoint]

class MetricsResponse(BaseModel):
    range: str
    resolution: str
    series: list[MetricSeries]
```

- [ ] **Step 2: Import-check**

Run: `docker exec opspilot-backend python3 -c "import app.schemas.metrics; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/metrics.py
git commit -m "Phase 2: metrics response schemas"
```

---

### Task A4: `GET /api/servers/:id/metrics`

**Files:**
- Create: `backend/app/routers/metrics.py`
- Modify: `backend/app/main.py` (register router)

- [ ] **Step 1: Write the endpoint**

```python
"""Server-detail historical metric reads (spec 04 §5)."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import CurrentUser
from app.routers.servers import _assert_server_access  # add if missing; see note
from app.services.metric_catalog import (
    RANGE_SOURCE, RANGE_INTERVAL, is_counter, to_rate, REAL_FS_DENYLIST,
)

router = APIRouter(prefix="/api/servers", tags=["metrics"])


def _parse_label_filter(lf: str | None) -> tuple[str, str] | None:
    if not lf or "=" not in lf:
        return None
    k, v = lf.split("=", 1)
    return k.strip(), v.strip()


@router.get("/{server_id}/metrics")
async def get_metrics(
    server_id: str,
    user: CurrentUser,
    range: str = Query(...),
    metrics: str = Query(...),
    label_filter: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    await _assert_server_access(server_id, user, db)
    if range not in RANGE_SOURCE:
        raise HTTPException(400, f"invalid range: {range}")
    source, valcol, timecol, resolution = RANGE_SOURCE[range]
    interval = RANGE_INTERVAL[range]
    names = [m.strip() for m in metrics.split(",") if m.strip()]
    if not names:
        raise HTTPException(400, "no metrics requested")

    lf = _parse_label_filter(label_filter)
    where_label = ""
    params: dict = {"sid": server_id, "names": names}
    if lf:
        where_label = " AND labels->>:lkey = :lval "
        params["lkey"], params["lval"] = lf

    # Always exclude pseudo-filesystems for disk.* metrics.
    where_fs = ""
    if any(n.startswith("disk.") for n in names):
        where_fs = " AND (labels->>'fstype' IS NULL OR labels->>'fstype' <> ALL(:denyfs)) "
        params["denyfs"] = sorted(REAL_FS_DENYLIST)

    stmt = text(f"""
        SELECT metric_name, labels, {timecol} AS t, {valcol} AS v
        FROM {source}
        WHERE server_id = :sid
          AND metric_name IN :names
          AND {timecol} >= now() - INTERVAL '{interval}'
          {where_label}
          {where_fs}
        ORDER BY metric_name, labels, {timecol} ASC
    """).bindparams(bindparam("names", expanding=True))

    rows = (await db.execute(stmt, params)).all()

    # group into series keyed by (metric_name, frozenset(labels))
    grouped: dict[tuple, dict] = {}
    for mname, labels, t, v in rows:
        labels = labels or {}
        key = (mname, tuple(sorted(labels.items())))
        g = grouped.setdefault(key, {"metric_name": mname, "labels": labels, "_pts": []})
        g["_pts"].append({"time": t.isoformat(), "value": float(v) if v is not None else None, "_t": t})

    series = []
    for g in grouped.values():
        pts = g["_pts"]
        if is_counter(g["metric_name"]):
            pts = to_rate([p for p in pts if p["value"] is not None])
        else:
            pts = [{"time": p["time"], "value": p["value"]} for p in pts]
        series.append({"metric_name": g["metric_name"], "labels": g["labels"], "data": pts})

    return {"range": range, "resolution": resolution, "series": series}
```

> **Note:** If `_assert_server_access` does not exist in `servers.py`, add it there (reuse `_assert_org_access` against the server's `org_id`) so all server-detail routes share one guard. Check first; do not duplicate.

- [ ] **Step 2: Register router in `main.py`**

```python
from app.routers import metrics as metrics_router
app.include_router(metrics_router.router)
```

- [ ] **Step 3: Smoke test — raw range**

Run:
```bash
curl -s -H "$AUTH" "$BASE/api/servers/$SID/metrics?range=1h&metrics=cpu.usage_active,mem.used_percent" | python3 -m json.tool | head -30
```
Expected: `range":"1h"`, `resolution":"10s"`, two series with ascending `data` points.

- [ ] **Step 4: Smoke test — rate + disk FS filter + aggregate range**

Run:
```bash
curl -s -H "$AUTH" "$BASE/api/servers/$SID/metrics?range=1h&metrics=net.bytes_recv" | python3 -c 'import sys,json;d=json.load(sys.stdin);vals=[p["value"] for s in d["series"] for p in s["data"]];print("min",min(vals),"all>=0",all(v>=0 for v in vals))'
curl -s -H "$AUTH" "$BASE/api/servers/$SID/metrics?range=1h&metrics=disk.used_percent" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("mounts",sorted({s["labels"].get("path") for s in d["series"]}))'
curl -s -H "$AUTH" "$BASE/api/servers/$SID/metrics?range=24h&metrics=cpu.usage_active" | python3 -c 'import sys,json;print("24h res",json.load(sys.stdin)["resolution"])'
```
Expected: `all>=0 True`; mounts list contains real paths (e.g. `/`) and **not** `/sys/firmware/efi/efivars`; `24h res 1h`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/metrics.py backend/app/main.py backend/app/routers/servers.py
git commit -m "Phase 2: GET /servers/:id/metrics — ranges, rates, FS filter"
```

---

### Task A5: `GET /metrics/latest` + `GET /processes` stub

**Files:**
- Modify: `backend/app/routers/metrics.py`

- [ ] **Step 1: Add latest + processes-stub endpoints**

```python
@router.get("/{server_id}/metrics/latest")
async def get_latest(server_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_server_access(server_id, user, db)
    rows = (await db.execute(text("""
        SELECT DISTINCT ON (metric_name, labels)
               metric_name, labels, value, time
        FROM server_metrics
        WHERE server_id = :sid
          AND time >= now() - INTERVAL '10 minutes'
        ORDER BY metric_name, labels, time DESC
    """), {"sid": server_id})).all()

    out: dict = {}
    for mname, labels, value, t in rows:
        labels = labels or {}
        entry = {"value": float(value) if value is not None else None,
                 "labels": labels, "time": t.isoformat()}
        if labels and any(k in labels for k in ("path", "interface", "name", "cpu")):
            out.setdefault(mname, [])
            if isinstance(out[mname], list):
                out[mname].append(entry)
        else:
            out[mname] = {"value": entry["value"], "time": entry["time"]}
    return out


@router.get("/{server_id}/processes", status_code=501)
async def get_processes(server_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_server_access(server_id, user, db)
    raise HTTPException(
        status_code=501,
        detail={"blocked": "agent-config", "detail": "top_processes not collected by Telegraf"},
    )
```

- [ ] **Step 2: Smoke test**

Run:
```bash
curl -s -H "$AUTH" "$BASE/api/servers/$SID/metrics/latest" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("cpu_total",d.get("cpu.usage_active"));print("n_cpus",d.get("system.n_cpus"));print("disk_is_list",isinstance(d.get("disk.used_percent"),list))'
echo "--- processes (expect 501) ---"
curl -s -o /dev/null -w "%{http_code}\n" -H "$AUTH" "$BASE/api/servers/$SID/metrics/processes" 2>/dev/null
curl -s -o /dev/null -w "%{http_code}\n" -H "$AUTH" "$BASE/api/servers/$SID/processes"
```
Expected: cpu_total dict with value; `disk_is_list True`; processes endpoint returns `501`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/metrics.py
git commit -m "Phase 2: GET /metrics/latest (gauges) + /processes 501 stub"
```

---

### Task A6: Maintenance endpoints + nullable ends_at migration + expiry job

**Files:**
- Create: `backend/migrations/versions/0004_maintenance_ends_nullable.py`
- Create: `backend/app/routers/maintenance.py`
- Modify: `backend/app/main.py`, scheduler module

- [ ] **Step 1: Migration — make `ends_at` nullable**

```python
"""maintenance_window.ends_at nullable for indefinite maintenance

Revision ID: 0004_maintenance_ends_nullable
Revises: 0003_settings_columns
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_maintenance_ends_nullable"
down_revision = "0003_settings_columns"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.alter_column("maintenance_window", "ends_at", existing_type=sa.DateTime(timezone=True), nullable=True)

def downgrade() -> None:
    op.alter_column("maintenance_window", "ends_at", existing_type=sa.DateTime(timezone=True), nullable=False)
```
Also set `ends_at: Mapped[datetime | None]` + `nullable=True` in `models/other.py`.

- [ ] **Step 2: Write maintenance router**

```python
"""Server maintenance windows (spec 04 §3.1)."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import CurrentUser
from app.models.other import MaintenanceWindow
from app.routers.servers import _assert_server_access, _require_admin

router = APIRouter(prefix="/api/servers", tags=["maintenance"])

class MaintenanceIn(BaseModel):
    reason: str | None = None
    ends_at: datetime | None = None

def _active_window(db_rows):
    now = datetime.now(timezone.utc)
    for w in db_rows:
        if w.starts_at <= now and (w.ends_at is None or w.ends_at > now):
            return w
    return None

@router.get("/{server_id}/maintenance")
async def get_maintenance(server_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_server_access(server_id, user, db)
    rows = (await db.execute(select(MaintenanceWindow).where(MaintenanceWindow.server_id == server_id))).scalars().all()
    w = _active_window(rows)
    if not w:
        return {"active": False}
    return {"active": True, "reason": w.note, "starts_at": w.starts_at.isoformat(),
            "ends_at": w.ends_at.isoformat() if w.ends_at else None}

@router.post("/{server_id}/maintenance", status_code=201)
async def start_maintenance(server_id: str, body: MaintenanceIn, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_server_access(server_id, user, db)
    _require_admin(user)
    w = MaintenanceWindow(server_id=server_id, starts_at=datetime.now(timezone.utc),
                          ends_at=body.ends_at, note=body.reason, created_by=user.id)
    db.add(w)
    # Suppress this server's active alerts (no email for this transition). Spec 10 §16.
    await db.execute(text("""
        UPDATE alert SET state='suppressed'
        WHERE server_id = :sid AND state IN ('firing','acknowledged','snoozed')
    """), {"sid": server_id})
    await db.commit()
    return {"active": True}

@router.delete("/{server_id}/maintenance", status_code=204)
async def end_maintenance(server_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_server_access(server_id, user, db)
    _require_admin(user)
    rows = (await db.execute(select(MaintenanceWindow).where(MaintenanceWindow.server_id == server_id))).scalars().all()
    w = _active_window(rows)
    if w:
        w.ends_at = datetime.now(timezone.utc)
        await db.commit()
    return None
```
> If `_require_admin` doesn't exist, reuse the existing admin guard pattern used by other Admin-only routes (e.g. server create/delete). Check `servers.py`/`deps.py` first.

- [ ] **Step 3: Add `maintenance_expiry` 60s scheduler job**

Locate the APScheduler setup (SQLAlchemy job store). Add a job that ends expired windows:
```python
async def maintenance_expiry_tick():
    # no-op placeholder for alert un-suppression (Phase 8 owns re-fire);
    # here we just let windows lapse — _active_window already treats past ends_at as inactive.
    pass

scheduler.add_job(maintenance_expiry_tick, "interval", seconds=60,
                  id="maintenance_expiry", replace_existing=True)
```
(The window auto-becomes inactive once `ends_at` passes because `_active_window` checks it; the tick exists per spec for future alert re-evaluation.)

- [ ] **Step 4: Register router + run migration**

```python
from app.routers import maintenance as maintenance_router
app.include_router(maintenance_router.router)
```
Run: `docker exec opspilot-backend alembic upgrade head`
Expected: `Running upgrade 0003_settings_columns -> 0004_maintenance_ends_nullable`

- [ ] **Step 5: Smoke test full lifecycle**

```bash
curl -s -H "$AUTH" -H 'Content-Type: application/json' -X POST "$BASE/api/servers/$SID/maintenance" -d '{"reason":"smoke test"}' -w "\n%{http_code}\n"
curl -s -H "$AUTH" "$BASE/api/servers/$SID/maintenance" | python3 -m json.tool
curl -s -o /dev/null -w "%{http_code}\n" -H "$AUTH" -X DELETE "$BASE/api/servers/$SID/maintenance"
curl -s -H "$AUTH" "$BASE/api/servers/$SID/maintenance" | python3 -m json.tool
```
Expected: POST→201; GET shows `"active": true, "reason":"smoke test"`; DELETE→204; final GET shows `"active": false`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/maintenance.py backend/app/main.py backend/migrations/versions/0004_maintenance_ends_nullable.py backend/app/models/other.py
git commit -m "Phase 2: maintenance endpoints + nullable ends_at + expiry job"
```

---

### Task A7: Shared `MetricChart.vue` wrapper

**Files:**
- Create: `frontend/src/components/charts/MetricChart.vue`
- Modify: `frontend/package.json` (add `apexcharts`, `vue3-apexcharts` if absent), a barrel `components/charts/index.ts`

> **UI/UX:** invoke `ui-ux-pro-max` (dark-dashboard) for chart colors/spacing. Reuse theme tokens — do not hardcode colors per tab.

- [ ] **Step 1: Verify/add chart dependency**

Run: `docker exec opspilot-frontend sh -c 'ls node_modules | grep -i apexcharts || echo MISSING'`
If MISSING: `docker exec opspilot-frontend npm install apexcharts vue3-apexcharts`

- [ ] **Step 2: Write the wrapper**

Props: `type` (`area|line|bar|donut|radialBar`), `series` (ApexAxisChartSeries), `categories?`, `unit?` (`%|bytes/s|count|ms`), `thresholds?` (`{value:number,color:string}[]`), `height?` (default 300), `stacked?`. Builds ApexCharts options from dark-theme tokens, formats y-axis by `unit` (human bytes/s for `bytes/s`), draws threshold annotation lines, renders `<apexchart>`. Single component all tabs use.

- [ ] **Step 3: Type-check**

Run: `docker exec opspilot-frontend npx vue-tsc --noEmit`
Expected: no errors referencing `MetricChart.vue`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/charts/ frontend/package.json frontend/package-lock.json
git commit -m "Phase 2: shared MetricChart wrapper (ApexCharts, dark theme)"
```

---

### Task A8: `useMetricsStore`

**Files:**
- Create: `frontend/src/stores/metrics.ts`
- Modify: API client service to add `getMetrics`, `getLatest`, `getMaintenance`, `startMaintenance`, `endMaintenance`

- [ ] **Step 1: Write the store** (per spec §6)

State: `activeServerId`, `selectedRange` (record keyed by tab, persisted via localStorage), `chartData: Record<string, Series[]>`, `latestValues: Record<string, any>`, `maintenance`. Actions:
- `loadServer(id)` → set id, fetch `getLatest`, set gauges
- `loadChartData(metrics: string[], range, key)` → `getMetrics`, store under `key`
- `applyLivePush(rows)` → update `latestValues`; for raw ranges append to matching `chartData` series; for 24h recompute rightmost hour bucket via running avg (track `_sum/_count` per series), replace in place; 7d/30d no-op
- `trimChartData(range)` → drop points older than the range window

- [ ] **Step 2: Type-check**

Run: `docker exec opspilot-frontend npx vue-tsc --noEmit`
Expected: clean for `metrics.ts`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/metrics.ts frontend/src/services/
git commit -m "Phase 2: useMetricsStore + metrics/maintenance API client"
```

---

### Task A9: `ServerDetail.vue` shell + gauges + Overview tab + WS wiring

**Files:**
- Create: `frontend/src/views/servers/ServerDetail.vue`, `components/servers/MaintenanceSlideOver.vue`, `components/servers/tabs/OverviewTab.vue`
- Modify: router (add `/servers/:id`), WS dispatcher (route `server_metrics:{id}` → `metrics.applyLivePush`)

> **Reuse:** `ui/PageHeader` (header), `ui/StatusBadge` (status/maintenance), `ui/SlideOver` (maintenance panel), `ui/StatCard`/`MetricBar` (gauges/disk), `ui/EmptyState`. Invoke `ui-ux-pro-max`.

- [ ] **Step 1: Router** — add route `{ path: '/servers/:id', component: ServerDetail }`. On mount send WS `{action:'subscribe', server_id}`; on unmount `{action:'unsubscribe', server_id}`. Org-switch watcher → redirect `/servers`.

- [ ] **Step 2: Header + 4 gauges** — header (back link, name, status dot, host/OS, tags, `[⋮]` with Toggle Maintenance). Gauges: CPU radial (`cpu.usage_active` + user/system/iowait subtext), RAM radial (`mem.used_percent` + used/total), Disk radial (max `disk.used_percent` + per-mount lines), Network (↓`net.bytes_recv` ↑`net.bytes_sent` rates, iface name). All from `latestValues`; threshold colors green/amber/red (70/85).

- [ ] **Step 3: MaintenanceSlideOver** — reason field, end-time options (none / duration / specific), Enable/End actions calling store; active-state view per spec §3.1.

- [ ] **Step 4: Tab nav + range selector** — tabs Overview/CPU/Memory/Disk/Network/System + disabled Processes (tooltip: "Requires agent procstat — deferred"). Range selector `1h/6h/24h/7d/30d` persisted per tab.

- [ ] **Step 5: OverviewTab** — 5 stacked `MetricChart`s: CPU area (`cpu.usage_active`), Memory dual-line (`mem.used_percent` + derived available), Disk horizontal bars (`MetricBar` per mount from latest), Network dual-line (`net.bytes_recv/sent` rates), Load 3-line (`system.load1/5/15`).

- [ ] **Step 6: Smoke test (browser, live)**

1. Open `http://localhost:5173/servers/fd772547-2f05-4d93-9ed2-9ddbe3e3646c`.
2. Confirm 4 gauges populate with real values; Overview charts render with data.
3. Spike CPU on the VM (`lima shell lima-ubuntu -- sh -c 'yes>/dev/null & yes>/dev/null & sleep 20; kill %1 %2'`); watch CPU gauge + Overview CPU chart rise live with **no reload** (WS).
4. `[⋮] → Toggle Maintenance` → enable → header shows Maintenance badge → End → reverts.

- [ ] **Step 7: Update dashboards + commit** (Rules 0/4)

Flip the relevant Phase 2 `⬜→✅` lines in `pm/PROGRESS.md` and `status:'pending'→'done'` in `pm/DASHBOARD.html`; bump `LAST_UPDATED`.
```bash
git add frontend/src pm/PROGRESS.md pm/DASHBOARD.html
git commit -m "Phase 2: ServerDetail shell + gauges + Overview tab + live WS"
git push origin main
```

---

# SLICES B–F — Tabs (independent; parallelizable after Slice A)

> Each tab is a self-contained component under `components/servers/tabs/` that reads
> the shared store + `MetricChart`. No shared mutable state between B–F. Each task ends
> with its own browser smoke test, PROGRESS/DASHBOARD update, and commit+push.
> Invoke `ui-ux-pro-max` for each.

### Task B: CPU tab

**Files:** Create `frontend/src/components/servers/tabs/CpuTab.vue`

- [ ] **Step 1:** Three charts: (1) CPU Usage area (`cpu.usage_active`, `cpu-total`), with red dashed threshold annotation from the server's `cpu` AlertRule if present (else none). (2) Breakdown stacked-area (`cpu.usage_user/system/iowait/steal`, `cpu-total`). (3) Per-core horizontal `MetricBar`s — one per `cpu` label ≠ `cpu-total` from `getMetrics(['cpu.usage_active'])` grouped by `cpu` label (live-updated from `latestValues`).
- [ ] **Step 2 (smoke):** Open CPU tab → all three render with real data; per-core count matches `system.n_cpus`; spike CPU → bars + area update live.
- [ ] **Step 3:** Update PROGRESS/DASHBOARD; `git commit -m "Phase 2: CPU tab"` + push.

### Task C: Memory tab

**Files:** Create `MemoryTab.vue`

- [ ] **Step 1:** (1) RAM % area (`mem.used_percent`). (2) Breakdown stacked horizontal bar from latest (`mem.used/cached/buffered/free` in GB). (3) Swap area (`swap.used_percent`) — render **only if** `latestValues['swap.total'].value > 0`, else note "No swap configured on this server."
- [ ] **Step 2 (smoke):** Open Memory tab → RAM area + breakdown render; swap section correctly shown/hidden per VM's swap.
- [ ] **Step 3:** Update PROGRESS/DASHBOARD; commit `"Phase 2: Memory tab"` + push.

### Task D: Disk tab

**Files:** Create `DiskTab.vue`

- [ ] **Step 1:** (1) Donut per mount (`MetricChart type=donut`) from latest `disk.used_percent`/`disk.used`/`disk.total` per `path`; group >3 mounts into "Other". (2) Usage history area, one line per mount (`getMetrics(['disk.used_percent'])`). (3) I/O throughput dual-line (`diskio.read_bytes/write_bytes` rates, `bytes/s` unit) with device dropdown (`name` label) if >1 device. (4) IOPS dual-line (`diskio.reads/writes` rates). (5) Util area (`diskio.io_util`, red >80%). (6) Latency line (`diskio.io_await`). Inode row only if any mount `disk.inodes_used_percent>50`.
- [ ] **Step 2 (smoke):** Open Disk tab → donuts show real mounts (no efivarfs); I/O charts show non-negative rates; device dropdown appears only if multiple devices.
- [ ] **Step 3:** Update PROGRESS/DASHBOARD; commit `"Phase 2: Disk tab"` + push.

### Task E: Network tab

**Files:** Create `NetworkTab.vue`

- [ ] **Step 1:** Interface selector (`interface` label; hidden if one iface). (1) Throughput dual-line (`net.bytes_recv/sent` rates, `bytes/s`). (2) Packets dual-line (`net.packets_recv/sent` rates). (3) Errors/drops grouped bar (`net.err_in/out`, `net.drop_in/out` rates).
- [ ] **Step 2 (smoke):** Open Network tab → throughput/packets render with non-negative rates; iface selector behaves; y-axis human-formatted (KB/s, MB/s).
- [ ] **Step 3:** Update PROGRESS/DASHBOARD; commit `"Phase 2: Network tab"` + push.

### Task F: System tab

**Files:** Create `SystemTab.vue`

- [ ] **Step 1:** (1) Load avg 3-line (`system.load1/5/15`) with dashed reference at `system.n_cpus`. (2) Process count area (`processes.total`). (3) Zombie bar (`processes.zombies`, orange if >0, threshold line at 1). (4) Static system-info card: OS/kernel (from server row), uptime (`system.uptime`→"X days X hours"), vCPUs (`system.n_cpus`), RAM (`mem.total`→GB) — fetched once.
- [ ] **Step 2 (smoke):** Open System tab → load chart with vCPU reference line; process count + zombie render; info card shows correct uptime/vCPU/RAM.
- [ ] **Step 3:** Update PROGRESS/DASHBOARD; commit `"Phase 2: System tab"` + push.

---

## Deferred (do NOT build — log only)

- **Processes tab (spec §3.10)** and **Agent Status footer (spec §3.11)** — blocked on Telegraf config. Add a `⬜ (blocked: agent procstat/systemd inputs)` note under Phase 2 in `pm/PROGRESS.md`, and a Phase 1 follow-up line to extend `telegraf.conf.j2` with `[[inputs.procstat]]` (top-N) + a systemd input, then agent re-deploy.

---

## Self-Review

- **Spec coverage:** §3.1 header/maintenance → A6+A9; §3.2 gauges → A9; §3.3 tabs+range → A9; §3.4 Overview → A9; §3.5 CPU → B; §3.6 Memory → C; §3.7 Disk → D; §3.8 Network → E; §3.9 System → F; §3.10/§3.11 → deferred (logged); §4 WS → A8+A9; §5 endpoints → A4/A5/A6; §6 stores → A8. All covered.
- **Type consistency:** `to_rate` input keys (`time/value/_t`) match A4 usage; `RANGE_SOURCE`/`RANGE_INTERVAL` keys identical; store action names reused verbatim in A9 + tabs.
- **Counter handling:** all `diskio.*`/`net.*` charts specify rates; `to_rate` clamps negatives.
- **Reuse:** existing `ui/*` primitives named per task; single `MetricChart` for all charts.
