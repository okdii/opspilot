# WebSocket Live Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push new metric rows from the ingest endpoint to subscribed WebSocket clients in 500ms batches, with server-side subscribe authorization.

**Architecture:** In-process `LiveBus` buffers parsed rows per server; one background task flushes every 500ms via `ws_manager.broadcast_metrics`, which fans out to connections subscribed to the server **or** its org. No PostgreSQL LISTEN/NOTIFY (single backend process — see PRD §5.4.8). Subscribe actions are authorized against role/org-membership.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, asyncpg, TimescaleDB.

**Verification convention:** This project has **no pytest** and verifies via **smoke tests** (CLAUDE.md Rule 1) — curl / `python -c` / WebSocket client scripts run against the live stack (backend `127.0.0.1:8765`, the onboarded `lima-ubuntu` VM emitting real metrics). Each task is implement → smoke-verify (exact command + expected output) → commit. Do **not** add a pytest suite.

**Spec:** `docs/superpowers/specs/2026-06-02-ws-live-infrastructure-design.md`

---

## File structure

| File | Responsibility | Action |
|---|---|---|
| `backend/app/ws/manager.py` | WS connection registry + fan-out | Modify — add `broadcast_metrics` |
| `backend/app/ws/live_bus.py` | In-process buffer + 500ms flush loop (the multi-process seam) | Create |
| `backend/app/ws/authz.py` | Subscribe authorization helpers | Create |
| `backend/app/services/ingestion.py` | Metric parsing/persistence + live publish | Modify — `write_metrics` signature + publish hook |
| `backend/app/routers/ingest.py` | Ingest endpoints | Modify — pass `server.org_id` to `write_metrics` |
| `backend/app/main.py` | App lifespan + WS endpoint | Modify — start flush loop; authorize subscribes; add `unsubscribe_org` |

**Pre-req for smoke steps:** a logged-in admin cookie + the lima server/org IDs. Run this once at the start of any smoke step and reuse `$TOK`, `$SID`, `$ORG`:

```bash
cd /Users/pocketdata/Code/Work/opspilot
H='$2b$12$5FtoMstccMPVWSs7us0S1Oj2qMXxOqQ4BuEzN9wjjgsxpO1yGoxV2'  # bcrypt of SmokeTest123!
docker exec opspilot-postgres psql -U opspilot -d opspilot -q -c \
"INSERT INTO \"user\" (id, username, password_hash, role) VALUES (gen_random_uuid(),'smoketest_admin','$H','admin') ON CONFLICT (username) DO UPDATE SET password_hash=EXCLUDED.password_hash, role='admin';"
export TOK=$(curl -s -c - -X POST http://127.0.0.1:8765/api/auth/login -H 'Content-Type: application/json' -d '{"username":"smoketest_admin","password":"SmokeTest123!"}' | grep opspilot_jwt | awk '{print $7}')
export SID=$(docker exec opspilot-postgres psql -U opspilot -d opspilot -tA -c "SELECT id FROM server WHERE name='lima-ubuntu' LIMIT 1;")
export ORG=$(docker exec opspilot-postgres psql -U opspilot -d opspilot -tA -c "SELECT id FROM organization LIMIT 1;")
echo "TOK len=${#TOK} SID=$SID ORG=$ORG"
```

Cleanup (after the final task): delete the `smoketest_admin` user.

---

## Task 1: `broadcast_metrics` on the WS manager

**Files:**
- Modify: `backend/app/ws/manager.py`

- [ ] **Step 1: Add the method** after `broadcast_server` (after line 63)

```python
    async def broadcast_metrics(self, server_id: str, org_id: str, payload: dict) -> None:
        """Fan a server's metric batch out to connections subscribed to that
        server OR to its org (the global dashboard subscribes by org)."""
        msg = json.dumps(payload)
        dead = []
        async with self._lock:
            targets = [
                c for c in self._connections
                if server_id in c.subscribed_servers
                or (org_id and org_id in c.subscribed_orgs)
            ]
        for conn in targets:
            try:
                await conn.websocket.send_text(msg)
            except Exception:
                dead.append(conn)
        for conn in dead:
            await self.disconnect(conn)
```

