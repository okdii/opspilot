# Multi-DB Instance Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow a single OpsPilot server to monitor multiple database instances (e.g. MySQL on :3306 and MySQL on :3307) by supporting N credentials per server, labelled instances, per-instance metric filtering, and a pill-tab UI within the database dashboard.

**Architecture:** Add a `label` column to `db_credential`, remove the LIMIT 1 single-credential enforcement throughout the backend, inject a `db_label` Telegraf tag per instance so metrics in `server_metrics.labels` stay distinguishable, and thread `credential_id` through all metric query endpoints. The frontend adds an instance pill bar between the server tabs and dashboard.

**Tech Stack:** Python/FastAPI (SQLAlchemy async, Alembic), Jinja2 (Telegraf template), Vue 3 + Pinia (TypeScript)

---

## File Map

| File | Change |
|------|--------|
| `backend/migrations/versions/0014_db_credential_label.py` | **Create** — Alembic migration adding `label` column |
| `backend/app/models/other.py` | **Modify** — add `label` field to `DBCredential` |
| `backend/app/routers/databases.py` | **Modify** — schemas, helpers, all endpoints |
| `backend/app/services/templates/telegraf.conf.j2` | **Modify** — replace single DSN blocks with loop |
| `backend/app/services/onboarding.py` | **Modify** — replace `_build_mysql_dsn`/`_build_pg_dsn` with `_build_db_instances` |
| `frontend/src/stores/databases.ts` | **Modify** — new types, updated actions |
| `frontend/src/views/databases/DatabasesView.vue` | **Modify** — instance pill bar, selectedInstanceId |
| `frontend/src/components/databases/DbCredentialModal.vue` | **Modify** — label field, updated props |
| `frontend/src/components/databases/DbHealthDashboard.vue` | **Modify** — credentialId prop, pass to all fetches |

---

### Task 1: DB Migration — add `label` column

**Files:**
- Create: `backend/migrations/versions/0014_db_credential_label.py`

- [ ] **Step 1: Create the migration file**

```python
# backend/migrations/versions/0014_db_credential_label.py
"""Add label column to db_credential table.

Revision ID: 0014_db_credential_label
Revises: 0013_db_credential_db_type
"""
import sqlalchemy as sa
from alembic import op

revision = "0014_db_credential_label"
down_revision = "0013_db_credential_db_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("db_credential", sa.Column("label", sa.String(60), nullable=True))


def downgrade() -> None:
    op.drop_column("db_credential", "label")
```

- [ ] **Step 2: Run the migration inside the backend container**

```bash
docker exec opspilot-backend alembic upgrade head
```

Expected output contains: `Running upgrade 0013_db_credential_db_type -> 0014_db_credential_label`

- [ ] **Step 3: Verify column exists**

```bash
docker exec opspilot-postgres psql -U opspilot -d opspilot \
  -c "\d db_credential" | grep label
```

Expected: `label | character varying(60) | | |`

- [ ] **Step 4: Commit**

```bash
git add backend/migrations/versions/0014_db_credential_label.py
git commit -m "feat(db): migration 0014 — add label column to db_credential"
```

---

### Task 2: Backend — model field + schemas + `_resolve_label` helper

**Files:**
- Modify: `backend/app/models/other.py`
- Modify: `backend/app/routers/databases.py`

- [ ] **Step 1: Add `label` field to `DBCredential` model**

In `backend/app/models/other.py`, find the `DBCredential` class and add after `db_type`:

```python
    label: Mapped[str | None] = mapped_column(String(60), nullable=True)
```

The full class after the change:
```python
class DBCredential(Base):
    __tablename__ = "db_credential"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("server.id", ondelete="CASCADE"), nullable=False, index=True)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=3306)
    username: Mapped[str] = mapped_column(String(80), nullable=False)
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    is_replica: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    db_type: Mapped[str] = mapped_column(String(16), nullable=False, default="mysql", server_default="mysql")
    last_deadlock_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label: Mapped[str | None] = mapped_column(String(60), nullable=True)

    server: Mapped["Server"] = relationship(back_populates="db_credentials")
```

- [ ] **Step 2: Update `DBCredentialIn` and `DBCredentialPatch` schemas**

In `backend/app/routers/databases.py`, replace both schema classes:

```python
class DBCredentialIn(BaseModel):
    host: str = Field(default="127.0.0.1", min_length=1, max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    username: str = Field(default="opspilot_monitor", min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=255)
    is_replica: bool = False
    db_type: str = Field(default="mysql", pattern="^(mysql|postgres)$")
    label: str | None = Field(default=None, max_length=60)


class DBCredentialPatch(BaseModel):
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, min_length=1, max_length=80)
    password: str | None = Field(default=None, max_length=255)
    is_replica: bool | None = None
    db_type: str | None = Field(default=None, pattern="^(mysql|postgres)$")
    label: str | None = Field(default=None, max_length=60)
```

- [ ] **Step 3: Add `_resolve_label` and `_get_credential_by_id` helpers**

In `backend/app/routers/databases.py`, replace the existing `_get_credential` helper block with:

```python
async def _get_credential(server_id: str, db: AsyncSession) -> DBCredential | None:
    return await db.scalar(
        select(DBCredential).where(DBCredential.server_id == server_id).limit(1)
    )


async def _get_credential_by_id(credential_id: str, server_id: str, db: AsyncSession) -> DBCredential:
    cred = await db.scalar(
        select(DBCredential).where(
            DBCredential.id == credential_id,
            DBCredential.server_id == server_id,
        )
    )
    if cred is None:
        raise HTTPException(
            404,
            detail={"error": "not_found", "message": "DB credential not found."},
        )
    return cred


def _resolve_label(cred: DBCredential) -> str:
    return cred.label or f"{cred.db_type}:{cred.port}"
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/other.py backend/app/routers/databases.py
git commit -m "feat(db): add label field to DBCredential model and schemas"
```

---

### Task 3: Backend — grouped list endpoint + updated `_last_check`

**Files:**
- Modify: `backend/app/routers/databases.py`

- [ ] **Step 1: Update `_last_check` to filter by label and db_type**

Replace the existing `_last_check` function:

```python
async def _last_check(
    db: AsyncSession, server_id: str, label: str, db_type: str
) -> tuple[bool | None, datetime | None]:
    """Best-effort connection health filtered by instance label.
    Falls back to unlabelled metrics for backward compat with pre-migration data."""
    prefix = "postgresql" if db_type == "postgres" else "mysql"
    row = (
        await db.execute(
            text(
                """
                SELECT MAX(time) AS last_t
                FROM server_metrics
                WHERE server_id = :sid
                  AND metric_name LIKE :prefix
                  AND (labels->>'db_label' = :label OR labels->>'db_label' IS NULL)
                """
            ),
            {"sid": str(server_id), "prefix": f"{prefix}.%", "label": label},
        )
    ).first()
    last_t = row.last_t if row else None
    if last_t is None:
        return None, None
    if last_t.tzinfo is None:
        last_t = last_t.replace(tzinfo=timezone.utc)
    ok = (datetime.now(timezone.utc) - last_t).total_seconds() <= 120
    return ok, last_t
```

