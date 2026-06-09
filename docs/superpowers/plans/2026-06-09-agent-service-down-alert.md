# Agent Service Down Alert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fire a `critical` alert when the OpsPilot agent reports a local service (e.g. MySQL) as `stopped`, and resolve it when the service returns to `running`.

**Architecture:** Inline evaluation added to `ingest_heartbeat` — after storing rows, iterate services and call `fire_alert`/`resolve_alert` from the existing alerting seam. Alert type `agent_service_down:{service_name}` encodes the service name so dedup works per `(type, server_id)` with no schema changes.

**Tech Stack:** Python/FastAPI, SQLAlchemy async, existing `app.services.alerting`

---

### Task 1: Add alert evaluation to heartbeat ingest

**Files:**
- Modify: `backend/app/routers/ingest.py`

- [ ] **Step 1: Add imports to ingest.py**

At the top of `backend/app/routers/ingest.py`, add to the existing imports:

```python
from sqlalchemy import and_, select, text
```

Replace the existing `from sqlalchemy import select, text` line with the above (add `and_`).

Also add:

```python
from app.models.other import Alert
from app.services.alerting import OPEN_STATES, fire_alert, resolve_alert
```

- [ ] **Step 2: Add `_evaluate_agent_services` helper above the heartbeat handler**

Insert this function above the `@router.post("/heartbeat")` line:

```python
async def _evaluate_agent_services(
    db: AsyncSession, server_id, server_name: str, services: list[_ServiceMetric]
) -> None:
    """Fire/resolve agent_service_down alerts based on heartbeat service statuses."""
    for svc in services:
        alert_type = f"agent_service_down:{svc.name}"
        if svc.status == "stopped":
            await fire_alert(
                db,
                type=alert_type,
                severity="critical",
                message=f"Service {svc.name} is down (reported by OpsPilot agent)",
                server_id=server_id,
                cooldown_min=60,
                commit=False,
            )
        elif svc.status == "running":
            open_alert = (
                await db.execute(
                    select(Alert).where(
                        and_(
                            Alert.type == alert_type,
                            Alert.server_id == server_id,
                            Alert.state.in_(OPEN_STATES),
                        )
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if open_alert:
                await resolve_alert(db, open_alert, commit=False)
```

- [ ] **Step 3: Call `_evaluate_agent_services` in `ingest_heartbeat`**

Replace the current heartbeat handler body:

```python
@router.post("/heartbeat")
async def ingest_heartbeat(
    payload: _HeartbeatPayload,
    server: Annotated[Server, Depends(_authenticated_server)],
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    server.last_seen_at = now
    row_count = 0
    if payload.services:
        rows = [
            {
                "ts": now,
                "sid": server.id,
                "sname": s.name,
                "status": s.status,
                "cpu_pct": s.cpu_pct,
                "mem_mb": s.mem_mb,
                "uptime_seconds": s.uptime_seconds,
            }
            for s in payload.services
        ]
        await db.execute(
            text("""
                INSERT INTO server_service_metrics
                    (time, server_id, service_name, status, cpu_pct, mem_mb, uptime_seconds)
                VALUES
                    (:ts, :sid, :sname, :status, :cpu_pct, :mem_mb, :uptime_seconds)
            """),
            rows,
        )
        row_count = len(rows)
        await _evaluate_agent_services(db, server.id, server.name, payload.services)
    await db.commit()
    return {"ok": True, "rows": row_count}
```

- [ ] **Step 4: Smoke test — stopped service fires alert**

```bash
# Get a server's ingestion token from the DB
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres \
  psql -U opspilot -d opspilot -c "SELECT name, ingestion_token FROM server LIMIT 3;"

# Send a heartbeat with a stopped service
curl -s -X POST http://localhost:9090/api/ingest/heartbeat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"services": [{"name": "mysql", "status": "stopped"}]}'
# Expected: {"ok": true, "rows": 1}

# Verify alert was created
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres \
  psql -U opspilot -d opspilot -c \
  "SELECT type, severity, message, state FROM alert WHERE type LIKE 'agent_service_down%' ORDER BY sent_at DESC LIMIT 5;"
# Expected: row with type='agent_service_down:mysql', severity='critical', state='firing'
```

- [ ] **Step 5: Smoke test — running service resolves alert**

```bash
curl -s -X POST http://localhost:9090/api/ingest/heartbeat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"services": [{"name": "mysql", "status": "running"}]}'
# Expected: {"ok": true, "rows": 1}

docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres \
  psql -U opspilot -d opspilot -c \
  "SELECT type, state, resolved_at FROM alert WHERE type = 'agent_service_down:mysql' ORDER BY sent_at DESC LIMIT 1;"
# Expected: state='resolved', resolved_at IS NOT NULL
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/ingest.py
git commit -m "feat: fire alert when agent-reported service goes down"
git push origin main
```