- [ ] **Step 2: Smoke — import + method exists**

Run:
```bash
docker exec opspilot-backend python -c "from app.ws.manager import ws_manager; assert hasattr(ws_manager,'broadcast_metrics'); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/ws/manager.py
git commit -m "feat(ws): add broadcast_metrics fan-out (server OR org subscribers)"
```

---

## Task 2: `LiveBus` module

**Files:**
- Create: `backend/app/ws/live_bus.py`

- [ ] **Step 1: Create the file**

```python
"""In-process live fan-out bus for metric pushes.

write_metrics() publishes parsed push-rows here; a single background task
(flush_loop, started in the app lifespan) flushes each server's buffer every
500ms and fans the batch out over WebSocket. This module is the single seam to
swap for PostgreSQL LISTEN/NOTIFY if the backend is ever scaled to multiple
worker processes (see PRD §5.4.8)."""
import asyncio
import logging

from app.ws.manager import ws_manager

logger = logging.getLogger(__name__)

FLUSH_INTERVAL_SECONDS = 0.5


class LiveBus:
    def __init__(self) -> None:
        self._buffer: dict[str, list[dict]] = {}
        self._server_org: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def publish(self, server_id: str, org_id: str, rows: list[dict]) -> None:
        """Buffer push-rows for a server. Cheap; safe to call from the ingest path."""
        if not rows:
            return
        async with self._lock:
            self._server_org[server_id] = org_id
            self._buffer.setdefault(server_id, []).extend(rows)

    async def _drain(self) -> dict[str, list[dict]]:
        async with self._lock:
            batch = self._buffer
            self._buffer = {}
            return batch

    async def flush_once(self) -> None:
        batch = await self._drain()
        for server_id, rows in batch.items():
            if not rows:
                continue
            org_id = self._server_org.get(server_id, "")
            payload = {"channel": f"server_metrics:{server_id}", "rows": rows}
            await ws_manager.broadcast_metrics(server_id, org_id, payload)

    async def flush_loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
            try:
                await self.flush_once()
            except Exception:
                logger.exception("live_bus flush failed")


live_bus = LiveBus()
```

- [ ] **Step 2: Smoke — publish then drain returns buffered rows**

Run:
```bash
docker exec opspilot-backend python -c "
import asyncio
from app.ws.live_bus import live_bus
async def main():
    await live_bus.publish('srv-1','org-1',[{'metric_name':'cpu.usage_idle','value':99.0,'labels':{},'time':'2026-06-02T00:00:00+00:00'}])
    batch = await live_bus._drain()
    assert 'srv-1' in batch and len(batch['srv-1'])==1, batch
    assert live_bus._server_org['srv-1']=='org-1'
    print('OK', batch['srv-1'][0]['metric_name'])
asyncio.run(main())
"
```
Expected: `OK cpu.usage_idle`

- [ ] **Step 3: Commit**

```bash
git add backend/app/ws/live_bus.py
git commit -m "feat(ws): add in-process LiveBus with 500ms batched flush"
```

---

## Task 3: Subscribe authorization helpers

**Files:**
- Create: `backend/app/ws/authz.py`

- [ ] **Step 1: Create the file**

```python
"""Authorization helpers for WebSocket subscribe actions.

String IDs from the WS payload / JWT are compared directly against UUID columns,
matching the existing pattern in app/deps.py (asyncpg coerces them)."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.server import Server
from app.models.user import UserOrganization


async def can_access_org(user_role: str, user_id: str, org_id: str, db: AsyncSession) -> bool:
    """Admins see every org; members must have a UserOrganization membership."""
    if user_role == "admin":
        return True
    membership = await db.scalar(
        select(UserOrganization).where(
            UserOrganization.user_id == user_id,
            UserOrganization.org_id == org_id,
        )
    )
    return membership is not None


async def resolve_server_org(server_id: str, db: AsyncSession) -> str | None:
    """Return the org_id (str) of an active server, or None if not found."""
    org_id = await db.scalar(
        select(Server.org_id).where(Server.id == server_id, Server.is_active == True)
    )
    return str(org_id) if org_id else None
```