- [ ] **Step 2: Replace `list_db_credentials` with grouped response**

Replace the entire `list_db_credentials` function:

```python
@router.get("/api/organizations/{org_id}/db-credentials")
async def list_db_credentials(org_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """One entry per active server; each entry has an `instances` array.
    No passwords are returned."""
    await _assert_org_access(org_id, user, db)

    servers = (
        await db.execute(
            select(Server)
            .where(Server.org_id == org_id, Server.is_active == True)  # noqa: E712
            .order_by(Server.name)
        )
    ).scalars().all()

    out: list[dict] = []
    for s in servers:
        creds = (
            await db.execute(
                select(DBCredential)
                .where(DBCredential.server_id == s.id)
                .order_by(DBCredential.id)
            )
        ).scalars().all()

        instances: list[dict] = []
        for cred in creds:
            label = _resolve_label(cred)
            last_ok, last_checked = await _last_check(db, str(s.id), label, cred.db_type)
            instances.append(
                {
                    "credential_id": str(cred.id),
                    "label": label,
                    "host": cred.host,
                    "port": cred.port,
                    "username": cred.username,
                    "is_replica": cred.is_replica,
                    "db_type": cred.db_type,
                    "last_check_ok": last_ok,
                    "last_checked": last_checked.isoformat() if last_checked else None,
                }
            )

        out.append(
            {
                "server_id": str(s.id),
                "server_name": s.name,
                "instances": instances,
            }
        )
    return out
```

- [ ] **Step 3: Verify the endpoint returns the new shape**

```bash
# Get a bearer token first — replace TOKEN with a valid session token
curl -s http://localhost:9090/api/organizations/$(
  docker exec opspilot-backend python3 -c "
import asyncio
from app.database import AsyncSessionLocal
from sqlalchemy import text
async def g():
    async with AsyncSessionLocal() as db:
        r = await db.execute(text('SELECT org_id FROM server LIMIT 1'))
        print(r.scalar())
asyncio.run(g())
" 2>/dev/null | tail -1)/db-credentials \
  -H "Authorization: Bearer TOKEN" | python3 -m json.tool | head -30
```

Expected: JSON with `[{"server_id": "...", "server_name": "...", "instances": [...]}]`

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/databases.py
git commit -m "feat(db): grouped list endpoint and label-filtered _last_check"
```

---

### Task 4: Backend — CRUD endpoints with `credential_id`

**Files:**
- Modify: `backend/app/routers/databases.py`

- [ ] **Step 1: Update `create_db_credentials` — remove the "already configured" guard and store label**

Replace the existing `create_db_credentials` function:

```python
@router.post("/api/servers/{server_id}/db-credentials", status_code=201)
async def create_db_credentials(
    server_id: str, body: DBCredentialIn, user: AdminUser, db: AsyncSession = Depends(get_db)
):
    server = await db.scalar(
        select(Server).where(Server.id == server_id, Server.is_active == True)  # noqa: E712
    )
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})

    cred = DBCredential(
        server_id=server_id,
        host=body.host,
        port=body.port,
        username=body.username,
        password_encrypted=encrypt(body.password),
        is_replica=body.is_replica,
        db_type=body.db_type,
        label=body.label or None,
    )
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    _trigger_redeploy(server_id)
    return {
        "credential_id": str(cred.id),
        "server_id": str(server_id),
        "label": _resolve_label(cred),
        "host": cred.host,
        "port": cred.port,
        "username": cred.username,
        "is_replica": cred.is_replica,
        "has_credentials": True,
        "redeploy_queued": True,
    }
```

- [ ] **Step 2: Update `update_db_credentials` — add `credential_id` path param and label support**

Replace the existing `update_db_credentials` function:

```python
@router.patch("/api/servers/{server_id}/db-credentials/{credential_id}")
async def update_db_credentials(
    server_id: str,
    credential_id: str,
    body: DBCredentialPatch,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    server = await db.scalar(
        select(Server).where(Server.id == server_id, Server.is_active == True)  # noqa: E712
    )
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})

    cred = await _get_credential_by_id(credential_id, server_id, db)

    config_changed = False
    if body.host is not None and body.host != cred.host:
        cred.host = body.host
        config_changed = True
    if body.port is not None and body.port != cred.port:
        cred.port = body.port
        config_changed = True
    if body.username is not None and body.username != cred.username:
        cred.username = body.username
        config_changed = True
    if body.is_replica is not None and body.is_replica != cred.is_replica:
        cred.is_replica = body.is_replica
        config_changed = True
    if body.db_type is not None and body.db_type != cred.db_type:
        cred.db_type = body.db_type
        config_changed = True
    if body.label is not None:
        cred.label = body.label or None
    if body.password:
        cred.password_encrypted = encrypt(body.password)
        config_changed = True

    await db.commit()
    await db.refresh(cred)

    redeploy_queued = _trigger_redeploy(server_id) if config_changed else False
    return {
        "credential_id": str(cred.id),
        "server_id": str(server_id),
        "label": _resolve_label(cred),
        "host": cred.host,
        "port": cred.port,
        "username": cred.username,
        "is_replica": cred.is_replica,
        "has_credentials": True,
        "redeploy_queued": redeploy_queued,
    }
```

- [ ] **Step 3: Update `delete_db_credentials` — add `credential_id` path param**

Replace the existing `delete_db_credentials` function:

```python
@router.delete("/api/servers/{server_id}/db-credentials/{credential_id}", status_code=200)
async def delete_db_credentials(
    server_id: str, credential_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)
):
    server = await db.scalar(
        select(Server).where(Server.id == server_id, Server.is_active == True)  # noqa: E712
    )
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})

    cred = await _get_credential_by_id(credential_id, server_id, db)
    await db.delete(cred)
    await db.commit()
    _trigger_redeploy(server_id)
    return {"ok": True, "redeploy_queued": True}
