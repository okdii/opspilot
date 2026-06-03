"""Log Viewer reads (spec 05).

GET /api/logs            — cursor-paginated log entries with filters
GET /api/logs/volume     — log volume per time bucket (stacked-bar chart)

The `server_logs` hypertable has no surrogate key, so each entry's `id` is a
deterministic hash of (time, server_id, source, message). The pagination cursor
encodes the last row's (time, id) so paging is stable even as new rows arrive.
"""
import base64
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import CurrentUser
from app.models.organization import Organization
from app.models.server import Server
from app.models.user import UserOrganization

router = APIRouter(prefix="/api/logs", tags=["logs"])

VALID_SOURCES = {
    "nginx_access", "nginx_error", "php_fpm", "php_app",
    "mariadb_error", "mariadb_slow", "syslog", "auth", "kernel",
}
VALID_SEVERITIES = {"debug", "info", "warn", "error", "fatal"}

MAX_LIMIT = 500
DEFAULT_LIMIT = 100

# range token -> default bucket size (seconds) for the volume chart (spec §5)
_DEFAULT_BUCKET = [
    (timedelta(minutes=15), 60),
    (timedelta(hours=1), 300),
    (timedelta(hours=6), 900),
    (timedelta(hours=24), 3600),
    (timedelta(days=7), 21600),
]


# Synthetic per-row id computed *in Postgres* (md5 — pgcrypto/digest is not
# installed). Returned as a column and echoed back via the cursor, so Python
# never has to reproduce Postgres timestamp formatting. Used both as the public
# `id` and as the pagination tie-break for equal timestamps.
_ROW_ID_SQL = "md5(l.time::text || '|' || l.server_id::text || '|' || l.source || '|' || l.message)"


def _encode_cursor(time: datetime, row_id: str) -> str:
    raw = json.dumps({"t": time.isoformat(), "id": row_id}).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode())
        obj = json.loads(raw)
        return datetime.fromisoformat(obj["t"]), obj["id"]
    except Exception:
        raise HTTPException(400, detail={"error": "bad_cursor", "message": "Invalid pagination cursor."})


def _parse_csv(value: str | None, allowed: set[str]) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip() and v.strip() in allowed]


def _parse_ts(value: str | None, default: datetime) -> datetime:
    if not value:
        return default
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, detail={"error": "bad_timestamp", "message": f"Invalid timestamp: {value}"})


async def _resolve_scope(
    user, db: AsyncSession,
    org_id: str | None, server_ids_raw: str | None,
) -> list[Server]:
    """Resolve the set of accessible servers the query targets, enforcing org
    membership for non-admins. Returns the Server rows in scope."""
    requested_ids = [s.strip() for s in (server_ids_raw or "").split(",") if s.strip()]

    if requested_ids:
        result = await db.execute(
            select(Server).where(Server.id.in_(requested_ids), Server.is_active == True)
        )
        servers = list(result.scalars().all())
        if not servers:
            raise HTTPException(404, detail={"error": "not_found", "message": "No matching servers."})
    elif org_id:
        org = await db.scalar(select(Organization).where(Organization.id == org_id))
        if not org:
            raise HTTPException(404, detail={"error": "not_found", "message": "Organization not found."})
        result = await db.execute(
            select(Server).where(Server.org_id == org_id, Server.is_active == True)
        )
        servers = list(result.scalars().all())
    else:
        raise HTTPException(422, detail={"error": "validation_error", "message": "org_id or server_ids is required."})

    if user.role != "admin":
        org_ids = {str(s.org_id) for s in servers}
        for oid in org_ids:
            membership = await db.scalar(
                select(UserOrganization).where(
                    UserOrganization.user_id == user.id,
                    UserOrganization.org_id == oid,
                )
            )
            if not membership:
                raise HTTPException(403, detail={"error": "forbidden", "message": "Access denied."})

    return servers


def _build_where(
    server_ids: list[str], sources: list[str], severities: list[str],
    search: str | None, frm: datetime, to: datetime,
) -> tuple[str, dict, list]:
    clauses = ["l.server_id IN :sids", "l.time >= :frm", "l.time <= :to"]
    params: dict = {"sids": server_ids, "frm": frm, "to": to}
    expanding = [bindparam("sids", expanding=True)]

    if sources:
        clauses.append("l.source IN :sources")
        params["sources"] = sources
        expanding.append(bindparam("sources", expanding=True))

    # nginx_access carries no severity. Severity filtering only restricts rows
    # that *have* a severity; access logs (severity unset/empty) always pass when
    # at least one severity is active (spec §4.3).
    if severities and len(severities) < len(VALID_SEVERITIES):
        clauses.append("(l.severity IN :severities OR l.severity = '' OR l.severity IS NULL OR l.source = 'nginx_access')")
        params["severities"] = severities
        expanding.append(bindparam("severities", expanding=True))

    if search and len(search) >= 2:
        clauses.append("to_tsvector('english', l.message) @@ websearch_to_tsquery('english', :search)")
        params["search"] = search

    return " AND ".join(clauses), params, expanding


