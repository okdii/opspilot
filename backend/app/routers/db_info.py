"""On-demand live database info endpoint (spec: 2026-06-10-db-info-tab-design.md).

Connects directly to the monitored database to collect version, charset, sizes,
SSL status, and storage info.  Static fields (host, port, type) come from the
stored credential.  Server hardware info (CPU, RAM, disk) comes from the
existing Telegraf server_metrics table.  Backup info comes from MonitoredJob.

Timeout: 5 s on the live DB connection — if unreachable, returns reachable=false
with static fields only; never raises 5xx for a down database.
"""
from __future__ import annotations

import logging

import asyncpg
import aiomysql
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt
from app.database import get_db
from app.deps import CurrentUser
from app.models.other import DBCredential, MonitoredJob
from app.models.server import Server
from app.routers.databases import _assert_server_access, _get_credential_by_id, _resolve_label

logger = logging.getLogger(__name__)
router = APIRouter(tags=["databases"])

_LIVE_TIMEOUT = 5  # seconds


# ── Live query helpers ────────────────────────────────────────────────────────

async def _query_mysql(host: str, port: int, user: str, password: str) -> dict:
    """Connect to MySQL/MariaDB and collect info fields. Returns reachable=False on any error."""
    try:
        conn = await aiomysql.connect(
            host=host, port=port, user=user, password=password,
            connect_timeout=_LIVE_TIMEOUT,
        )
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SHOW GLOBAL VARIABLES WHERE Variable_name IN "
                "('version','datadir','character_set_server','collation_server','time_zone')"
            )
            variables = {r["Variable_name"]: r["Value"] for r in await cur.fetchall()}

            await cur.execute(
                "SHOW GLOBAL STATUS WHERE Variable_name IN ('Uptime','Ssl_cipher')"
            )
            status = {r["Variable_name"]: r["Value"] for r in await cur.fetchall()}

            await cur.execute(
                "SELECT COALESCE(SUM(data_length + index_length), 0) AS b "
                "FROM information_schema.tables"
            )
            total_size = (await cur.fetchone() or {}).get("b")

            await cur.execute(
                "SELECT COUNT(DISTINCT table_schema) AS n FROM information_schema.tables "
                "WHERE table_schema NOT IN ('information_schema','performance_schema','mysql','sys')"
            )
            db_count = (await cur.fetchone() or {}).get("n")

            await cur.execute(
                "SELECT COUNT(*) AS n FROM information_schema.tables "
                "WHERE table_schema NOT IN ('information_schema','performance_schema','mysql','sys')"
            )
            table_count = (await cur.fetchone() or {}).get("n")

            await cur.execute(
                "SELECT table_schema AS name, SUM(data_length + index_length) AS sz "
                "FROM information_schema.tables "
                "WHERE table_schema NOT IN ('information_schema','performance_schema','mysql','sys') "
                "GROUP BY table_schema ORDER BY sz DESC LIMIT 1"
            )
            largest_db = await cur.fetchone()

            await cur.execute(
                "SELECT CONCAT(table_schema,'.',table_name) AS name, "
                "(data_length + index_length) AS sz "
                "FROM information_schema.tables "
                "WHERE table_schema NOT IN ('information_schema','performance_schema','mysql','sys') "
                "ORDER BY sz DESC LIMIT 1"
            )
            largest_table = await cur.fetchone()

        conn.close()
        ssl_cipher = status.get("Ssl_cipher", "")
        return {
            "reachable": True,
            "version": variables.get("version"),
            "data_directory": variables.get("datadir"),
            "character_set": variables.get("character_set_server"),
            "collation": variables.get("collation_server"),
            "time_zone": variables.get("time_zone"),
            "uptime_seconds": int(status["Uptime"]) if status.get("Uptime") else None,
            "ssl_enabled": bool(ssl_cipher),
            "ssl_version": ssl_cipher or None,
            "size_bytes": int(total_size) if total_size is not None else None,
            "total_databases": int(db_count) if db_count is not None else None,
            "total_tables": int(table_count) if table_count is not None else None,
            "largest_db": {"name": largest_db["name"], "size_bytes": int(largest_db["sz"])} if largest_db and largest_db["sz"] else None,
            "largest_table": {"name": largest_table["name"], "size_bytes": int(largest_table["sz"])} if largest_table and largest_table["sz"] else None,
        }
    except Exception:  # noqa: BLE001
        logger.warning("db_info: mysql query failed for %s:%s", host, port)
        return {"reachable": False}


