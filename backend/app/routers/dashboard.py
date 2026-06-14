"""Global dashboard read endpoints (spec 04 §2).

Servers + live metrics are real now; services/alerts/ssl summary blocks return
zeros until their phases (each isolated for a one-line swap later)."""
from fastapi import APIRouter, Depends
from sqlalchemy import bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AdminUser, CurrentUser
from app.models.organization import Organization
from app.models.other import Alert
from app.models.server import Server
from app.routers.servers import _assert_org_access, _compute_status

router = APIRouter(prefix="/api/organizations", tags=["dashboard"])
global_router = APIRouter(tags=["dashboard"])

CPU_METRIC = "cpu.usage_active"
RAM_METRIC = "mem.used_percent"
DISK_METRIC = "disk.used_percent"


@router.get("/{org_id}/dashboard")
async def get_dashboard(org_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_org_access(org_id, user, db)

    servers = (
        await db.execute(
            select(Server).where(Server.org_id == org_id, Server.is_active == True)
        )
    ).scalars().all()
    ids = [str(s.id) for s in servers]

    # Latest value per (server, metric) for the three card metrics.
    latest: dict[tuple[str, str], float] = {}
    if ids:
        stmt = text(
            """
            SELECT server_id::text AS sid, metric_name, last(value, time) AS value
            FROM server_metrics
            WHERE server_id IN :ids
              AND metric_name IN :metrics
              AND time > NOW() - INTERVAL '24 hours'
              AND (metric_name <> :disk OR labels->>'path' = '/')
            GROUP BY server_id, metric_name
            """
        ).bindparams(bindparam("ids", expanding=True), bindparam("metrics", expanding=True))
        result = await db.execute(
            stmt,
            {"ids": ids, "metrics": [CPU_METRIC, RAM_METRIC, DISK_METRIC], "disk": DISK_METRIC},
        )
        for sid, mname, value in result:
            latest[(sid, mname)] = value

    server_out = []
    online = offline = maintenance = 0
    for s in servers:
        status = _compute_status(s)
        if status == "online":
            online += 1
        elif status == "maintenance":
            maintenance += 1
        else:
            offline += 1
        sid = str(s.id)
        server_out.append({
            "id": sid,
            "name": s.name,
            "host": s.host,
            "tags": s.tags or [],
            "status": status,
            "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None,
            "metrics": {
                "cpu": latest.get((sid, CPU_METRIC)),
                "ram": latest.get((sid, RAM_METRIC)),
                "disk": latest.get((sid, DISK_METRIC)),
            },
        })

    # Alert counts scoped to this org's servers (zeros until Phase 8 populates).
    alerts = {"firing": 0, "snoozed": 0, "acknowledged": 0}
    if ids:
        rows = await db.execute(
            select(Alert.state, func.count())
            .where(Alert.server_id.in_(ids), Alert.state.in_(["firing", "snoozed", "acknowledged"]))
            .group_by(Alert.state)
        )
        for state, count in rows:
            alerts[state] = count

    return {
        "summary": {
            "servers": {"total": len(servers), "online": online, "offline": offline, "maintenance": maintenance},
            "services": {"up": 0, "down": 0},
            "alerts": alerts,
            "ssl_domains": {"expiring": 0, "expired": 0},
        },
        "servers": server_out,
    }


@router.get("/{org_id}/alerts/recent")
async def get_recent_alerts(org_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_org_access(org_id, user, db)
    rows = await db.execute(
        select(Alert, Server.name)
        .join(Server, Alert.server_id == Server.id)
        .where(Server.org_id == org_id)
        .order_by(Alert.sent_at.desc())
        .limit(10)
    )
    return [
        {
            "id": str(a.id),
            "server_name": name,
            "severity": a.severity,
            "message": a.message,
            "state": a.state,
            "sent_at": a.sent_at.isoformat() if a.sent_at else None,
        }
        for a, name in rows
    ]


@global_router.get("/api/dashboard/global")
async def get_global_dashboard(_user: AdminUser, db: AsyncSession = Depends(get_db)):
    """Cross-org summary stats for admin users. Returns one entry per org."""
    # Fetch all orgs sorted by name
    orgs = (
        await db.execute(select(Organization).order_by(Organization.name))
    ).scalars().all()

    if not orgs:
        return []

    # Fetch all active servers grouped by org
    servers_rows = (
        await db.execute(
            select(Server).where(Server.is_active == True)
        )
    ).scalars().all()

    # Build per-org server buckets
    servers_by_org: dict[str, list[Server]] = {str(o.id): [] for o in orgs}
    for s in servers_rows:
        oid = str(s.org_id)
        if oid in servers_by_org:
            servers_by_org[oid].append(s)

    # Collect all server ids for alert query
    all_server_ids = [str(s.id) for s in servers_rows]

    # Fetch alert counts grouped by (server_id, state) — avoids loading all rows
    firing_by_server: dict[str, int] = {}
    total_by_server: dict[str, int] = {}
    if all_server_ids:
        alert_rows = (
            await db.execute(
                select(Alert.server_id, Alert.state, func.count())
                .where(
                    Alert.server_id.in_(all_server_ids),
                    Alert.state.in_(["firing", "snoozed", "acknowledged"]),
                )
                .group_by(Alert.server_id, Alert.state)
            )
        ).all()
        for server_id, state, count in alert_rows:
            sid = str(server_id)
            total_by_server[sid] = total_by_server.get(sid, 0) + count
            if state == "firing":
                firing_by_server[sid] = firing_by_server.get(sid, 0) + count

    result = []
    for org in orgs:
        oid = str(org.id)
        org_servers = servers_by_org.get(oid, [])
        online = offline = 0
        for s in org_servers:
            status = _compute_status(s)
            if status == "online":
                online += 1
            elif status == "offline":
                offline += 1
        # maintenance and pending are intentionally excluded from both counts

        org_server_ids = {str(s.id) for s in org_servers}
        total_alerts = sum(total_by_server.get(sid, 0) for sid in org_server_ids)
        firing_alerts = sum(firing_by_server.get(sid, 0) for sid in org_server_ids)

        result.append({
            "org": {"id": oid, "name": org.name},
            "servers": {"total": len(org_servers), "online": online, "offline": offline},
            "alerts": {"total": total_alerts, "firing": firing_alerts},
        })

    return result