```

- [ ] **Step 4: Update `get_db_credential_password` — add `credential_id` path param**

Replace the existing `get_db_credential_password` function:

```python
@router.get("/api/servers/{server_id}/db-credentials/{credential_id}/password")
async def get_db_credential_password(
    server_id: str, credential_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)
):
    """Return the decrypted monitoring-user password for admins who need to retrieve it."""
    cred = await _get_credential_by_id(credential_id, server_id, db)
    return {"password": decrypt(cred.password_encrypted)}
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/databases.py
git commit -m "feat(db): CRUD endpoints accept credential_id; POST allows multiple per server"
```

---

### Task 5: Backend — metric helpers with `db_label` filtering

**Files:**
- Modify: `backend/app/routers/databases.py`

- [ ] **Step 1: Update `_rate_latest` to accept `db_label`**

Replace the existing `_rate_latest` function:

```python
async def _rate_latest(
    db: AsyncSession, server_id: str, stored: str, *, per: str, db_label: str = ""
) -> float | None:
    """Per-second or per-minute rate from the two most recent counter samples.
    db_label filters to a specific instance; empty string matches all (including unlabelled)."""
    label_clause = (
        "AND (labels->>'db_label' = :label OR labels->>'db_label' IS NULL)"
        if db_label else ""
    )
    rows = (
        await db.execute(
            text(
                f"""
                SELECT value, time
                FROM server_metrics
                WHERE server_id = :sid AND metric_name = :m
                  AND time >= now() - INTERVAL '10 minutes'
                  {label_clause}
                ORDER BY time DESC
                LIMIT 2
                """
            ),
            {"sid": str(server_id), "m": stored, "label": db_label},
        )
    ).all()
    if len(rows) < 2:
        return None
    cur_v, cur_t = rows[0]
    prev_v, prev_t = rows[1]
    if cur_v is None or prev_v is None:
        return None
    dt = (cur_t - prev_t).total_seconds()
    if dt <= 0:
        return None
    delta = float(cur_v) - float(prev_v)
    if delta < 0:
        return None
    rate_per_sec = delta / dt
    return round(rate_per_sec * (60 if per == "min" else 1), 2)
```

- [ ] **Step 2: Update `_pg_tuple_ops_rate` to accept `db_label`**

Replace the existing `_pg_tuple_ops_rate` function:

```python
async def _pg_tuple_ops_rate(db: AsyncSession, server_id: str, db_label: str = "") -> float | None:
    """Sum of insert+update+delete rates (per sec) for PostgreSQL tuple operations."""
    ins = await _rate_latest(db, server_id, "postgresql.tup_inserted", per="sec", db_label=db_label)
    upd = await _rate_latest(db, server_id, "postgresql.tup_updated", per="sec", db_label=db_label)
    dlt = await _rate_latest(db, server_id, "postgresql.tup_deleted", per="sec", db_label=db_label)
    parts = [v for v in [ins, upd, dlt] if v is not None]
    return round(sum(parts), 2) if parts else None
```

- [ ] **Step 3: Update `_series` to accept `db_label`**

Replace the existing `_series` function:

```python
async def _series(
    db: AsyncSession,
    server_id: str,
    stored: str,
    source: str,
    valcol: str,
    timecol: str,
    interval: str,
    is_rate: bool,
    *,
    db_label: str = "",
) -> list[dict]:
    label_clause = (
        "AND (labels->>'db_label' = :label OR labels->>'db_label' IS NULL)"
        if db_label else ""
    )
    rows = (
        await db.execute(
            text(
                f"""
                SELECT {timecol} AS t, {valcol} AS v
                FROM {source}
                WHERE server_id = :sid AND metric_name = :m
                  AND {timecol} >= now() - INTERVAL '{interval}'
                  {label_clause}
                ORDER BY {timecol} ASC
                """
            ),
            {"sid": str(server_id), "m": stored, "label": db_label},
        )
    ).all()
    pts = [{"time": t, "value": float(v) if v is not None else None, "_t": t} for t, v in rows]

    if is_rate:
        clean = [p for p in pts if p["value"] is not None]
        out: list[dict] = []
        for prev, cur in zip(clean, clean[1:]):
            dt = (cur["_t"] - prev["_t"]).total_seconds()
            if dt <= 0:
                continue
            delta = cur["value"] - prev["value"]
            if delta < 0:
                continue
            out.append({"time": cur["_t"].isoformat(), "value": round(delta / dt, 4)})
        return out

    return [{"time": p["_t"].isoformat(), "value": p["value"]} for p in pts]
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/databases.py
git commit -m "feat(db): add db_label filtering to _rate_latest, _pg_tuple_ops_rate, _series"
```

---

### Task 6: Backend — metric endpoints accept `credential_id`

**Files:**
- Modify: `backend/app/routers/databases.py`

- [ ] **Step 1: Update `get_db_metrics_latest` to accept `credential_id` and filter metrics**

Replace the entire `get_db_metrics_latest` function:

```python
@router.get("/api/servers/{server_id}/db-metrics/latest")
async def get_db_metrics_latest(
    server_id: str,
    credential_id: str = Query(...),
    user: CurrentUser = Depends(lambda: None),
    db: AsyncSession = Depends(get_db),
):
    """Latest DB metric values for the stat cards. Filtered to the given credential instance."""
    await _assert_server_access(server_id, user, db)

    cred = await _get_credential_by_id(credential_id, server_id, db)
    label = _resolve_label(cred)
    is_pg = cred.db_type == "postgres"

    rows = (
        await db.execute(
            text(
                """
                SELECT DISTINCT ON (metric_name) metric_name, value, time
                FROM server_metrics
                WHERE server_id = :sid
                  AND (metric_name LIKE 'mysql.%' OR metric_name LIKE 'mariadb.%' OR metric_name LIKE 'postgresql.%')
                  AND time >= now() - INTERVAL '10 minutes'
                  AND (labels->>'db_label' = :label OR labels->>'db_label' IS NULL)
                ORDER BY metric_name, time DESC
                """
            ),
            {"sid": str(server_id), "label": label},
        )
    ).all()
    latest: dict[str, float] = {m: float(v) for m, v, _ in rows if v is not None}
    last_t = max((t for _, _, t in rows), default=None)

    def _val(stored: str) -> float | None:
        v = latest.get(stored)
        return v if v is not None else None

    if is_pg:
        return {
            "connections_active":   _val("postgresql.numbackends"),
            "connections_max":      None,
            "queries_per_sec":      None,
            "slow_queries_per_min": None,
            "innodb_buffer_pool_hit_rate": None,
            "innodb_deadlocks":     None,
            "transactions_per_sec": await _rate_latest(db, server_id, "postgresql.xact_commit", per="sec", db_label=label),
            "cache_hit_rate":       _val("postgresql.blks_hit_rate"),
            "deadlocks":            await _rate_latest(db, server_id, "postgresql.deadlocks", per="sec", db_label=label),
            "tuple_ops_per_sec":    await _pg_tuple_ops_rate(db, server_id, db_label=label),
            "temp_files_per_min":   await _rate_latest(db, server_id, "postgresql.temp_files", per="min", db_label=label),
            "checkpoints_per_min":  await _rate_latest(db, server_id, "postgresql.checkpoints_timed", per="min", db_label=label),
            "replication_lag_sec":  _val("postgresql.replication_delay") if cred.is_replica else None,
            "replication_running":  None,
            "mariadb_version":      None,
            "last_collected_at":    last_t.isoformat() if last_t else None,
        }

    qps = await _rate_latest(db, server_id, "mysql.queries", per="sec", db_label=label)
    slow_pm = await _rate_latest(db, server_id, "mysql.slow_queries", per="min", db_label=label)

    return {
        "connections_active":         _val("mysql.threads_connected"),
        "connections_max":            _val(_MAX_CONNECTIONS_METRIC),
        "queries_per_sec":            qps,
        "slow_queries_per_min":       slow_pm,
        "innodb_buffer_pool_hit_rate": _val("mysql.innodb_buffer_pool_hit_rate"),
        "innodb_deadlocks":           _val("mysql.innodb_deadlocks"),
        "replication_lag_sec":        _val("mariadb.seconds_behind_master") if cred.is_replica else None,
        "replication_running": (
            bool(_val("mariadb.replication_running"))
            if (cred.is_replica and _val("mariadb.replication_running") is not None)
            else None
        ),
        "table_locks_waited":  _val("mysql.table_locks_waited"),
        "aborted_connections": _val("mysql.aborted_connects"),
        "deadlocks":           None,
        "transactions_per_sec": None,
        "cache_hit_rate":      None,
        "tuple_ops_per_sec":   None,
        "temp_files_per_min":  None,
        "checkpoints_per_min": None,
        "mariadb_version":     None,
        "last_collected_at":   last_t.isoformat() if last_t else None,
    }