- [ ] **Step 2: Smoke — admin allowed, lima server resolves to its org**

Run (after the pre-req block so `$SID`/`$ORG` are set):
```bash
docker exec -e SID="$SID" -e ORG="$ORG" opspilot-backend python -c "
import asyncio, os
from app.database import AsyncSessionLocal
from app.ws.authz import can_access_org, resolve_server_org
async def main():
    async with AsyncSessionLocal() as db:
        assert await can_access_org('admin','00000000-0000-0000-0000-000000000000', os.environ['ORG'], db) is True
        org = await resolve_server_org(os.environ['SID'], db)
        assert org == os.environ['ORG'], (org, os.environ['ORG'])
        print('OK', org)
asyncio.run(main())
"
```
Expected: `OK <ORG uuid>`

- [ ] **Step 3: Commit**

```bash
git add backend/app/ws/authz.py
git commit -m "feat(ws): add subscribe authorization helpers"
```

---

## Task 4: Publish metrics from the ingest path

**Files:**
- Modify: `backend/app/services/ingestion.py:114-150`
- Modify: `backend/app/routers/ingest.py` (the `/metrics` handler)

- [ ] **Step 1: Add a module logger import** at the top of `ingestion.py` (below the existing imports, around line 18)

```python
import logging

logger = logging.getLogger(__name__)
```

- [ ] **Step 2: Change `write_metrics` signature + build push-rows + publish.** Replace the function body (lines 114-150) with:

```python
async def write_metrics(server_id: UUID, org_id, line_protocol_body: str, db: AsyncSession) -> int:
    """
    Parse Line Protocol and INSERT one row per numeric field to server_metrics.
    After persisting, publish the same rows to the in-process live bus for WS
    fan-out (additive — must never break ingestion).

    Returns the number of rows inserted.
    """
    rows: list[dict] = []
    push_rows: list[dict] = []
    import json
    for rec in parse_line_protocol(line_protocol_body):
        labels_json = json.dumps(rec["tags"]) if rec["tags"] else None
        for fname, fval in rec["fields"].items():
            if isinstance(fval, bool):
                num = 1.0 if fval else 0.0
            elif isinstance(fval, (int, float)):
                num = float(fval)
            else:
                continue  # skip strings
            metric_name = f"{rec['measurement']}.{fname}"
            rows.append({
                "time": rec["time"],
                "server_id": server_id,
                "metric_name": metric_name,
                "value": num,
                "labels": labels_json,
            })
            push_rows.append({
                "metric_name": metric_name,
                "value": num,
                "labels": rec["tags"] or {},
                "time": rec["time"].isoformat(),
            })

    if not rows:
        return 0

    await db.execute(
        text("""
            INSERT INTO server_metrics (time, server_id, metric_name, value, labels)
            VALUES (:time, :server_id, :metric_name, :value, CAST(:labels AS JSONB))
        """),
        rows,
    )
    await db.commit()

    # Live fan-out — additive; a failure here must not affect ingestion.
    try:
        from app.ws.live_bus import live_bus
        await live_bus.publish(str(server_id), str(org_id), push_rows)
    except Exception:
        logger.exception("live_bus publish failed for server %s", server_id)

    return len(rows)
```

- [ ] **Step 3: Update the `/metrics` handler** in `backend/app/routers/ingest.py` to pass `server.org_id`. Change the `write_metrics` call from:

```python
    count = await write_metrics(server.id, body, db)
```
to:
```python
    count = await write_metrics(server.id, server.org_id, body, db)
```

