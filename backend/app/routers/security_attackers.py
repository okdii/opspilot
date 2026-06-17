"""Attacker Intelligence — security alerts/actions pivoted by source IP.

GET /api/servers/{server_id}/security/attackers              top attackers (paged, enriched)
GET /api/servers/{server_id}/security/attackers/{ip}/events  one attacker's event history
GET /api/servers/{server_id}/security/trend                  global attack volume per day
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import CurrentUser
from app.models.other import Alert, SecurityAction
from app.routers.security_events import SECURITY_TYPES, STAGE, STAGE_ORDER
from app.services import ip_intel as intel

router = APIRouter(prefix="/api/servers", tags=["security"])

_MIN_AWARE = datetime.min.replace(tzinfo=timezone.utc)


async def _check_access(server_id: str, user: CurrentUser, db: AsyncSession) -> None:
    from app.routers.servers import _assert_server_access
    await _assert_server_access(server_id, user, db)


async def _alerts_and_block_targets(
    db: AsyncSession, server_id: str
) -> tuple[list[Alert], dict[str, str]]:
    """All security alerts for the server, plus {alert_id: block_ip target} for the
    fallback attribution path (alerts whose message has no inline IP but which the
    responder mitigated with a block_ip)."""
    alerts = (await db.execute(
        select(Alert).where(Alert.server_id == server_id, Alert.type.in_(SECURITY_TYPES))
    )).scalars().all()
    block_targets: dict[str, str] = {}
    if alerts:
        rows = (await db.execute(
            select(SecurityAction.alert_id, SecurityAction.target)
            .where(SecurityAction.alert_id.in_([a.id for a in alerts]),
                   SecurityAction.action_type == "block_ip",
                   SecurityAction.target.is_not(None))
        )).all()
        for alert_id, target in rows:
            if alert_id is not None:
                block_targets.setdefault(str(alert_id), target)
    return alerts, block_targets


def _resolve_ip(a: Alert, block_targets: dict[str, str]) -> str | None:
    """Approach A: inline IP in the message first, else the linked block_ip target.
    Private/loopback/reserved IPs are excluded — this is external-attacker intelligence."""
    ip = intel.extract_inline_ip(a.message) or block_targets.get(str(a.id))
    return ip if ip and intel.is_public_ip(ip) else None


@router.get("/{server_id}/security/attackers")
async def attackers(
    server_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    sort: str = Query("last_seen"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    await _check_access(server_id, user, db)
    alerts, block_targets = await _alerts_and_block_targets(db, server_id)

    groups: dict[str, dict] = {}
    for a in alerts:
        ip = _resolve_ip(a, block_targets)
        if ip is None:
            continue
        at = a.sent_at
        g = groups.get(ip)
        if g is None:
            g = groups[ip] = {
                "ip": ip, "event_count": 0, "first_seen": at, "last_seen": at,
                "stages": set(), "critical_count": 0, "warning_count": 0,
                # _last: internal sort key (latest sent_at); excluded by the _out projection.
                "last_type": a.type, "last_message": a.message, "_last": at,
            }
        g["event_count"] += 1
        stage = STAGE.get(a.type)
        if stage:
            g["stages"].add(stage)
        if a.severity == "critical":
            g["critical_count"] += 1
        elif a.severity == "warning":
            g["warning_count"] += 1
        if at is not None and (g["first_seen"] is None or at < g["first_seen"]):
            g["first_seen"] = at
        if at is not None and (g["_last"] is None or at > g["_last"]):
            g["_last"] = at
            g["last_seen"] = at
            g["last_type"] = a.type
            g["last_message"] = a.message

    # Mitigations + blocked, keyed by IP (block_ip actions target the IP directly).
    # "blocked" means CURRENTLY blocked, so it requires an executed block that was
    # not since reverted: both manual undo and TTL auto-expiry stamp reverted_at and
    # move status off "executed" (-> "reverted"/"expired"). reverted_at IS NULL is the
    # single source of truth for "still in effect". mitigations stays a historical
    # total (every block_ip ever aimed at this IP), so reverted blocks still count.
    mrows = (await db.execute(
        select(SecurityAction.target, SecurityAction.status,
               SecurityAction.reverted_at, func.count())
        .where(SecurityAction.server_id == server_id,
               SecurityAction.action_type == "block_ip",
               SecurityAction.target.is_not(None))
        .group_by(SecurityAction.target, SecurityAction.status, SecurityAction.reverted_at)
    )).all()
    mit_count: dict[str, int] = defaultdict(int)
    blocked: set[str] = set()
    for target, status, reverted_at, count in mrows:
        mit_count[target] += count
        if status == "executed" and reverted_at is None:
            blocked.add(target)
    for ip, g in groups.items():
        g["mitigations"] = mit_count.get(ip, 0)
        g["blocked"] = ip in blocked

    items = list(groups.values())
    if sort == "events":
        items.sort(key=lambda g: g["event_count"], reverse=True)
    elif sort == "severity":
        items.sort(key=lambda g: (g["critical_count"], g["event_count"]), reverse=True)
    else:  # last_seen (default)
        items.sort(key=lambda g: g["_last"] or _MIN_AWARE, reverse=True)

    total = len(items)
    page = items[offset:offset + limit]
    intel_map = await intel.enrich_many(db, [g["ip"] for g in page])

    def _out(g: dict) -> dict:
        i = intel_map.get(g["ip"])
        return {
            "ip": g["ip"],
            "event_count": g["event_count"],
            "first_seen": g["first_seen"],
            "last_seen": g["last_seen"],
            "stages": [s for s in STAGE_ORDER if s in g["stages"]],
            "critical_count": g["critical_count"],
            "warning_count": g["warning_count"],
            "mitigations": g["mitigations"],
            "blocked": g["blocked"],
            "last_type": g["last_type"],
            "last_message": g["last_message"],
            "intel": None if i is None else {
                "abuse_score": i.abuse_score,
                "country_code": i.country_code,
                "isp": i.isp,
                "usage_type": i.usage_type,
                "total_reports": i.total_reports,
                "last_reported_at": i.last_reported_at,
            },
        }

    return {"items": [_out(g) for g in page], "total": total}


@router.get("/{server_id}/security/attackers/{ip}/events")
async def attacker_events(
    server_id: str,
    ip: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Security event history for one attacker IP (newest first), same row shape
    as /security/events so the expanded row can render a compact event list."""
    await _check_access(server_id, user, db)
    alerts, block_targets = await _alerts_and_block_targets(db, server_id)
    matched = [a for a in alerts if _resolve_ip(a, block_targets) == ip]
    matched.sort(key=lambda a: a.sent_at or _MIN_AWARE, reverse=True)
    total = len(matched)
    page = matched[offset:offset + limit]
    return {
        "items": [
            {
                "id": str(a.id), "type": a.type, "stage": STAGE.get(a.type, "—"),
                "severity": a.severity, "message": a.message,
                "state": a.state, "at": a.sent_at,
            }
            for a in page
        ],
        "total": total,
    }


@router.get("/{server_id}/security/trend")
async def security_trend(
    server_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=90),
):
    """Global attack volume per day, stacked by severity, zero-filled across the
    full window so the chart has a continuous axis."""
    await _check_access(server_id, user, db)
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    day = func.date_trunc("day", Alert.sent_at, "UTC")
    rows = (await db.execute(
        select(day.label("day"), Alert.severity, func.count())
        .where(Alert.server_id == server_id, Alert.type.in_(SECURITY_TYPES),
               Alert.sent_at >= since)
        .group_by(day, Alert.severity)
    )).all()

    buckets: dict[str, dict] = {}
    for d, severity, count in rows:
        key = d.date().isoformat()
        b = buckets.setdefault(key, {"date": key, "critical": 0, "warning": 0})
        if severity in ("critical", "warning"):
            b[severity] += count

    start = (now - timedelta(days=days - 1)).date()
    return [
        buckets.get((start + timedelta(days=n)).isoformat(),
                    {"date": (start + timedelta(days=n)).isoformat(), "critical": 0, "warning": 0})
        for n in range(days)
    ]