```

Note: The `user` dependency injection line above needs the correct FastAPI pattern. Replace `user: CurrentUser = Depends(lambda: None)` with the existing import style — check the file for the exact `CurrentUser` dependency and use it unchanged.

- [ ] **Step 2: Update `get_db_metrics` (series) to accept `credential_id`**

Replace the existing `get_db_metrics` function:

```python
@router.get("/api/servers/{server_id}/db-metrics")
async def get_db_metrics(
    server_id: str,
    credential_id: str = Query(...),
    metric: str = Query(...),
    range: str = Query("1h"),
    user: CurrentUser = Depends(lambda: None),
    db: AsyncSession = Depends(get_db),
):
    """Time-series chart data for one DB metric over a range. Filtered to credential instance."""
    await _assert_server_access(server_id, user, db)

    cred = await _get_credential_by_id(credential_id, server_id, db)
    label = _resolve_label(cred)
    metric_map = _PG_METRIC_MAP if cred.db_type == "postgres" else _METRIC_MAP

    if metric not in metric_map:
        raise HTTPException(
            400, detail={"error": "invalid_metric", "message": f"Unsupported metric: {metric}"}
        )
    if range not in RANGE_SOURCE:
        raise HTTPException(
            400, detail={"error": "invalid_range", "message": f"Invalid range: {range}"}
        )

    stored, is_rate = metric_map[metric]
    source, valcol, timecol, resolution = RANGE_SOURCE[range]
    interval = RANGE_INTERVAL[range]

    pts = await _series(db, server_id, stored, source, valcol, timecol, interval, is_rate, db_label=label)

    result: dict = {"metric": metric, "range": range, "resolution": resolution, "data": pts}

    if metric == "connections_active" and cred.db_type != "postgres":
        max_pts = await _series(
            db, server_id, _MAX_CONNECTIONS_METRIC, source, valcol, timecol, interval, False, db_label=label
        )
        result["connections_max"] = max_pts[-1]["value"] if max_pts else None

    return result