- [ ] **Step 4: Smoke — metrics still ingest (regression guard)**

Wait ~10s for a Telegraf flush, then confirm rows are still being written and the endpoint returns 200:
```bash
BEFORE=$(docker exec opspilot-postgres psql -U opspilot -d opspilot -tA -c "SELECT count(*) FROM server_metrics WHERE server_id='$SID';")
sleep 12
AFTER=$(docker exec opspilot-postgres psql -U opspilot -d opspilot -tA -c "SELECT count(*) FROM server_metrics WHERE server_id='$SID';")
echo "before=$BEFORE after=$AFTER"; [ "$AFTER" -gt "$BEFORE" ] && echo "INGEST OK" || echo "FAIL: no new rows"
docker logs opspilot-backend --since 20s 2>&1 | grep -iE "live_bus publish failed|Traceback" && echo "FAIL: publish errored" || echo "no publish errors"
```
Expected: `INGEST OK` and `no publish errors`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ingestion.py backend/app/routers/ingest.py
git commit -m "feat(ws): publish parsed metrics to the live bus from write_metrics"
```

---

## Task 5: Start the flush loop + authorize subscribes

**Files:**
- Modify: `backend/app/main.py` (lifespan + WS endpoint)

- [ ] **Step 1: Add imports** near the top of `main.py` (after line 2)

```python
import asyncio
```
and with the other app imports (after line 20):
```python
from app.ws.live_bus import live_bus
from app.ws.authz import can_access_org, resolve_server_org
```

- [ ] **Step 2: Start/stop the flush loop in `lifespan`.** Replace the lifespan body (lines 24-30) with:

```python
async def lifespan(app: FastAPI):
    # Register background jobs
    scheduler.add_job(session_cleanup, "cron", hour=3, minute=0, id="session_cleanup", replace_existing=True)
    scheduler.add_job(ticket_sweep, "interval", seconds=60, id="ticket_sweep", replace_existing=True)
    scheduler.start()
    flush_task = asyncio.create_task(live_bus.flush_loop())
    yield
    flush_task.cancel()
    scheduler.shutdown(wait=False)
```

- [ ] **Step 3: Authorize the subscribe actions.** In the WS endpoint, replace the `subscribe_org` block (lines 121-130, through the end of the `subscribe` block) with:

```python
            if action == "subscribe_org":
                org_id = msg.get("org_id")
                if org_id:
                    async with AsyncSessionLocal() as db:
                        allowed = await can_access_org(user_role, user_id, org_id, db)
                    if allowed:
                        conn.subscribed_orgs.add(org_id)
                    else:
                        await ws.send_text(json.dumps({"error": "forbidden", "channel": f"org:{org_id}"}))

            elif action == "unsubscribe_org":
                org_id = msg.get("org_id")
                if org_id:
                    conn.subscribed_orgs.discard(org_id)

            elif action == "subscribe":
                server_id = msg.get("server_id")
                if server_id:
                    async with AsyncSessionLocal() as db:
                        org_id = await resolve_server_org(server_id, db)
                        allowed = org_id is not None and await can_access_org(user_role, user_id, org_id, db)
                    if allowed:
                        conn.subscribed_servers.add(server_id)
                    else:
                        await ws.send_text(json.dumps({"error": "forbidden", "channel": f"server_metrics:{server_id}"}))
```

(Leave the existing `subscribe_onboarding` / `unsubscribe_onboarding` / `subscribe_rotation` / `unsubscribe` blocks unchanged.)

- [ ] **Step 4: Smoke — backend healthy + flush loop running, no startup errors**

Run:
```bash
sleep 4
curl -s -o /dev/null -w "health %{http_code}\n" http://127.0.0.1:8765/api/health
docker logs opspilot-backend --since 30s 2>&1 | grep -iE "Application startup complete|Traceback|ImportError" | tail -3
```
Expected: `health 200`, an `Application startup complete`, no `Traceback`/`ImportError`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(ws): run live flush loop in lifespan; authorize subscribe actions"
```

