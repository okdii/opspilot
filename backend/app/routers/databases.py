"""Database deep monitoring — DB credential CRUD + DB metric reads (spec 08).

Credential save/update/delete each re-render Telegraf's `inputs.mysql` block and
restart the agent over SSH via the existing onboarding redeploy
(`onboarding.schedule(server_id, redeploy_only=True)` →
`run_onboarding` rebuilds the mysql_dsn from the stored, encrypted DBCredential
and uploads telegraf.conf). Passwords are AES-GCM encrypted at rest
(`app.core.crypto`) and never returned by any endpoint.

DB metrics are collected by Telegraf's `inputs.mysql` plugin (measurement
`mysql`) and land in `server_metrics` as `mysql.<field>` rows. These read
endpoints translate the spec's abstract metric names (connections_active,
queries_per_sec, …) to the stored Telegraf field names and serve latest + time
series. `queries_per_sec`, `slow_queries_per_min`, and the cumulative counters
(deadlocks / table_locks / aborted_connections) are derived as rates from the
monotonic Telegraf counters.

Alert evaluation (spec 08 §9):
  * db_connections (>80% of max, rolling avg) and db_replication_lag (>30s) are
    handled by the generic Phase-8 metric_alert_evaluator via AlertRules — this
    module does NOT duplicate that. db_replication_stopped is also generic.
  * db_deadlock is DB-specific (delta tracking against
    DBCredential.last_deadlock_count) and is NOT covered by the generic
    evaluator, so it lives here as `db_deadlock_evaluator` — a coroutine the
    COORDINATOR wires into the scheduler (see module footer). It fires via the
    shared `fire_alert` seam.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt
from app.database import AsyncSessionLocal, get_db
from app.deps import AdminUser, CurrentUser
from app.models.organization import Organization
from app.models.other import DBCredential
from app.models.server import Server
from app.models.user import UserOrganization
from app.routers.servers import _assert_server_access
from app.services import onboarding as onboarding_service
from app.services.alerting import fire_alert
from app.services.metric_catalog import RANGE_INTERVAL, RANGE_SOURCE

logger = logging.getLogger(__name__)

router = APIRouter(tags=["databases"])


# ── Metric-name mapping ──────────────────────────────────────────────────────
# Spec-08 abstract metric name -> (stored Telegraf metric_name, is_rate).
# Telegraf's inputs.mysql writes the `mysql` measurement; the cumulative global
# status counters (queries, slow_queries, innodb_deadlocks, table_locks_waited,
# aborted_connects) must be served as per-interval rates, not raw counts.
# Replication lag is published by the mariadb-flavoured slave-status gather under
# `mariadb.seconds_behind_master` (matches the Phase-8 evaluator's mapping).
_METRIC_MAP: dict[str, tuple[str, bool]] = {
    "connections_active": ("mysql.threads_connected", False),
    "queries_per_sec": ("mysql.queries", True),
    "slow_queries_per_min": ("mysql.slow_queries", True),
    "innodb_buffer_pool_hit_rate": ("mysql.innodb_buffer_pool_hit_rate", False),
    "innodb_deadlocks": ("mysql.innodb_deadlocks", True),
    "replication_lag_sec": ("mariadb.seconds_behind_master", False),
    "table_locks_waited": ("mysql.table_locks_waited", True),
    "aborted_connections": ("mysql.aborted_connects", True),
}

_PG_METRIC_MAP: dict[str, tuple[str, bool]] = {
    "connections_active":   ("postgresql.numbackends",       False),
    "transactions_per_sec": ("postgresql.xact_commit",       True),
    "cache_hit_rate":       ("postgresql.blks_hit_rate",     False),
    "deadlocks":            ("postgresql.deadlocks",         True),
    "tuple_ops_per_sec":    ("postgresql.tup_inserted",      True),
    "temp_files_per_min":   ("postgresql.temp_files",        True),
    "checkpoints_per_min":  ("postgresql.checkpoints_timed", True),
    "replication_lag_sec":  ("postgresql.replication_delay", False),
}

# Stored metric name carrying the connection ceiling, for the connections chart.
_MAX_CONNECTIONS_METRIC = "mysql.max_connections"

# Stored counter used for the deadlock delta evaluator.
_DEADLOCKS_STORED = "mysql.innodb_deadlocks"


# ── Schemas ──────────────────────────────────────────────────────────────────

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
    # Omit/blank to preserve existing encrypted password (spec §4.3 / §12.2).
    password: str | None = Field(default=None, max_length=255)
    is_replica: bool | None = None
    db_type: str | None = Field(default=None, pattern="^(mysql|postgres)$")
    label: str | None = Field(default=None, max_length=60)


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _assert_org_access(org_id: str, user, db: AsyncSession) -> None:
    org = await db.scalar(select(Organization).where(Organization.id == org_id))
    if not org:
        raise HTTPException(404, detail={"error": "not_found", "message": "Organization not found."})
    if user.role != "admin":
        membership = await db.scalar(
            select(UserOrganization).where(
                UserOrganization.user_id == user.id,
                UserOrganization.org_id == org_id,
            )
        )
        if not membership:
            raise HTTPException(403, detail={"error": "forbidden", "message": "Access denied."})


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


async def _last_check(db: AsyncSession, server_id: str) -> tuple[bool | None, datetime | None]:
    """Best-effort connection health: did any mysql.* sample land in the last
    couple of minutes? Returns (ok, last_collected_at). ok is None when no DB
    metric has ever been seen for this server."""
    row = (
        await db.execute(
            text(
                """
                SELECT MAX(time) AS last_t
                FROM server_metrics
                WHERE server_id = :sid AND metric_name LIKE 'mysql.%'
                """
            ),
            {"sid": str(server_id)},
        )
    ).first()
    last_t = row.last_t if row else None
    if last_t is None:
        return None, None
    if last_t.tzinfo is None:
        last_t = last_t.replace(tzinfo=timezone.utc)
    ok = (datetime.now(timezone.utc) - last_t).total_seconds() <= 120
    return ok, last_t


def _trigger_redeploy(server_id: str) -> bool:
    """Queue the Telegraf re-deploy that re-renders telegraf.conf (now with the
    updated/removed mysql_dsn) and restarts the agent. Returns False if a
    redeploy/onboarding is already running for this server."""
    return onboarding_service.schedule(str(server_id), redeploy_only=True)


# ── Credential endpoints ─────────────────────────────────────────────────────

@router.get("/api/organizations/{org_id}/db-credentials")
async def list_db_credentials(org_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """One entry per active server in the org with its credential status. No
    passwords are returned (spec §12.1)."""
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
        cred = await _get_credential(str(s.id), db)
        if cred is None:
            out.append(
                {
                    "server_id": str(s.id),
                    "server_name": s.name,
                    "has_credentials": False,
                    "db_type": "mysql",
                }
            )
            continue
        last_ok, last_checked = await _last_check(db, str(s.id))
        out.append(
            {
                "server_id": str(s.id),
                "server_name": s.name,
                "has_credentials": True,
                "host": cred.host,
                "port": cred.port,
                "username": cred.username,
                "is_replica": cred.is_replica,
                "db_type": cred.db_type,
                "last_check_ok": last_ok,
                "last_checked": last_checked.isoformat() if last_checked else None,
            }
        )
    return out


@router.post("/api/servers/{server_id}/db-credentials", status_code=201)
async def create_db_credentials(
    server_id: str, body: DBCredentialIn, user: AdminUser, db: AsyncSession = Depends(get_db)
):
    server = await db.scalar(
        select(Server).where(Server.id == server_id, Server.is_active == True)  # noqa: E712
    )
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})

    if await _get_credential(server_id, db) is not None:
        raise HTTPException(
            409,
            detail={
                "error": "already_exists",
                "message": "DB credentials already configured — use PATCH to update.",
            },
        )

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

    redeploy_queued = _trigger_redeploy(server_id)
    return {
        "server_id": str(server_id),
        "host": cred.host,
        "port": cred.port,
        "username": cred.username,
        "is_replica": cred.is_replica,
        "has_credentials": True,
        "redeploy_queued": redeploy_queued,
    }


@router.patch("/api/servers/{server_id}/db-credentials")
async def update_db_credentials(
    server_id: str, body: DBCredentialPatch, user: AdminUser, db: AsyncSession = Depends(get_db)
):
    server = await db.scalar(
        select(Server).where(Server.id == server_id, Server.is_active == True)  # noqa: E712
    )
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})

    cred = await _get_credential(server_id, db)
    if cred is None:
        raise HTTPException(
            404,
            detail={"error": "not_found", "message": "No DB credentials configured for this server."},
        )

    # Track whether anything that affects the Telegraf config changed; a blank
    # password with no other field change preserves creds and skips re-deploy
    # (spec §13 edge state).
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
    if body.password:  # non-empty → rotate password
        cred.password_encrypted = encrypt(body.password)
        config_changed = True

    await db.commit()
    await db.refresh(cred)

    redeploy_queued = _trigger_redeploy(server_id) if config_changed else False
    return {
        "server_id": str(server_id),
        "host": cred.host,
        "port": cred.port,
        "username": cred.username,
        "is_replica": cred.is_replica,
        "has_credentials": True,
        "redeploy_queued": redeploy_queued,
    }



@router.delete("/api/servers/{server_id}/db-credentials", status_code=200)
async def delete_db_credentials(
    server_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)
):
    server = await db.scalar(
        select(Server).where(Server.id == server_id, Server.is_active == True)  # noqa: E712
    )
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})

    cred = await _get_credential(server_id, db)
    if cred is None:
        raise HTTPException(
            404,
            detail={"error": "not_found", "message": "No DB credentials configured for this server."},
        )

    await db.delete(cred)
    await db.commit()

    # Re-deploy with no DBCredential present → telegraf.conf renders without the
    # inputs.mysql block (mysql_dsn is None) and Telegraf restarts. Existing
    # metric history is retained.
    redeploy_queued = _trigger_redeploy(server_id)
    return {"ok": True, "redeploy_queued": redeploy_queued}


# ── Metric read endpoints ────────────────────────────────────────────────────

@router.get("/api/servers/{server_id}/db-metrics/latest")
async def get_db_metrics_latest(
    server_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """Latest DB metric values for the stat cards (spec §11 DBMetricsLatest).
    Returns null-valued fields gracefully when no DB metrics are flowing yet."""
    await _assert_server_access(server_id, user, db)

    cred = await _get_credential(server_id, db)
    is_pg = cred and cred.db_type == "postgres"

    # Latest single sample per metric within a short lookback (10 min).
    rows = (
        await db.execute(
            text(
                """
                SELECT DISTINCT ON (metric_name) metric_name, value, time
                FROM server_metrics
                WHERE server_id = :sid
                  AND (metric_name LIKE 'mysql.%' OR metric_name LIKE 'mariadb.%' OR metric_name LIKE 'postgresql.%')
                  AND time >= now() - INTERVAL '10 minutes'
                ORDER BY metric_name, time DESC
                """
            ),
            {"sid": str(server_id)},
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
            "transactions_per_sec": await _rate_latest(db, server_id, "postgresql.xact_commit", per="sec"),
            "cache_hit_rate":       _val("postgresql.blks_hit_rate"),
            "deadlocks":            await _rate_latest(db, server_id, "postgresql.deadlocks", per="sec"),
            "tuple_ops_per_sec":    await _pg_tuple_ops_rate(db, server_id),
            "temp_files_per_min":   await _rate_latest(db, server_id, "postgresql.temp_files", per="min"),
            "checkpoints_per_min":  await _rate_latest(db, server_id, "postgresql.checkpoints_timed", per="min"),
            "replication_lag_sec":  _val("postgresql.replication_delay") if (cred and cred.is_replica) else None,
            "replication_running":  None,
            "mariadb_version":      None,
            "last_collected_at":    last_t.isoformat() if last_t else None,
        }

    # Rate-based fields (per second / per minute) are derived from the last two
    # raw counter samples.
    qps = await _rate_latest(db, server_id, "mysql.queries", per="sec")
    slow_pm = await _rate_latest(db, server_id, "mysql.slow_queries", per="min")

    # mariadb version arrives as a string field; we don't store strings in
    # server_metrics (numeric only), so version is surfaced as null here and
    # read from the metric labels by the frontend if available.
    is_replica = bool(cred.is_replica) if cred else False

    return {
        "connections_active": _val("mysql.threads_connected"),
        "connections_max": _val(_MAX_CONNECTIONS_METRIC),
        "queries_per_sec": qps,
        "slow_queries_per_min": slow_pm,
        "innodb_buffer_pool_hit_rate": _val("mysql.innodb_buffer_pool_hit_rate"),
        "innodb_deadlocks": _val("mysql.innodb_deadlocks"),
        "replication_lag_sec": _val("mariadb.seconds_behind_master") if is_replica else None,
        "replication_running": (
            bool(_val("mariadb.replication_running"))
            if (is_replica and _val("mariadb.replication_running") is not None)
            else None
        ),
        "table_locks_waited": _val("mysql.table_locks_waited"),
        "aborted_connections": _val("mysql.aborted_connects"),
        "mariadb_version": None,
        "last_collected_at": last_t.isoformat() if last_t else None,
    }


async def _rate_latest(db: AsyncSession, server_id: str, stored: str, *, per: str) -> float | None:
    """Per-second (per='sec') or per-minute (per='min') rate from the two most
    recent counter samples. None when fewer than two samples or on a reset."""
    rows = (
        await db.execute(
            text(
                """
                SELECT value, time
                FROM server_metrics
                WHERE server_id = :sid AND metric_name = :m
                  AND time >= now() - INTERVAL '10 minutes'
                ORDER BY time DESC
                LIMIT 2
                """
            ),
            {"sid": str(server_id), "m": stored},
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
    if delta < 0:  # counter reset
        return None
    rate_per_sec = delta / dt
    return round(rate_per_sec * (60 if per == "min" else 1), 2)


async def _pg_tuple_ops_rate(db: AsyncSession, server_id: str) -> float | None:
    """Sum of insert+update+delete rates (per sec) for PostgreSQL tuple operations."""
    ins = await _rate_latest(db, server_id, "postgresql.tup_inserted", per="sec")
    upd = await _rate_latest(db, server_id, "postgresql.tup_updated", per="sec")
    dlt = await _rate_latest(db, server_id, "postgresql.tup_deleted", per="sec")
    parts = [v for v in [ins, upd, dlt] if v is not None]
    return round(sum(parts), 2) if parts else None


@router.get("/api/servers/{server_id}/db-metrics")
async def get_db_metrics(
    server_id: str,
    user: CurrentUser,
    metric: str = Query(...),
    range: str = Query("1h"),
    db: AsyncSession = Depends(get_db),
):
    """Time-series chart data for one DB metric over a range (spec §12.2).
    Counter-derived metrics are returned as rates. Returns an empty `data` array
    gracefully when no samples exist."""
    await _assert_server_access(server_id, user, db)

    cred = await _get_credential(server_id, db)
    metric_map = _PG_METRIC_MAP if (cred and cred.db_type == "postgres") else _METRIC_MAP

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

    pts = await _series(db, server_id, stored, source, valcol, timecol, interval, is_rate)

    result: dict = {"metric": metric, "range": range, "resolution": resolution, "data": pts}

    if metric == "connections_active" and not (cred and cred.db_type == "postgres"):
        max_pts = await _series(
            db, server_id, _MAX_CONNECTIONS_METRIC, source, valcol, timecol, interval, False
        )
        # Ceiling line: the most recent max value (or null when unavailable).
        result["connections_max"] = max_pts[-1]["value"] if max_pts else None

    return result


async def _series(
    db: AsyncSession,
    server_id: str,
    stored: str,
    source: str,
    valcol: str,
    timecol: str,
    interval: str,
    is_rate: bool,
) -> list[dict]:
    rows = (
        await db.execute(
            text(
                f"""
                SELECT {timecol} AS t, {valcol} AS v
                FROM {source}
                WHERE server_id = :sid AND metric_name = :m
                  AND {timecol} >= now() - INTERVAL '{interval}'
                ORDER BY {timecol} ASC
                """
            ),
            {"sid": str(server_id), "m": stored},
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
            if delta < 0:  # counter reset
                continue
            out.append({"time": cur["_t"].isoformat(), "value": round(delta / dt, 4)})
        return out

    return [{"time": p["_t"].isoformat(), "value": p["value"]} for p in pts]


# ── DB deadlock alert evaluator (spec §9 step 3) ─────────────────────────────
# DB-specific: not covered by the generic Phase-8 metric_alert_evaluator (which
# handles db_connections / db_replication_lag / db_replication_stopped via
# AlertRules). This tracks the cumulative innodb_deadlocks counter against
# DBCredential.last_deadlock_count and fires `db_deadlock` on any increase.
#
# COORDINATOR — wire into scheduler.py / main.py (NOT edited here):
#     from app.routers.databases import db_deadlock_evaluator
#     scheduler.add_job(
#         db_deadlock_evaluator, "interval", seconds=60,
#         id="db_deadlock_evaluator", replace_existing=True,
#     )

async def _latest_deadlock_count(db: AsyncSession, server_id) -> int | None:
    row = (
        await db.execute(
            text(
                """
                SELECT value FROM server_metrics
                WHERE server_id = :sid AND metric_name = :m
                  AND time >= now() - INTERVAL '10 minutes'
                ORDER BY time DESC LIMIT 1
                """
            ),
            {"sid": str(server_id), "m": _DEADLOCKS_STORED},
        )
    ).first()
    if row is None or row.value is None:
        return None
    return int(row.value)


async def db_deadlock_evaluator() -> None:
    """APScheduler entry point (60s). For every server with DB credentials,
    compare the latest cumulative innodb_deadlocks counter to the persisted
    last_deadlock_count. On increase → fire 'db_deadlock' (critical) and update
    the stored count. On a decrease (MariaDB restart / counter reset) → silently
    reset last_deadlock_count to the current value without firing (spec §13)."""
    async with AsyncSessionLocal() as db:
        try:
            creds = (await db.execute(select(DBCredential))).scalars().all()
            for cred in creds:
                try:
                    current = await _latest_deadlock_count(db, cred.server_id)
                    if current is None:
                        continue  # no DB telemetry for this server
                    prev = cred.last_deadlock_count
                    if prev is None:
                        # First observation — establish the baseline, no alert.
                        cred.last_deadlock_count = current
                        await db.flush()
                        continue
                    if current < prev:
                        # Counter reset (restart) — clean slate, no alert.
                        cred.last_deadlock_count = current
                        await db.flush()
                        continue
                    if current > prev:
                        new_deadlocks = current - prev
                        await fire_alert(
                            db,
                            type="db_deadlock",
                            severity="critical",
                            message=(
                                f"{new_deadlocks} new InnoDB deadlock(s) detected "
                                f"(total {current})."
                            ),
                            server_id=cred.server_id,
                            cooldown_min=60,
                            email_meta={
                                "condition": "innodb_deadlocks increased",
                                "value": current,
                                "threshold": prev,
                            },
                            commit=False,
                        )
                        cred.last_deadlock_count = current
                        await db.flush()
                except Exception:  # noqa: BLE001 — one server must not stall the rest
                    logger.exception(
                        "db_deadlock_evaluator: server %s evaluation failed", cred.server_id
                    )
            await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("db_deadlock_evaluator tick failed")
            await db.rollback()