async def _query_postgres(host: str, port: int, user: str, password: str) -> dict:
    """Connect to PostgreSQL and collect info fields. Returns reachable=False on any error."""
    try:
        conn = await asyncpg.connect(
            host=host, port=port, user=user, password=password,
            database="postgres", timeout=_LIVE_TIMEOUT,
        )
        version = await conn.fetchval("SELECT version()")
        data_dir = await conn.fetchval("SHOW data_directory")
        encoding = await conn.fetchval("SHOW server_encoding")
        collation = await conn.fetchval("SHOW lc_collate")
        timezone = await conn.fetchval("SHOW TimeZone")
        uptime_sec = await conn.fetchval(
            "SELECT EXTRACT(EPOCH FROM (NOW() - pg_postmaster_start_time()))::bigint"
        )
        ssl_row = await conn.fetchrow(
            "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
        )
        total_size = await conn.fetchval(
            "SELECT COALESCE(SUM(pg_database_size(datname)),0) "
            "FROM pg_database WHERE datistemplate = false"
        )
        db_count = await conn.fetchval(
            "SELECT COUNT(*) FROM pg_database WHERE datistemplate = false"
        )
        table_count = await conn.fetchval(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog','information_schema')"
        )
        largest_db = await conn.fetchrow(
            "SELECT datname AS name, pg_database_size(datname) AS sz "
            "FROM pg_database WHERE datistemplate = false ORDER BY sz DESC LIMIT 1"
        )
        largest_table = await conn.fetchrow(
            "SELECT schemaname || '.' || relname AS name, "
            "pg_total_relation_size(relid) AS sz "
            "FROM pg_stat_user_tables ORDER BY sz DESC LIMIT 1"
        )
        await conn.close()

        ssl_on = bool(ssl_row and ssl_row["ssl"])
        return {
            "reachable": True,
            "version": version,
            "data_directory": data_dir,
            "character_set": encoding,
            "collation": collation,
            "time_zone": timezone,
            "uptime_seconds": int(uptime_sec) if uptime_sec is not None else None,
            "ssl_enabled": ssl_on,
            "ssl_version": "Enabled" if ssl_on else None,
            "size_bytes": int(total_size) if total_size is not None else None,
            "total_databases": int(db_count) if db_count is not None else None,
            "total_tables": int(table_count) if table_count is not None else None,
            "largest_db": {"name": largest_db["name"], "size_bytes": int(largest_db["sz"])} if largest_db else None,
            "largest_table": {"name": largest_table["name"], "size_bytes": int(largest_table["sz"])} if largest_table else None,
        }
    except Exception:  # noqa: BLE001
        logger.warning("db_info: postgres query failed for %s:%s", host, port)
        return {"reachable": False}


async def _get_server_hw(db: AsyncSession, server_id: str) -> dict:
    """Latest hardware metrics from Telegraf (CPU, RAM, disk)."""
    rows = (
        await db.execute(
            text("""
                SELECT DISTINCT ON (metric_name) metric_name, value
                FROM server_metrics
                WHERE server_id = :sid
                  AND metric_name IN ('system.n_cpus','mem.total','disk.total','disk.free')
                  AND time >= now() - INTERVAL '10 minutes'
                ORDER BY metric_name, time DESC
            """),
            {"sid": str(server_id)},
        )
    ).all()
    return {m: v for m, v in rows if v is not None}


async def _get_conn_metrics(
    db: AsyncSession, server_id: str, label: str, db_type: str
) -> dict:
    """Current and max connections from the latest Telegraf metrics."""
    if db_type == "postgres":
        metric_cur = "postgresql.numbackends"
        metric_max = None
    else:
        metric_cur = "mysql.threads_connected"
        metric_max = "mysql.max_connections"

    wanted = [m for m in [metric_cur, metric_max] if m]
    rows = (
        await db.execute(
            text("""
                SELECT DISTINCT ON (metric_name) metric_name, value
                FROM server_metrics
                WHERE server_id = :sid
                  AND metric_name = ANY(:metrics)
                  AND (labels->>'db_label' = :label OR labels->>'db_label' IS NULL)
                  AND time >= now() - INTERVAL '10 minutes'
                ORDER BY metric_name, time DESC
            """),
            {"sid": str(server_id), "metrics": wanted, "label": label},
        )
    ).all()
    vals = {m: v for m, v in rows if v is not None}
    return {
        "current": int(vals[metric_cur]) if metric_cur in vals else None,
        "max": int(vals[metric_max]) if metric_max and metric_max in vals else None,
    }