---

## Task 6: End-to-end live verification against `lima-ubuntu`

**Files:**
- Create (throwaway, not committed): `/tmp/ws_live_check.py`

- [ ] **Step 1: Write the WS client** to `/tmp/ws_live_check.py`

```python
import asyncio, json, os, httpx, websockets

BASE = "http://localhost:8000"
WS = "ws://localhost:8000/ws"
SID = os.environ["SID"]
ORG = os.environ["ORG"]

async def session_ticket(c):
    await (await c.post("/api/auth/login", json={"username":"smoketest_admin","password":"SmokeTest123!"})).aread()
    return (await c.get("/api/ws-ticket")).json()["ticket"]

async def collect(sub_msg, label):
    async with httpx.AsyncClient(base_url=BASE) as c:
        t = await session_ticket(c)
        async with websockets.connect(f"{WS}?ticket={t}") as ws:
            await ws.send(json.dumps(sub_msg))
            try:
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                    if msg.get("channel","").startswith("server_metrics:"):
                        print(f"  [{label}] batch on {msg['channel']} rows={len(msg['rows'])}")
                        print(f"  [{label}] sample={msg['rows'][0]}")
                        return len(msg["rows"])
                    if msg.get("error"):
                        print(f"  [{label}] {msg}")
                        return msg
            except asyncio.TimeoutError:
                print(f"  [{label}] TIMEOUT (no batch)"); return None

async def main():
    print("1) subscribe by SERVER")
    n1 = await collect({"action":"subscribe","server_id":SID}, "server")
    print("2) subscribe by ORG")
    n2 = await collect({"action":"subscribe_org","org_id":ORG}, "org")
    print("3) batching: a single batch should carry many rows")
    print(f"   server batch rows={n1}  (expect > 1, coalesced)")
    assert isinstance(n1,int) and n1 > 1, "expected a coalesced multi-row batch"
    assert isinstance(n2,int) and n2 > 1, "org channel should receive the batch too"
    print("DONE_OK")

asyncio.run(main())
```

- [ ] **Step 2: Run it inside the backend container**

```bash
docker cp /tmp/ws_live_check.py opspilot-backend:/tmp/ws_live_check.py
docker exec -e SID="$SID" -e ORG="$ORG" opspilot-backend python /tmp/ws_live_check.py
```
Expected: a `[server]` batch line with `rows=<many>`, a `[org]` batch line, and `DONE_OK` within ~10-15s (next Telegraf flush).

- [ ] **Step 3: Authorization smoke — a non-member member cannot subscribe**

```bash
# create a member with NO org membership
docker exec opspilot-postgres psql -U opspilot -d opspilot -q -c \
"INSERT INTO \"user\" (id, username, password_hash, role) VALUES (gen_random_uuid(),'smoketest_member','\$2b\$12\$5FtoMstccMPVWSs7us0S1Oj2qMXxOqQ4BuEzN9wjjgsxpO1yGoxV2','member') ON CONFLICT (username) DO UPDATE SET password_hash=EXCLUDED.password_hash, role='member';"
docker cp /tmp/ws_live_check.py opspilot-backend:/tmp/ws_live_check.py
docker exec -e SID="$SID" -e ORG="$ORG" opspilot-backend python -c "
import asyncio, json, os, httpx, websockets
async def main():
    async with httpx.AsyncClient(base_url='http://localhost:8000') as c:
        await (await c.post('/api/auth/login', json={'username':'smoketest_member','password':'SmokeTest123!'})).aread()
        t=(await c.get('/api/ws-ticket')).json()['ticket']
        async with websockets.connect(f'ws://localhost:8000/ws?ticket={t}') as ws:
            await ws.send(json.dumps({'action':'subscribe','server_id':os.environ['SID']}))
            msg=json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            assert msg.get('error')=='forbidden', msg
            print('FORBIDDEN OK', msg)
asyncio.run(main())
"
docker exec opspilot-postgres psql -U opspilot -d opspilot -q -c "DELETE FROM \"user\" WHERE username='smoketest_member';"
```
Expected: `FORBIDDEN OK {...'error': 'forbidden'...}` (member with no membership is denied and gets the frame).