@router.get("")
async def list_logs(
    user: CurrentUser,
    org_id: str | None = Query(None),
    server_ids: str | None = Query(None),
    sources: str | None = Query(None),
    severities: str | None = Query(None),
    search: str | None = Query(None),
    frm: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    cursor: str | None = Query(None),
    limit: int = Query(DEFAULT_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    servers = await _resolve_scope(user, db, org_id, server_ids)
    server_map = {str(s.id): s.name for s in servers}
    scope_ids = list(server_map.keys())

    limit = max(1, min(limit, MAX_LIMIT))
    now = datetime.now(timezone.utc)
    frm_dt = _parse_ts(frm, now - timedelta(hours=1))
    to_dt = _parse_ts(to, now)
    src_list = _parse_csv(sources, VALID_SOURCES)
    sev_list = _parse_csv(severities, VALID_SEVERITIES)

    where, params, expanding = _build_where(scope_ids, src_list, sev_list, search, frm_dt, to_dt)

    # Cursor: rows strictly older than (time, id). Tie-break on the synthetic id
    # (md5, computed in SQL) so equal-timestamp rows page deterministically.
    cursor_clause = ""
    if cursor:
        c_time, c_id = _decode_cursor(cursor)
        cursor_clause = (
            f" AND (l.time < :c_time OR (l.time = :c_time AND {_ROW_ID_SQL} < :c_id))"
        )
        params["c_time"] = c_time
        params["c_id"] = c_id

    params["lim"] = limit + 1  # fetch one extra to detect more pages

    stmt = text(f"""
        SELECT l.time, l.server_id, l.source, l.severity, l.message, l.raw,
               {_ROW_ID_SQL} AS row_id
        FROM server_logs l
        WHERE {where} {cursor_clause}
        ORDER BY l.time DESC, row_id DESC
        LIMIT :lim
    """).bindparams(*expanding)

    rows = (await db.execute(stmt, params)).all()

    has_more = len(rows) > limit
    limit_reached = False
    rows = rows[:limit]

    entries = []
    last_time = last_id = None
    for t, sid, source, severity, message, raw, rid in rows:
        sid_str = str(sid)
        fields = raw if isinstance(raw, dict) else {}
        entries.append({
            "id": rid,
            "time": t.isoformat(),
            "server_id": sid_str,
            "server_name": server_map.get(sid_str, sid_str),
            "source": source,
            "severity": (severity or None) if source != "nginx_access" else None,
            "message": message,
            "fields": fields,
        })
        last_time, last_id = t, rid

    next_cursor = None
    if has_more and last_time is not None and not limit_reached:
        next_cursor = _encode_cursor(last_time, last_id)

    # A full page that also exhausts the 500 cap signals "narrow your filters".
    if len(entries) >= MAX_LIMIT and has_more:
        limit_reached = True
        next_cursor = None

    return {
        "entries": entries,
        "next_cursor": next_cursor,
        "count": len(entries),
        "limit_reached": limit_reached,
    }


@router.get("/volume")
async def log_volume(
    user: CurrentUser,
    org_id: str | None = Query(None),
    server_ids: str | None = Query(None),
    sources: str | None = Query(None),
    severities: str | None = Query(None),
    search: str | None = Query(None),
    frm: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    bucket_seconds: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    servers = await _resolve_scope(user, db, org_id, server_ids)
    scope_ids = [str(s.id) for s in servers]

    now = datetime.now(timezone.utc)
    frm_dt = _parse_ts(frm, now - timedelta(hours=1))
    to_dt = _parse_ts(to, now)
    src_list = _parse_csv(sources, VALID_SOURCES)
    sev_list = _parse_csv(severities, VALID_SEVERITIES)

    if not bucket_seconds:
        span = to_dt - frm_dt
        bucket_seconds = 3600
        for max_span, bsec in _DEFAULT_BUCKET:
            if span <= max_span:
                bucket_seconds = bsec
                break
    bucket_seconds = max(60, min(bucket_seconds, 86400))

    where, params, expanding = _build_where(scope_ids, src_list, sev_list, search, frm_dt, to_dt)
    params["bsec"] = bucket_seconds

    stmt = text(f"""
        SELECT time_bucket(make_interval(secs => :bsec), l.time) AS bucket,
               CASE WHEN l.severity IN ('debug','info','warn','error','fatal')
                    THEN l.severity ELSE 'info' END AS sev,
               count(*) AS n
        FROM server_logs l
        WHERE {where}
        GROUP BY bucket, sev
        ORDER BY bucket ASC
    """).bindparams(*expanding)

    rows = (await db.execute(stmt, params)).all()

    buckets: dict[str, dict] = {}
    for bucket, sev, n in rows:
        key = bucket.isoformat()
        b = buckets.setdefault(key, {
            "time": key, "debug": 0, "info": 0, "warn": 0, "error": 0, "fatal": 0,
        })
        if sev in b:
            b[sev] += n

    return {"buckets": list(buckets.values()), "bucket_seconds": bucket_seconds}