async def _get_backup(db: AsyncSession, server_id: str) -> dict | None:
    """Latest MonitoredJob record for this server (first by last_ping_at desc)."""
    job = await db.scalar(
        select(MonitoredJob)
        .where(MonitoredJob.server_id == server_id)
        .order_by(MonitoredJob.last_ping_at.desc().nulls_last())
        .limit(1)
    )
    if not job:
        return None
    return {
        "last_run_at": job.last_ping_at.isoformat() if job.last_ping_at else None,
        "status": job.status,
        "size_bytes": job.last_size_bytes,
    }


async def _get_replication(
    db: AsyncSession, server_id: str, label: str, cred: DBCredential
) -> dict:
    """Replication status from Telegraf metrics."""
    if cred.db_type == "postgres":
        metric_running = "postgresql.replication_delay"
        metric_lag = "postgresql.replication_delay"
    else:
        metric_running = "mariadb.replication_running"
        metric_lag = "mariadb.seconds_behind_master"

    rows = (
        await db.execute(
            text("""
                SELECT DISTINCT ON (metric_name) metric_name, value
                FROM server_metrics
                WHERE server_id = :sid
                  AND metric_name IN (:m_run, :m_lag)
                  AND (labels->>'db_label' = :label OR labels->>'db_label' IS NULL)
                  AND time >= now() - INTERVAL '10 minutes'
                ORDER BY metric_name, time DESC
            """),
            {"sid": str(server_id), "m_run": metric_running, "m_lag": metric_lag, "label": label},
        )
    ).all()
    vals = {m: v for m, v in rows if v is not None}

    role = "replica" if cred.is_replica else "primary"
    if cred.db_type == "postgres":
        lag = float(vals.get(metric_lag, 0)) if vals.get(metric_lag) is not None else None
        running = lag is not None
    else:
        running_v = vals.get(metric_running)
        running = bool(running_v) if running_v is not None else None
        lag_v = vals.get(metric_lag)
        lag = float(lag_v) if lag_v is not None else None

    return {"role": role, "running": running, "lag_sec": lag}


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/api/servers/{server_id}/db-info")
async def get_db_info(
    server_id: str,
    user: CurrentUser,
    credential_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Live database information snapshot for the Info tab."""
    await _assert_server_access(server_id, user, db)
    cred = await _get_credential_by_id(credential_id, server_id, db)
    password = decrypt(cred.password_encrypted)
    label = _resolve_label(cred)

    server = await db.scalar(select(Server).where(Server.id == server_id))

    if cred.db_type == "postgres":
        live = await _query_postgres(cred.host, cred.port, cred.username, password)
    else:
        live = await _query_mysql(cred.host, cred.port, cred.username, password)

    hw = await _get_server_hw(db, server_id)
    conn_metrics = await _get_conn_metrics(db, server_id, label, cred.db_type)
    backup = await _get_backup(db, server_id)
    replication = await _get_replication(db, server_id, label, cred)

    return {
        "reachable": live.get("reachable", False),
        "db": {
            "type": cred.db_type,
            "version": live.get("version"),
            "host": cred.host,
            "port": cred.port,
            "uptime_seconds": live.get("uptime_seconds"),
            "data_directory": live.get("data_directory"),
            "character_set": live.get("character_set"),
            "collation": live.get("collation"),
            "time_zone": live.get("time_zone"),
            "size_bytes": live.get("size_bytes"),
        },
        "server": {
            "name": server.name if server else None,
            "os": server.os_distro if server else None,
            "cpu_cores": int(hw["system.n_cpus"]) if "system.n_cpus" in hw else None,
            "ram_bytes": int(hw["mem.total"]) if "mem.total" in hw else None,
            "disk_total_bytes": int(hw["disk.total"]) if "disk.total" in hw else None,
            "disk_free_bytes": int(hw["disk.free"]) if "disk.free" in hw else None,
        },
        "connections": {
            "current": conn_metrics["current"],
            "max": conn_metrics["max"],
            "ssl_enabled": live.get("ssl_enabled", False),
            "ssl_version": live.get("ssl_version"),
        },
        "storage": {
            "total_databases": live.get("total_databases"),
            "total_tables": live.get("total_tables"),
            "largest_db": live.get("largest_db"),
            "largest_table": live.get("largest_table"),
            "used_bytes": live.get("size_bytes"),
            "free_bytes": int(hw["disk.free"]) if "disk.free" in hw else None,
        },
        "replication": replication,
        "backup": backup,
    }
