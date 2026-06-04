"""Service Monitoring router (spec 06 §10).

CRUD + read endpoints for services, incidents, check history, uptime timeline,
response-time series, plus the public /status data endpoints. Admin-gated
writes (canEdit = isAdmin). Probe jobs are (de)registered on create/update/
delete via app.services.probe.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AdminUser, CurrentUser
from app.models.organization import Organization
from app.models.other import Alert, Incident, Service
from app.models.server import Server
from app.models.user import UserOrganization
from app.schemas.service import ServiceCreate, ServiceOut, ServiceUpdate
from app.services import probe

router = APIRouter(tags=["services"])

# Range → time_bucket spec for the response-time chart (spec 06 §5.4).
_RANGE_BUCKET = {
    "1h": ("1 hour", "1 minute"),
    "6h": ("6 hours", "1 minute"),
    "24h": ("24 hours", "1 minute"),
    "7d": ("7 days", "1 hour"),
    "30d": ("30 days", "1 hour"),
}


# ── Access guards ───────────────────────────────────────────────────────────


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


async def _get_accessible_service(service_id: str, user, db: AsyncSession) -> Service:
    service = await db.scalar(select(Service).where(Service.id == service_id))
    if not service:
        raise HTTPException(404, detail={"error": "not_found", "message": "Service not found."})
    server = await db.get(Server, service.server_id)
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})
    if user.role != "admin":
        membership = await db.scalar(
            select(UserOrganization).where(
                UserOrganization.user_id == user.id,
                UserOrganization.org_id == server.org_id,
            )
        )
        if not membership:
            raise HTTPException(403, detail={"error": "forbidden", "message": "Access denied."})
    return service


async def _get_admin_service(service_id: str, db: AsyncSession) -> Service:
    service = await db.scalar(select(Service).where(Service.id == service_id))
    if not service:
        raise HTTPException(404, detail={"error": "not_found", "message": "Service not found."})
    return service


# ── Uptime / response aggregation helpers ───────────────────────────────────


async def _uptime_pct(db: AsyncSession, service_id: str, interval: str) -> float | None:
    """up_count / total_count * 100 over the window. None if no checks."""
    row = (
        await db.execute(
            text(
                "SELECT COUNT(*) AS total, "
                "COUNT(*) FILTER (WHERE status = 'up') AS up "
                "FROM service_checks "
                f"WHERE service_id = :sid AND time >= now() - INTERVAL '{interval}'"
            ),
            {"sid": service_id},
        )
    ).one()
    total = row.total or 0
    if total == 0:
        return None
    return round((row.up or 0) / total * 100, 2)


async def _avg_response_24h(db: AsyncSession, service_id: str) -> int | None:
    avg = await db.scalar(
        text(
            "SELECT AVG(response_time_ms) FROM service_checks "
            "WHERE service_id = :sid AND status = 'up' "
            "AND time >= now() - INTERVAL '24 hours'"
        ),
        {"sid": service_id},
    )
    return int(round(avg)) if avg is not None else None


async def _open_incident_id(db: AsyncSession, service_id: str) -> str | None:
    inc = await db.scalar(
        select(Incident.id)
        .where(Incident.service_id == service_id, Incident.resolved_at.is_(None))
        .order_by(Incident.started_at.desc())
        .limit(1)
    )
    return str(inc) if inc else None


async def _service_to_out(service: Service, server_name: str, db: AsyncSession) -> ServiceOut:
    sid = str(service.id)
    return ServiceOut(
        id=sid,
        server_id=str(service.server_id),
        server_name=server_name,
        name=service.name,
        type=service.type,
        url=service.url,
        port=service.port,
        expected_status=service.expected_status,
        interval_sec=service.interval_sec,
        timeout_sec=service.timeout_sec,
        is_active=service.is_active,
        is_public=service.is_public,
        ignore_ssl_errors=service.ignore_ssl_errors,
        last_status=service.last_status,
        last_checked=service.last_checked,
        consecutive_failures=service.consecutive_failures or 0,
        uptime_24h=await _uptime_pct(db, sid, "24 hours"),
        uptime_7d=await _uptime_pct(db, sid, "7 days"),
        avg_response_ms_24h=await _avg_response_24h(db, sid),
        open_incident_id=await _open_incident_id(db, sid),
    )


# ── List / detail ───────────────────────────────────────────────────────────


@router.get("/api/organizations/{org_id}/services", response_model=list[ServiceOut])
async def list_services(org_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_org_access(org_id, user, db)
    rows = (
        await db.execute(
            select(Service, Server.name)
            .join(Server, Service.server_id == Server.id)
            .where(Server.org_id == org_id, Server.is_active == True)  # noqa: E712
            .order_by(Server.name, Service.name)
        )
    ).all()
    return [await _service_to_out(svc, server_name, db) for svc, server_name in rows]


@router.get("/api/servers/{server_id}/monitoring", response_model=list[ServiceOut])
async def list_server_monitoring(
    server_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    server = await db.get(Server, server_id)
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})
    if user.role != "admin":
        membership = await db.scalar(
            select(UserOrganization).where(
                UserOrganization.user_id == user.id,
                UserOrganization.org_id == server.org_id,
            )
        )
        if not membership:
            raise HTTPException(403, detail={"error": "forbidden", "message": "Access denied."})
    rows = (
        await db.execute(
            select(Service).where(Service.server_id == server_id).order_by(Service.name)
        )
    ).scalars().all()
    return [await _service_to_out(svc, server.name, db) for svc in rows]


@router.get("/api/services/{service_id}", response_model=ServiceOut)
async def get_service(service_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    service = await _get_accessible_service(service_id, user, db)
    server = await db.get(Server, service.server_id)
    return await _service_to_out(service, server.name if server else "", db)


# ── Create / update / delete (Admin) ────────────────────────────────────────


@router.post("/api/services", status_code=201, response_model=ServiceOut)
async def create_service(body: ServiceCreate, user: AdminUser, db: AsyncSession = Depends(get_db)):
    server = await db.scalar(
        select(Server).where(Server.id == body.server_id, Server.is_active == True)  # noqa: E712
    )
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})

    # Type-specific field validation (spec §4.2).
    if body.type == "http":
        if not body.url or not (body.url.startswith("http://") or body.url.startswith("https://")):
            raise HTTPException(422, detail={"error": "validation_error", "message": "A valid http:// or https:// URL is required."})
        if len(body.url) > 500:
            raise HTTPException(422, detail={"error": "validation_error", "message": "URL is too long (max 500)."})
        expected_status = body.expected_status or 200
        url = body.url
        port = None
    else:  # tcp / db — host stored in url, port required
        if not body.url:
            raise HTTPException(422, detail={"error": "validation_error", "message": "Host is required."})
        if body.port is None:
            raise HTTPException(422, detail={"error": "validation_error", "message": "Port is required."})
        url = body.url.strip()
        port = body.port
        expected_status = None

    service = Service(
        server_id=body.server_id,
        name=body.name,
        type=body.type,
        url=url,
        port=port,
        expected_status=expected_status,
        interval_sec=body.interval_sec,
        timeout_sec=body.timeout_sec,
        is_active=body.is_active,
        is_public=body.is_public,
        ignore_ssl_errors=body.ignore_ssl_errors,
        consecutive_failures=0,
    )
    db.add(service)
    await db.commit()
    await db.refresh(service)

    # Schedule the probe job + fire one immediate check (spec §4.4) if active.
    if service.is_active:
        probe.register_probe_job(str(service.id), service.interval_sec)
        import asyncio

        asyncio.create_task(probe.probe_now(str(service.id)))

    return await _service_to_out(service, server.name, db)


@router.patch("/api/services/{service_id}", response_model=ServiceOut)
async def update_service(
    service_id: str, body: ServiceUpdate, user: AdminUser, db: AsyncSession = Depends(get_db)
):
    service = await _get_admin_service(service_id, db)

    if body.name is not None:
        service.name = body.name
    if body.url is not None:
        service.url = body.url
    if body.port is not None:
        service.port = body.port
    if body.expected_status is not None:
        service.expected_status = body.expected_status
    if body.interval_sec is not None:
        service.interval_sec = body.interval_sec
    if body.timeout_sec is not None:
        service.timeout_sec = body.timeout_sec
    if body.is_public is not None:
        service.is_public = body.is_public
    if body.ignore_ssl_errors is not None:
        service.ignore_ssl_errors = body.ignore_ssl_errors
    if body.is_active is not None:
        service.is_active = body.is_active

    await db.commit()
    await db.refresh(service)

    # Reconcile the probe job (interval change / pause / resume).
    if service.is_active:
        probe.register_probe_job(str(service.id), service.interval_sec)
    else:
        probe.unregister_probe_job(str(service.id))

    server = await db.get(Server, service.server_id)
    return await _service_to_out(service, server.name if server else "", db)


@router.delete("/api/services/{service_id}", status_code=204)
async def delete_service(service_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)):
    service = await _get_admin_service(service_id, db)

    probe.unregister_probe_job(str(service.id))

    # Resolve any open alerts (service_id is SET NULL on delete; resolve first).
    open_alerts = (
        await db.execute(
            select(Alert).where(
                Alert.service_id == service.id,
                Alert.state.in_(["firing", "acknowledged", "snoozed", "suppressed"]),
            )
        )
    ).scalars().all()
    for alert in open_alerts:
        alert.state = "resolved"
        alert.resolved_at = datetime.now(timezone.utc)

    # Incidents + service_checks rows cascade via FK ON DELETE CASCADE.
    await db.delete(service)
    await db.commit()
    return None


# ── Incidents ───────────────────────────────────────────────────────────────


@router.get("/api/services/{service_id}/incidents")
async def list_incidents(
    service_id: str,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    await _get_accessible_service(service_id, user, db)
    page_size = 20
    rows = (
        await db.execute(
            select(Incident)
            .where(
                Incident.service_id == service_id,
                Incident.started_at >= func.now() - text("INTERVAL '90 days'"),
            )
            .order_by(Incident.resolved_at.is_(None).desc(), Incident.started_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return {
        "page": page,
        "page_size": page_size,
        "incidents": [
            {
                "id": str(inc.id),
                "started_at": inc.started_at.isoformat() if inc.started_at else None,
                "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
                "duration_sec": inc.duration_sec,
            }
            for inc in rows
        ],
    }


# ── Check history (cursor-paginated) ────────────────────────────────────────


@router.get("/api/services/{service_id}/checks")
async def list_checks(
    service_id: str,
    user: CurrentUser,
    cursor: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    await _get_accessible_service(service_id, user, db)
    page_size = 50
    params: dict = {"sid": service_id, "lim": page_size + 1}
    cursor_clause = ""
    if cursor:
        cursor_clause = " AND time < :cursor "
        params["cursor"] = cursor

    rows = (
        await db.execute(
            text(
                "SELECT time, status, response_time_ms FROM service_checks "
                f"WHERE service_id = :sid {cursor_clause} "
                "ORDER BY time DESC LIMIT :lim"
            ),
            params,
        )
    ).all()

    has_more = len(rows) > page_size
    rows = rows[:page_size]
    next_cursor = rows[-1].time.isoformat() if has_more and rows else None

    return {
        "checks": [
            {
                "time": r.time.isoformat(),
                "status": r.status,
                "response_time_ms": r.response_time_ms,
            }
            for r in rows
        ],
        "next_cursor": next_cursor,
    }


# ── 90-day uptime timeline ──────────────────────────────────────────────────


@router.get("/api/services/{service_id}/uptime-timeline")
async def uptime_timeline(
    service_id: str,
    user: CurrentUser,
    days: int = Query(90, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    await _get_accessible_service(service_id, user, db)
    rows = (
        await db.execute(
            text(
                "SELECT time_bucket('1 day', time) AS day, "
                "COUNT(*) AS total, "
                "COUNT(*) FILTER (WHERE status = 'up') AS up "
                "FROM service_checks "
                f"WHERE service_id = :sid AND time >= now() - INTERVAL '{days} days' "
                "GROUP BY day ORDER BY day ASC"
            ),
            {"sid": service_id},
        )
    ).all()

    out = []
    for r in rows:
        total = r.total or 0
        up = r.up or 0
        uptime_pct = round(up / total * 100, 2) if total else 100.0
        down_minutes = total - up  # 1 check ≈ 1 minute at default interval
        out.append(
            {
                "date": r.day.date().isoformat(),
                "uptime_pct": uptime_pct,
                "down_minutes": down_minutes,
            }
        )
    return out


# ── Response-time chart ─────────────────────────────────────────────────────


@router.get("/api/services/{service_id}/response-time")
async def response_time(
    service_id: str,
    user: CurrentUser,
    range: str = Query("24h"),
    db: AsyncSession = Depends(get_db),
):
    await _get_accessible_service(service_id, user, db)
    if range not in _RANGE_BUCKET:
        raise HTTPException(400, detail={"error": "validation_error", "message": f"Invalid range: {range}"})
    window, bucket = _RANGE_BUCKET[range]

    rows = (
        await db.execute(
            text(
                f"SELECT time_bucket(INTERVAL '{bucket}', time) AS bucket_time, "
                "AVG(response_time_ms) AS avg_ms, "
                "percentile_cont(0.95) WITHIN GROUP (ORDER BY response_time_ms) AS p95_ms "
                "FROM service_checks "
                f"WHERE service_id = :sid AND status = 'up' "
                f"AND time >= now() - INTERVAL '{window}' "
                "GROUP BY bucket_time ORDER BY bucket_time ASC"
            ),
            {"sid": service_id},
        )
    ).all()

    return {
        "range": range,
        "data": [
            {
                "time": r.bucket_time.isoformat(),
                "avg_ms": int(round(r.avg_ms)) if r.avg_ms is not None else None,
                "p95_ms": int(round(r.p95_ms)) if r.p95_ms is not None else None,
            }
            for r in rows
        ],
    }


# ── Public status page data (no auth) ───────────────────────────────────────


@router.get("/api/public/services")
async def public_services(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Service).where(Service.is_public == True)  # noqa: E712
        )
    ).scalars().all()
    out = []
    for svc in rows:
        sid = str(svc.id)
        out.append(
            {
                "id": sid,
                "name": svc.name,
                "last_status": svc.last_status,
                "uptime_30d": await _uptime_pct(db, sid, "30 days"),
                "open_incident_id": await _open_incident_id(db, sid),
            }
        )
    return out


@router.get("/api/public/services/{service_id}/uptime")
async def public_uptime(
    service_id: str,
    days: int = Query(90, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    """90-day per-day uptime timeline for a public service (no auth, is_public only)."""
    svc = await db.scalar(
        select(Service).where(
            Service.id == service_id,
            Service.is_public == True,  # noqa: E712
        )
    )
    if not svc:
        raise HTTPException(404, detail={"error": "not_found", "message": "Service not found."})
    rows = (
        await db.execute(
            text(
                "SELECT time_bucket('1 day', time) AS day, "
                "COUNT(*) AS total, "
                "COUNT(*) FILTER (WHERE status = 'up') AS up "
                "FROM service_checks "
                f"WHERE service_id = :sid AND time >= now() - INTERVAL '{days} days' "
                "GROUP BY day ORDER BY day ASC"
            ),
            {"sid": service_id},
        )
    ).all()
    out = []
    for r in rows:
        total = r.total or 0
        up = r.up or 0
        uptime_pct = round(up / total * 100, 2) if total else 100.0
        out.append(
            {
                "date": r.day.date().isoformat(),
                "uptime_pct": uptime_pct,
                "down_minutes": total - up,
            }
        )
    return out


@router.get("/api/public/incidents")
async def public_incidents(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Incident, Service.name)
            .join(Service, Incident.service_id == Service.id)
            .where(
                Service.is_public == True,  # noqa: E712
                Incident.started_at >= func.now() - text("INTERVAL '90 days'"),
            )
            .order_by(Incident.started_at.desc())
            .limit(20)
        )
    ).all()
    return [
        {
            "id": str(inc.id),
            "service_name": name,
            "started_at": inc.started_at.isoformat() if inc.started_at else None,
            "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
            "duration_sec": inc.duration_sec,
        }
        for inc, name in rows
    ]