```

Again, replace the `user` dependency with the correct `CurrentUser` import as it appears elsewhere in the file.

- [ ] **Step 3: Fix `user` dependency in both new endpoints**

The two functions above use a placeholder for `user`. Open `backend/app/routers/databases.py` and find the correct pattern used by other endpoints, e.g.:

```python
async def get_db_metrics_latest(
    server_id: str,
    credential_id: str = Query(...),
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
```

`CurrentUser` is already imported at the top of the file and works as a FastAPI dependency — keep it as-is from the existing endpoints (no `Depends()` wrapper needed if it's already typed as a dependency type).

- [ ] **Step 4: Restart the backend and verify no import errors**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart backend
sleep 3
docker logs opspilot-backend 2>&1 | tail -10
```

Expected: no `ImportError` or `AttributeError`; uvicorn shows "Application startup complete."

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/databases.py
git commit -m "feat(db): metric endpoints accept credential_id query param for instance filtering"
```

---

### Task 7: Telegraf template + onboarding service

**Files:**
- Modify: `backend/app/services/templates/telegraf.conf.j2`
- Modify: `backend/app/services/onboarding.py`

- [ ] **Step 1: Replace single-DSN blocks in telegraf.conf.j2 with a loop**

Open `backend/app/services/templates/telegraf.conf.j2`. Find and replace the entire section from `{% if mysql_dsn %}` through the end of the `{% if pg_dsn %}` block (including the closing `{% endif %}`). Replace it with:

```jinja2
{% for inst in db_instances %}
{% if inst.db_type == 'mysql' %}
# ── MySQL input: {{ inst.label }} ────────────────────────────────────────────
[[inputs.mysql]]
  servers = ["{{ inst.dsn }}"]
  perf_events_statements_digest_text_limit = 120
  perf_events_statements_limit            = 250
  perf_events_statements_time_limit       = 86400
  table_schema_databases                  = []
  gather_slave_status                     = true
  gather_table_io_waits                   = false
  gather_table_lock_waits                 = false
  gather_index_io_waits                   = false
  gather_event_waits                      = false
  gather_file_events_stats                = false
  gather_perf_events_statements           = false
  [inputs.mysql.tags]
    db_label = "{{ inst.label }}"

{% elif inst.db_type == 'postgres' %}
# ── PostgreSQL input: {{ inst.label }} ─────────────────────────────────────
[[inputs.postgresql]]
  address = "{{ inst.dsn }}"
  [inputs.postgresql.tags]
    db_label = "{{ inst.label }}"

{% endif %}
{% endfor %}
```

- [ ] **Step 2: Add `_build_db_instances` to onboarding.py**

In `backend/app/services/onboarding.py`, add after the existing `_build_pg_dsn` function:

```python
async def _build_db_instances(db, server) -> list[dict]:
    """Return [{label, dsn, db_type}] for every DBCredential on this server."""
    from app.core.crypto import decrypt
    creds = (
        await db.execute(select(DBCredential).where(DBCredential.server_id == server.id))
    ).scalars().all()
    instances = []
    for cred in creds:
        label = cred.label or f"{cred.db_type}:{cred.port}"
        password = decrypt(cred.password_encrypted)
        if cred.db_type == "postgres":
            dsn = f"postgres://{cred.username}:{password}@{cred.host}:{cred.port}/postgres?sslmode=disable"
        else:
            dsn = f"{cred.username}:{password}@tcp({cred.host}:{cred.port})/?tls=false"
        instances.append({"label": label, "dsn": dsn, "db_type": cred.db_type})
    return instances
```

- [ ] **Step 3: Update `_step_configure_telegraf` signature**

In `backend/app/services/onboarding.py`, replace `_step_configure_telegraf`:

```python
async def _step_configure_telegraf(db, server, ssh: SSHSession, db_instances: list[dict]):
    log, t0 = await _start_step(db, server.id, "configure_telegraf", 6)
    tmpl = _template_env.get_template("telegraf.conf.j2")
    conf = tmpl.render(
        server_id=str(server.id),
        server_name=server.name,
        ingest_url=settings.opspilot_base_url.rstrip("/") if settings.opspilot_base_url else "http://opspilot-backend:8000",
        ingestion_token=str(server.ingestion_token),
        db_instances=db_instances,
    )
    try:
        await ssh.upload(conf, "/etc/telegraf/telegraf.conf", mode=0o644, sudo=True)
        await _finish_step(db, log, t0, status="done", message="config written")
    except SSHError as e:
        await _finish_step(db, log, t0, status="failed", message=str(e))
        raise
```

- [ ] **Step 4: Update the call site in `run_onboarding`**

In `backend/app/services/onboarding.py`, find the lines that call `_build_mysql_dsn`, `_build_pg_dsn`, and `_step_configure_telegraf`. Replace them:

```python
                db_instances = await _build_db_instances(db, server)
                await _step_configure_telegraf(db, server, ssh, db_instances)
```

(Remove the two `_build_mysql_dsn` / `_build_pg_dsn` calls and the old `_step_configure_telegraf` call.)

- [ ] **Step 5: Verify template renders correctly**

```bash
docker exec opspilot-backend python3 -c "
import asyncio
from app.database import AsyncSessionLocal
from app.services.onboarding import _build_db_instances, _template_env
from app.models.server import Server
from sqlalchemy import select

async def check():
    async with AsyncSessionLocal() as db:
        server = await db.scalar(select(Server).where(Server.is_active == True))
        instances = await _build_db_instances(db, server)
        print('instances:', instances)
        tmpl = _template_env.get_template('telegraf.conf.j2')
        conf = tmpl.render(server_id='x', server_name='x', ingest_url='http://x', ingestion_token='x', db_instances=instances)
        for line in conf.split('\n'):
            if 'mysql' in line.lower() or 'db_label' in line:
                print(line)

asyncio.run(check())
" 2>&1 | grep -v "INFO\|Engine\|BEGIN\|ROLLBACK"
```

Expected output: lines containing `[[inputs.mysql]]`, `db_label = "mysql:3306"` (or actual label).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/templates/telegraf.conf.j2 backend/app/services/onboarding.py
git commit -m "feat(db): Telegraf template loops over db_instances; onboarding uses _build_db_instances"
```

---

### Task 8: Frontend store — new types and updated actions

**Files:**
- Modify: `frontend/src/stores/databases.ts`

- [ ] **Step 1: Replace types**

In `frontend/src/stores/databases.ts`, replace the `DbCredentialStatus` interface and add new ones. Find `export interface DbCredentialStatus` and replace it and everything up to (not including) `export interface DbSeriesPoint`:

```typescript
export interface DbInstanceStatus {
  credential_id: string
  label: string
  host: string
  port: number
  username?: string
  is_replica?: boolean
  db_type: DbType
  last_check_ok: boolean | null
  last_checked: string | null
}

export interface DbServerStatus {
  server_id: string
  server_name: string
  instances: DbInstanceStatus[]
}
```

- [ ] **Step 2: Update `DbCredentialPayload` to include `label`**

Find `export interface DbCredentialPayload` and replace it:

```typescript
export interface DbCredentialPayload {
  host: string
  port: number
  username: string
  password?: string
  is_replica: boolean
  db_type: DbType
  label?: string
}
```

- [ ] **Step 3: Update the store state and actions**

Replace the entire store definition (from `export const useDatabaseStore` to the closing `})`):

```typescript
export const useDatabaseStore = defineStore('databases', () => {
  const servers = ref<DbServerStatus[]>([])
  const latest = ref<Record<string, DbMetricsLatest>>({})
  const loadingCredentials = ref(false)
  const loadingLatest = ref(false)
  const error = ref<string | null>(null)

  function serverFor(serverId: string): DbServerStatus | null {
    return servers.value.find((s) => s.server_id === serverId) ?? null
  }

  function instanceFor(serverId: string, credentialId: string): DbInstanceStatus | null {
    return serverFor(serverId)?.instances.find((i) => i.credential_id === credentialId) ?? null
  }

  function latestFor(serverId: string): DbMetricsLatest {
    return latest.value[serverId] ?? EMPTY_LATEST
  }

  function connectionPct(serverId: string): number {
    const l = latestFor(serverId)
    if (!l.connections_active || !l.connections_max) return 0
    return Math.round((l.connections_active / l.connections_max) * 100)
  }

  // --- Actions ---------------------------------------------------------------

  async function fetchCredentials(orgId: string): Promise<void> {
    loadingCredentials.value = true
    error.value = null
    try {
      const { data } = await api.get<DbServerStatus[]>(
        `/api/organizations/${orgId}/db-credentials`,
      )
      servers.value = data
    } catch {
      error.value = 'Could not load database credential status.'
    } finally {
      loadingCredentials.value = false
    }
  }

  async function saveCredentials(
    serverId: string,
    payload: DbCredentialPayload,
    credentialId: string | null,
  ): Promise<void> {
    const base = `/api/servers/${serverId}/db-credentials`
    if (credentialId) {
      await api.patch(`${base}/${credentialId}`, payload)
    } else {
      await api.post(base, payload)
    }
  }

  async function deleteCredentials(serverId: string, credentialId: string): Promise<void> {
    await api.delete(`/api/servers/${serverId}/db-credentials/${credentialId}`)
    const server = serverFor(serverId)
    if (server) {
      server.instances = server.instances.filter((i) => i.credential_id !== credentialId)
    }
    delete latest.value[`${serverId}:${credentialId}`]
  }

  async function fetchLatest(serverId: string, credentialId: string): Promise<void> {
    loadingLatest.value = true
    try {
      const { data } = await api.get<DbMetricsLatest>(
        `/api/servers/${serverId}/db-metrics/latest`,
        { params: { credential_id: credentialId } },
      )
      latest.value = { ...latest.value, [serverId]: data }
    } catch {
      latest.value = { ...latest.value, [serverId]: { ...EMPTY_LATEST } }
    } finally {
      loadingLatest.value = false
    }
  }

  async function fetchSeries(
    serverId: string,
    metric: DbMetricName,
    range: MetricRange,
    credentialId: string,
  ): Promise<DbSeriesResponse> {
    const { data } = await api.get<DbSeriesResponse>(
      `/api/servers/${serverId}/db-metrics`,
      { params: { metric, range, credential_id: credentialId } },
    )
    return data
  }

  async function fetchPassword(serverId: string, credentialId: string): Promise<string> {
    const { data } = await api.get<{ password: string }>(
      `/api/servers/${serverId}/db-credentials/${credentialId}/password`,
    )
    return data.password
  }

  function reset(): void {
    servers.value = []
    latest.value = {}
    loadingCredentials.value = false
    loadingLatest.value = false
    error.value = null
  }

  return {
    servers,
    // legacy alias so DatabasesView can use store.credentials until fully migrated
    credentials: servers,
    latest,
    loadingCredentials,
    loadingLatest,
    error,
    serverFor,
    instanceFor,
    latestFor,
    connectionPct,
    fetchCredentials,
    saveCredentials,
    deleteCredentials,
    fetchLatest,
    fetchSeries,
    fetchPassword,
    reset,
  }
})
```

- [ ] **Step 4: TypeScript check**

```bash
cd /Users/pocketdata/Code/Work/opspilot/frontend && npx vue-tsc --noEmit 2>&1 | head -30
```

Expected: errors only in components not yet updated (DatabasesView, DbCredentialModal, DbHealthDashboard) — not in the store itself.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/databases.ts
git commit -m "feat(db): store — DbServerStatus/DbInstanceStatus types, credential_id-aware actions"
```

---

### Task 9: Frontend — `DatabasesView` with instance pill bar

**Files:**
- Modify: `frontend/src/views/databases/DatabasesView.vue`

- [ ] **Step 1: Replace the script section**

Replace the entire `<script setup lang="ts">` block:

```typescript
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { PageHeader, EmptyState } from '@/components/ui'
import { useOrgStore } from '@/stores/org'
import { useNotify } from '@/composables/useNotify'
import { useDatabaseStore } from '@/stores/databases'
import type { DbCredentialPayload, DbInstanceStatus } from '@/stores/databases'
import DbNoCredentials from '@/components/databases/DbNoCredentials.vue'
import DbCredentialModal from '@/components/databases/DbCredentialModal.vue'
import DbHealthDashboard from '@/components/databases/DbHealthDashboard.vue'

const orgStore = useOrgStore()
const store = useDatabaseStore()
const notify = useNotify()

const orgId = computed(() => orgStore.activeOrgId)
const canEdit = computed(() => orgStore.canEdit)

const selectedId = ref<string | null>(null)
const selectedInstanceId = ref<string | null>(null)
const modalOpen = ref(false)
const editingInstance = ref<DbInstanceStatus | null>(null)
const confirmRemove = ref(false)
const removingInstance = ref<DbInstanceStatus | null>(null)

const servers = computed(() => store.servers)
const selected = computed(() => servers.value.find((s) => s.server_id === selectedId.value) ?? null)
const selectedInstance = computed(
  () => selected.value?.instances.find((i) => i.credential_id === selectedInstanceId.value) ?? null,
)

const DB_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/></svg>`

function serverBadge(s: typeof servers.value[0]) {
  if (!s.instances.length) return { glyph: '—', tone: 'muted', title: 'No credentials configured' }
  if (s.instances.some((i) => i.last_check_ok === false)) return { glyph: '⚠', tone: 'warn', title: 'Connection error' }
  if (s.instances.every((i) => i.last_check_ok == null)) return { glyph: '◐', tone: 'pending', title: 'Deploying / awaiting first check' }
  return { glyph: '✓', tone: 'ok', title: 'Connected' }
}

function instanceDot(inst: DbInstanceStatus): string {
  if (inst.last_check_ok === false) return '⚠'
  if (inst.last_check_ok == null) return '◐'
  return '●'
}

function instanceDotClass(inst: DbInstanceStatus): string {
  if (inst.last_check_ok === false) return 'warn'
  if (inst.last_check_ok == null) return 'pending'
  return 'ok'
}

function selectInstance(credentialId: string) {
  selectedInstanceId.value = credentialId
}

function selectServer(id: string) {
  selectedId.value = id
  const srv = servers.value.find((s) => s.server_id === id)
  if (!srv || !srv.instances.length) { selectedInstanceId.value = null; return }
  // prefer connected → pending → first
  const connected = srv.instances.find((i) => i.last_check_ok === true)
  const pending = srv.instances.find((i) => i.last_check_ok == null)
  selectedInstanceId.value = (connected ?? pending ?? srv.instances[0]).credential_id
}

async function load() {
  if (!orgId.value) return
  await store.fetchCredentials(orgId.value)
  // Auto-select first server with instances, else first server
  const withCreds = servers.value.find((s) => s.instances.length > 0)
  const target = withCreds ?? servers.value[0]
  if (target) selectServer(target.server_id)
  if (hasPending()) startPolling()
}

// Poll while any instance is awaiting first check
let pollTimer: ReturnType<typeof setInterval> | null = null

function hasPending(): boolean {
  return servers.value.some((s) => s.instances.some((i) => i.last_check_ok == null))
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    if (!orgId.value) return
    await store.fetchCredentials(orgId.value)
    if (!hasPending()) stopPolling()
  }, 10_000)
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

onMounted(load)
onUnmounted(stopPolling)

watch(orgId, () => {
  stopPolling()
  store.reset()
  selectedId.value = null
  selectedInstanceId.value = null
  void load()
})

// Keyboard: ← / → between server tabs
function onKey(e: KeyboardEvent) {
  if (modalOpen.value || confirmRemove.value) return
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
  const idx = servers.value.findIndex((s) => s.server_id === selectedId.value)
  if (idx < 0) return
  const next = e.key === 'ArrowRight' ? idx + 1 : idx - 1
  if (next >= 0 && next < servers.value.length) selectServer(servers.value[next].server_id)
}
onMounted(() => window.addEventListener('keydown', onKey))

function openAddInstance() {
  editingInstance.value = null
  modalOpen.value = true
}

function openEditInstance(inst: DbInstanceStatus) {
  editingInstance.value = inst
  modalOpen.value = true
}

async function onSave(payload: DbCredentialPayload, credentialId: string | null) {
  if (!selectedId.value) return
  try {
    await store.saveCredentials(selectedId.value, payload, credentialId)
    modalOpen.value = false
    notify.success(credentialId ? 'Credentials updated.' : 'DB instance added. Re-deploying Telegraf…')
    if (orgId.value) await store.fetchCredentials(orgId.value)
    if (hasPending()) startPolling()
    // select the newly added instance (last one on server)
    if (!credentialId) {
      const srv = servers.value.find((s) => s.server_id === selectedId.value)
      if (srv?.instances.length) {
        selectedInstanceId.value = srv.instances[srv.instances.length - 1].credential_id
      }
    }
  } catch (err) {
    notify.error(err as Error, { title: 'Could not save credentials' })
  }
}

function promptRemove(inst: DbInstanceStatus) {
  removingInstance.value = inst
  confirmRemove.value = true
}

async function onRemove() {
  if (!selectedId.value || !removingInstance.value) return
  try {
    await store.deleteCredentials(selectedId.value, removingInstance.value.credential_id)
    confirmRemove.value = false
    removingInstance.value = null
    notify.success('DB instance removed. Re-deploying Telegraf…')
    if (orgId.value) await store.fetchCredentials(orgId.value)
    // re-select first instance on server
    const srv = servers.value.find((s) => s.server_id === selectedId.value)
    selectedInstanceId.value = srv?.instances[0]?.credential_id ?? null
  } catch (err) {
    notify.error(err as Error, { title: 'Could not remove instance' })
  }
}
</script>
```

- [ ] **Step 2: Replace the template section**

Replace the entire `<template>` block:

```html
<template>
  <div class="page">
    <PageHeader title="Database Monitoring" subtitle="MariaDB & PostgreSQL health metrics per server" />

    <EmptyState
      v-if="!store.loadingCredentials && !servers.length"
      :icon="DB_ICON"
      title="No servers to monitor"
      message="Add and onboard a server before configuring database monitoring."
    >
      <template #action>
        <router-link to="/" class="link-btn">Go to Dashboard</router-link>
      </template>
    </EmptyState>

    <template v-else>
      <!-- Server tab strip -->
      <div class="tab-strip" role="tablist" aria-label="Servers">
        <button
          v-for="s in servers" :key="s.server_id"
          class="srv-tab" :class="{ active: s.server_id === selectedId }"
          role="tab" :aria-selected="s.server_id === selectedId"
          type="button" @click="selectServer(s.server_id)"
        >
          <span class="srv-name">{{ s.server_name }}</span>
          <span class="srv-badge" :class="serverBadge(s).tone" :title="serverBadge(s).title">
            {{ serverBadge(s).glyph }}
          </span>
        </button>
      </div>

      <div class="content" v-if="selected">
        <!-- Instance pill bar (only when at least one instance exists) -->
        <div v-if="selected.instances.length" class="inst-bar">
          <button
            v-for="inst in selected.instances" :key="inst.credential_id"
            class="inst-pill"
            :class="{ active: inst.credential_id === selectedInstanceId }"
            type="button"
            @click="selectInstance(inst.credential_id)"
          >
            <span class="inst-dot" :class="instanceDotClass(inst)">{{ instanceDot(inst) }}</span>
            {{ inst.label }}
          </button>
          <button v-if="canEdit" class="inst-pill add-pill" type="button" @click="openAddInstance">
            + Add Instance
          </button>
        </div>

        <!-- No credentials yet -->
        <DbNoCredentials
          v-if="!selected.instances.length"
          :key="`nc-${selected.server_id}`"
          :server-name="selected.server_name"
          :can-edit="canEdit"
          db-type="mysql"
          @setup="openAddInstance"
        />

        <!-- Health dashboard for selected instance -->
        <DbHealthDashboard
          v-else-if="selectedInstance"
          :key="`hd-${selectedInstance.credential_id}`"
          :server-id="selected.server_id"
          :server-name="selected.server_name"
          :status="selectedInstance"
          :can-edit="canEdit"
          :db-type="selectedInstance.db_type"
          :credential-id="selectedInstance.credential_id"
          @edit="openEditInstance(selectedInstance)"
          @remove="promptRemove(selectedInstance)"
        />
      </div>
    </template>

    <!-- Credential modal -->
    <DbCredentialModal
      v-model="modalOpen"
      :server-name="selected?.server_name ?? ''"
      :existing="editingInstance"
      @save="onSave"
    />

    <!-- Remove confirmation -->
    <Teleport to="body">
      <div v-if="confirmRemove" class="confirm-scrim" @click.self="confirmRemove = false">
        <div class="confirm" role="alertdialog" aria-modal="true">
          <h3 class="cf-title">Remove {{ removingInstance?.label }} from {{ selected?.server_name }}?</h3>
          <ul class="cf-list">
            <li>Remove stored credentials for this instance</li>
            <li>Remove this input block from Telegraf config (re-deploy required)</li>
            <li>Stop collecting metrics for this instance (history retained)</li>
          </ul>
          <div class="cf-actions">
            <button class="btn ghost" type="button" @click="confirmRemove = false">Cancel</button>
            <button class="btn danger" type="button" @click="onRemove">Remove</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
```

- [ ] **Step 3: Add instance pill bar styles to the `<style scoped>` block**

Append inside the existing `<style scoped>` block (after the last existing rule):

```css
.inst-bar {
  display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px; align-items: center;
}
.inst-pill {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--surface-2); border: 1px solid var(--border); color: var(--muted);
  font-size: 12px; font-weight: 500; padding: 5px 12px; border-radius: 20px; cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}
.inst-pill:hover { border-color: var(--accent); color: var(--text); }
.inst-pill.active { background: rgba(99,102,241,0.15); border-color: var(--accent); color: #fff; }
.inst-pill.add-pill { border-style: dashed; }
.inst-dot { font-size: 10px; }
.inst-dot.ok { color: var(--green); }
.inst-dot.warn { color: var(--amber); }
.inst-dot.pending { color: var(--accent-2); }
```

- [ ] **Step 4: TypeScript check — expect errors only in modal and dashboard**

```bash
cd /Users/pocketdata/Code/Work/opspilot/frontend && npx vue-tsc --noEmit 2>&1 | grep "error TS" | head -20
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/databases/DatabasesView.vue
git commit -m "feat(db): DatabasesView — instance pill bar, selectedInstanceId, multi-instance support"
```

---

### Task 10: Frontend — `DbCredentialModal` with label field

**Files:**
- Modify: `frontend/src/components/databases/DbCredentialModal.vue`

- [ ] **Step 1: Update props and form in the script**

Replace the entire `<script setup lang="ts">` block:

```typescript
<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { SlideOver } from '@/components/ui'
import type { DbCredentialPayload, DbInstanceStatus, DbType } from '@/stores/databases'

const props = defineProps<{
  modelValue: boolean
  serverName: string
  existing: DbInstanceStatus | null
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'save', payload: DbCredentialPayload, credentialId: string | null): void
}>()

const dbType = ref<DbType>('mysql')

const form = reactive<DbCredentialPayload>({
  host: '127.0.0.1',
  port: 3306,
  username: 'opspilot_monitor',
  password: '',
  is_replica: false,
  db_type: 'mysql',
  label: '',
})
const saving = ref(false)
const errors = reactive<Record<string, string>>({})
const isEdit = ref(false)

watch(dbType, (t) => {
  if (isEdit.value) return
  form.port = t === 'postgres' ? 5432 : 3306
  if (!form.username || form.username === 'opspilot_monitor' || form.username === 'opspilot') {
    form.username = t === 'postgres' ? 'opspilot' : 'opspilot_monitor'
  }
})

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    saving.value = false
    Object.keys(errors).forEach((k) => delete errors[k])
    const e = props.existing
    isEdit.value = !!e
    dbType.value = e?.db_type ?? 'mysql'
    form.host = e?.host ?? '127.0.0.1'
    form.port = e?.port ?? (dbType.value === 'postgres' ? 5432 : 3306)
    form.username = e?.username ?? (dbType.value === 'postgres' ? 'opspilot' : 'opspilot_monitor')
    form.password = ''
    form.is_replica = e?.is_replica ?? false
    form.db_type = dbType.value
    form.label = e?.label ?? ''
  },
)

function validate(): boolean {
  Object.keys(errors).forEach((k) => delete errors[k])
  if (!form.host.trim()) errors.host = 'Host is required.'
  else if (/^\w+:\/\//.test(form.host)) errors.host = 'Enter a hostname or IP, no protocol prefix.'
  if (!form.port || form.port < 1 || form.port > 65535) errors.port = 'Port must be 1–65535.'
  if (!form.username.trim()) errors.username = 'Username is required.'
  else if (form.username.length > 80) errors.username = 'Max 80 characters.'
  if (!isEdit.value && !form.password) errors.password = 'Password is required.'
  if (form.password && form.password.length > 255) errors.password = 'Max 255 characters.'
  if (form.label && form.label.length > 60) errors.label = 'Max 60 characters.'
  return Object.keys(errors).length === 0
}

function submit() {
  if (saving.value) return
  if (!validate()) return
  saving.value = true
  const payload: DbCredentialPayload = {
    host: form.host.trim(),
    port: Number(form.port),
    username: form.username.trim(),
    is_replica: form.is_replica,
    db_type: dbType.value,
    label: form.label?.trim() || undefined,
  }
  if (form.password) payload.password = form.password
  emit('save', payload, props.existing?.credential_id ?? null)
}

watch(
  () => props.modelValue,
  (open) => { if (!open) saving.value = false },
)

const showPassword = ref(false)
</script>
```

- [ ] **Step 2: Add the label field to the template**

In the `<template>` block, find the password field `</label>` closing tag and add the label field after it (before the `is_replica` toggle):

```html
      <label class="field">
        <span class="lbl">Instance Label</span>
        <input
          v-model="form.label"
          class="inp"
          :class="{ err: errors.label }"
          placeholder="e.g. Primary, Analytics, Port 3307"
          autocomplete="off"
          maxlength="60"
        />
        <small v-if="errors.label" class="err-msg">{{ errors.label }}</small>
        <small v-else class="hint">Optional — defaults to "{{ dbType }}:{{ form.port }}" if blank.</small>
      </label>
```

- [ ] **Step 3: Update the SlideOver title and subtitle**

Find the `<SlideOver` opening tag and update `:title` and `subtitle`:

```html
  <SlideOver
    :model-value="modelValue"
    :title="isEdit ? `Edit DB Instance — ${existing?.label ?? serverName}` : `Add DB Instance — ${serverName}`"
    subtitle="Read-only database monitoring user"
    width="480px"
    @update:model-value="emit('update:modelValue', $event)"
  >
```

- [ ] **Step 4: Remove the `db_type` disabled condition** (allow type change on create always)

Find `:disabled="!!existing?.has_credentials"` on both type-pill buttons and replace with:

```html
:disabled="isEdit"
```

- [ ] **Step 5: TypeScript check**

```bash
cd /Users/pocketdata/Code/Work/opspilot/frontend && npx vue-tsc --noEmit 2>&1 | grep "error TS" | head -10
```

Expected: only DbHealthDashboard errors remain.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/databases/DbCredentialModal.vue
git commit -m "feat(db): DbCredentialModal — label field, instance-aware props and emit"
```

---

### Task 11: Frontend — `DbHealthDashboard` with `credentialId` prop

**Files:**
- Modify: `frontend/src/components/databases/DbHealthDashboard.vue`

- [ ] **Step 1: Update props and store calls in the script**

In `<script setup lang="ts">`, add `credentialId` to props:

```typescript
const props = defineProps<{
  serverId: string
  serverName: string
  status: DbInstanceStatus
  canEdit: boolean
  dbType?: 'mysql' | 'postgres'
  credentialId: string
}>()
```

(Import `DbInstanceStatus` instead of `DbCredentialStatus` from the store.)

- [ ] **Step 2: Update `reload` and `loadSeries` to pass `credentialId`**

Find the `reload` function and `loadSeries` function. Update `store.fetchLatest` and `store.fetchSeries` calls:

```typescript
async function reload() {
  await Promise.all([store.fetchLatest(props.serverId, props.credentialId), loadSeries()])
}
```

In `loadSeries`, update each `store.fetchSeries` call:

```typescript
        store
          .fetchSeries(props.serverId, m as any, range.value, props.credentialId)
```

- [ ] **Step 3: Update `copyPassword` to pass `credentialId`**

Find `copyPassword` and update:

```typescript
    const pw = await store.fetchPassword(props.serverId, props.credentialId)
```

- [ ] **Step 4: Add watch on `credentialId` to reload when instance switches**

After the existing `watch(range, loadSeries)` line, add:

```typescript
watch(() => props.credentialId, reload)
```

- [ ] **Step 5: TypeScript check — expect zero errors**

```bash
cd /Users/pocketdata/Code/Work/opspilot/frontend && npx vue-tsc --noEmit 2>&1 | head -20
```

Expected: no output (zero errors).

- [ ] **Step 6: Smoke test in the browser**

1. Open `http://localhost:9090/databases`
2. Confirm the existing server tab shows with its instance pill (`mysql:3306` or the label you set)
3. Confirm the health dashboard loads with metrics
4. Click "+ Add Instance", fill in a second MySQL on a different port (e.g. 3307), save
5. Confirm a second pill appears
6. Click between the two pills — dashboard updates to that instance's metrics (shows `—` if no data yet)
7. "Copy Password" copies the right credential's password
8. "Remove" targets the active instance, not the whole server

- [ ] **Step 7: Commit and push**

```bash
git add frontend/src/components/databases/DbHealthDashboard.vue
git commit -m "feat(db): DbHealthDashboard — credentialId prop, instance-aware metric fetches"
git push origin main
```