- [ ] **Step 4: No commit** (verification only — nothing to commit here).

---

## Task 7: Update progress dashboard, clean up, final commit

**Files:**
- Modify: `pm/PROGRESS.md`
- Modify: `pm/DASHBOARD.html`

- [ ] **Step 1: Flip the WS-infra tasks** in `pm/PROGRESS.md` (Phase 2 → WebSocket Infrastructure). Change these four `⬜` to `✅` (the metric mechanism line wording is now in-process fan-out):

```
- ✅ PostgreSQL LISTEN/NOTIFY → FastAPI WS fan-out  *(implemented as in-process live bus — see PRD §5.4.8)*
- ✅ 500ms event batching before WS push
- ✅ WS channel authorization per subscribe message
- ✅ subscribe_org / subscribe (server) / unsubscribe actions
```
Leave `⬜ Smoke test: open dashboard, verify live metric updates arrive` pending — it needs the dashboard UI (next slice); live delivery itself was verified by the Task 6 WS client.

- [ ] **Step 2: Update the Phase 2 summary count** in `pm/PROGRESS.md` (`0 / 20` → `4 / 20`) and the Total (`60 / 191` → `64 / 191`).

- [ ] **Step 3: Flip the matching entries** in `pm/DASHBOARD.html` — set `status: 'pending'` → `status: 'done'` for the same four tasks (search each task's text string). Leave the dashboard smoke-test entry pending.

- [ ] **Step 4: Clean up the throwaway admin**

```bash
docker exec opspilot-postgres psql -U opspilot -d opspilot -q -c "
DELETE FROM session WHERE user_id=(SELECT id FROM \"user\" WHERE username='smoketest_admin');
DELETE FROM \"user\" WHERE username IN ('smoketest_admin','smoketest_member');"
docker exec opspilot-postgres psql -U opspilot -d opspilot -c "SELECT username, role FROM \"user\";"
```
Expected: only the original `admin` remains.

- [ ] **Step 5: Commit + push**

```bash
git add backend/app/ws/ backend/app/services/ingestion.py backend/app/routers/ingest.py backend/app/main.py pm/PROGRESS.md pm/DASHBOARD.html
git commit -m "feat(ws): live metric fan-out infrastructure (Phase 2 slice 1)

In-process LiveBus + 500ms batched flush, broadcast_metrics fan-out to
server/org subscribers, and authorized subscribe actions. Verified live on
lima-ubuntu: server + org channels receive coalesced metric batches; a member
without org membership is denied with a forbidden frame.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git push origin main
```

---

## Self-review notes

- **Spec coverage:** LiveBus + flush (Task 2), `write_metrics` hook (Task 4), `broadcast_metrics` server/org fan-out (Task 1), subscribe authorization + `unsubscribe_org` (Task 5), lifespan flush task (Task 5), live/auth/batching verification (Task 6). All §3 components and §5 verification items covered.
- **Type consistency:** `write_metrics(server_id, org_id, body, db)` defined in Task 4 and called that way in the Task 4 ingest-router step; `live_bus.publish(str(server_id), str(org_id), push_rows)` matches `publish(server_id, org_id, rows)` in Task 2; `broadcast_metrics(server_id, org_id, payload)` matches its definition (Task 1) and call site (Task 2); `can_access_org`/`resolve_server_org` signatures match between Task 3 and Task 5.
- **No placeholders:** every code/command step is concrete.
- **Out of scope (next slices):** dashboard UI, REST summary endpoints, log live tail, alert events.
