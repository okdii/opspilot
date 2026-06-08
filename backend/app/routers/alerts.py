"""Alert read + action endpoints (spec 10 §14, §10) — Slice D.

- GET  /api/organizations/{org_id}/alerts            active (firing|acked|snoozed[|suppressed])
- GET  /api/organizations/{org_id}/alerts/history    resolved, cursor-paginated
- GET  /api/organizations/{org_id}/alerts/frequency  last-30d daily critical/warning counts
- POST /api/alerts/{id}/acknowledge                  ack (admin/operator)
- POST /api/alerts/{id}/snooze                        snooze (admin/operator)

Also exposes ``snooze_expiry_tick`` — a 60s job coroutine (wired by the
coordinator) that returns snoozed alerts whose ``snoozed_until`` has passed back
to ``firing`` and broadcasts ``alert_updated`` (spec §16).

``GET /alerts/recent`` already lives in routers/dashboard.py — not duplicated here.
"""
import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import CurrentUser
from app.models.other import Alert, Domain, Service, SSLCert
from app.models.server import Server
from app.models.user import User
from app.routers.servers import _assert_org_access
from app.services import alerting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["alerts"])

# States considered "active" (not resolved). Suppressed is visible per spec §6.1
# ("everything not resolved") but sorts last.
ACTIVE_STATES = ("firing", "acknowledged", "snoozed", "suppressed")
_STATE_ORDER = {"firing": 0, "acknowledged": 1, "snoozed": 2, "suppressed": 3}

HISTORY_PAGE_SIZE = 50


# ---------------------------------------------------------------------------
# Role guard — ack/snooze are admin or operator (spec §14).
# ---------------------------------------------------------------------------
async def require_operator_or_admin(user: CurrentUser) -> User:
    if user.role not in ("admin", "operator"):
        raise HTTPException(
            403, detail={"error": "forbidden", "message": "Operator or Admin access required."}
        )
    return user


WriteUser = Annotated[User, Depends(require_operator_or_admin)]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class SnoozeIn(BaseModel):
    minutes: int | None = None
    until: datetime | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.minutes is None and self.until is None:
            raise ValueError("Provide either 'minutes' or 'until'.")
        if self.minutes is not None and self.minutes <= 0:
            raise ValueError("'minutes' must be positive.")
        return self


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _iso(dt: datetime | None) -> str | None:
    aware = _aware(dt)
    return aware.isoformat() if aware else None


def _alert_out(
    a: Alert,
    server_name: str | None = None,
    service_name: str | None = None,
    domain_name: str | None = None,
) -> dict:
    return {
        "id": str(a.id),
        "type": a.type,
        "severity": a.severity,
        "message": a.message,
        "state": a.state,
        "server_id": str(a.server_id) if a.server_id else None,
        "service_id": str(a.service_id) if a.service_id else None,
        "domain_id": str(a.domain_id) if a.domain_id else None,
        "ssl_cert_id": str(a.ssl_cert_id) if a.ssl_cert_id else None,
        "job_id": str(a.job_id) if a.job_id else None,
        "server_name": server_name,
        "service_name": service_name,
        "domain_name": domain_name,
        "sent_at": _iso(a.sent_at),
        "acknowledged_at": _iso(a.acknowledged_at),
        "snoozed_until": _iso(a.snoozed_until),
        "resolved_at": _iso(a.resolved_at),
        "consecutive_clear_count": a.consecutive_clear_count,
    }


async def _get_alert_for_user(alert_id: str, user: User, db: AsyncSession) -> Alert:
    alert = await db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(404, detail={"error": "not_found", "message": "Alert not found."})
    org_id, _ = await alerting._resolve_org_and_server_name(db, alert)
    if org_id is None:
        # Orphaned subject (e.g. server deleted) — admins only.
        if user.role != "admin":
            raise HTTPException(403, detail={"error": "forbidden", "message": "Access denied."})
        return alert
    await _assert_org_access(org_id, user, db)
    return alert


def _encode_cursor(sent_at: datetime, alert_id: str) -> str:
    raw = f"{_aware(sent_at).isoformat()}|{alert_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts, alert_id = raw.split("|", 1)
        return datetime.fromisoformat(ts), alert_id
    except Exception:
        raise HTTPException(400, detail={"error": "bad_cursor", "message": "Invalid cursor."})


# ---------------------------------------------------------------------------
# GET active alerts
# ---------------------------------------------------------------------------
@router.get("/organizations/{org_id}/alerts")
async def list_active_alerts(
    org_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    await _assert_org_access(org_id, user, db)

    rows = (
        await db.execute(
            select(Alert, Server.name, Service.name, Domain.domain)
            .join(Server, Alert.server_id == Server.id)
            .outerjoin(Service, Alert.service_id == Service.id)
            .outerjoin(Domain, Alert.domain_id == Domain.id)
            .where(Server.org_id == org_id, Alert.state.in_(ACTIVE_STATES))
        )
    ).all()

    out = [
        (a, _alert_out(a, server_name=sname, service_name=svcname, domain_name=domname))
        for a, sname, svcname, domname in rows
    ]
    # firing → acked → snoozed → suppressed, then newest first within each group.
    out.sort(
        key=lambda pair: (
            _STATE_ORDER.get(pair[1]["state"], 99),
            -(_aware(pair[0].sent_at).timestamp() if pair[0].sent_at else 0),
        )
    )
    return [d for _, d in out]


# ---------------------------------------------------------------------------
# GET history (resolved, cursor-paginated)
# ---------------------------------------------------------------------------
@router.get("/organizations/{org_id}/alerts/history")
async def list_alert_history(
    org_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    cursor: str | None = None,
    server_id: str | None = None,
    type: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    search: str | None = None,
    limit: int = Query(HISTORY_PAGE_SIZE, ge=1, le=200),
):
    await _assert_org_access(org_id, user, db)

    conds = [Server.org_id == org_id, Alert.state == "resolved"]
    if server_id:
        conds.append(Alert.server_id == server_id)
    if type:
        conds.append(Alert.type == type)
    if start:
        conds.append(Alert.sent_at >= start)
    if end:
        conds.append(Alert.sent_at <= end)
    if search:
        conds.append(Alert.message.ilike(f"%{search}%"))
    if cursor:
        c_sent, c_id = _decode_cursor(cursor)
        # keyset: (sent_at, id) strictly less than cursor (sent_at desc, id desc).
        conds.append(
            or_(
                Alert.sent_at < c_sent,
                and_(Alert.sent_at == c_sent, Alert.id < c_id),
            )
        )

    rows = (
        await db.execute(
            select(Alert, Server.name, Service.name, Domain.domain)
            .join(Server, Alert.server_id == Server.id)
            .outerjoin(Service, Alert.service_id == Service.id)
            .outerjoin(Domain, Alert.domain_id == Domain.id)
            .where(and_(*conds))
            .order_by(Alert.sent_at.desc(), Alert.id.desc())
            .limit(limit + 1)
        )
    ).all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        _alert_out(a, server_name=sname, service_name=svcname, domain_name=domname)
        for a, sname, svcname, domname in rows
    ]
    next_cursor = None
    if has_more and rows:
        last_alert = rows[-1][0]
        next_cursor = _encode_cursor(last_alert.sent_at, str(last_alert.id))
    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}


# ---------------------------------------------------------------------------
# GET frequency (last-30d daily critical/warning counts, zero-filled)
# ---------------------------------------------------------------------------
@router.get("/organizations/{org_id}/alerts/frequency")
async def alert_frequency(
    org_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    await _assert_org_access(org_id, user, db)

    stmt = text(
        """
        SELECT date_trunc('day', a.sent_at)::date AS day,
               a.severity AS severity,
               COUNT(*) AS cnt
        FROM alert a
        JOIN server s ON a.server_id = s.id
        WHERE s.org_id = :org_id
          AND a.sent_at >= now() - interval '30 days'
        GROUP BY day, a.severity
        """
    )
    result = await db.execute(stmt, {"org_id": org_id})

    counts: dict[str, dict[str, int]] = {}
    for day, severity, cnt in result:
        key = day.isoformat()
        bucket = counts.setdefault(key, {"critical": 0, "warning": 0})
        if severity in bucket:
            bucket[severity] = int(cnt)
        else:
            bucket[severity] = int(cnt)

    # zero-fill the 30-day window (oldest → newest)
    today = datetime.now(timezone.utc).date()
    out = []
    for offset in range(29, -1, -1):
        d = today - timedelta(days=offset)
        key = d.isoformat()
        bucket = counts.get(key, {})
        out.append(
            {
                "date": key,
                "critical": bucket.get("critical", 0),
                "warning": bucket.get("warning", 0),
            }
        )
    return out


# ---------------------------------------------------------------------------
# POST acknowledge
# ---------------------------------------------------------------------------
@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str, user: WriteUser, db: AsyncSession = Depends(get_db)
):
    alert = await _get_alert_for_user(alert_id, user, db)
    if alert.state == "resolved":
        raise HTTPException(
            409, detail={"error": "already_resolved", "message": "Alert already resolved."}
        )

    alert.state = "acknowledged"
    alert.acknowledged_at = alerting._now()
    await db.flush()

    org_id, server_name = await alerting._resolve_org_and_server_name(db, alert)
    await alerting._broadcast("alert_updated", alert, org_id, server_name)
    await db.commit()

    return _alert_out(alert, server_name=server_name)


# ---------------------------------------------------------------------------
# POST snooze
# ---------------------------------------------------------------------------
@router.post("/alerts/{alert_id}/snooze")
async def snooze_alert(
    alert_id: str, body: SnoozeIn, user: WriteUser, db: AsyncSession = Depends(get_db)
):
    alert = await _get_alert_for_user(alert_id, user, db)
    if alert.state == "resolved":
        raise HTTPException(
            409, detail={"error": "already_resolved", "message": "Alert already resolved."}
        )

    now = alerting._now()
    if body.until is not None:
        until = _aware(body.until)
        if until <= now:
            raise HTTPException(
                422, detail={"error": "past_until", "message": "'until' must be in the future."}
            )
    else:
        until = now + timedelta(minutes=body.minutes)

    alert.state = "snoozed"
    alert.snoozed_until = until
    await db.flush()

    org_id, server_name = await alerting._resolve_org_and_server_name(db, alert)
    await alerting._broadcast("alert_updated", alert, org_id, server_name)
    await db.commit()

    return _alert_out(alert, server_name=server_name)


# ---------------------------------------------------------------------------
# Snooze-expiry job coroutine (wired by coordinator @60s).
# ---------------------------------------------------------------------------
async def snooze_expiry_tick() -> None:
    """Return snoozed alerts whose ``snoozed_until`` has passed back to
    ``firing`` and broadcast ``alert_updated`` (spec §16).

    The evaluators handle re-firing email/dedup for the *condition*; this tick
    only flips the row's state so the alert reappears as active. If the
    condition has since cleared, the evaluator's clear-count logic resolves it
    on its own cadence.
    """
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        now = alerting._now()
        rows = (
            await db.execute(
                select(Alert).where(
                    Alert.state == "snoozed",
                    Alert.snoozed_until.is_not(None),
                    Alert.snoozed_until < now,
                )
            )
        ).scalars().all()

        if not rows:
            return

        for alert in rows:
            alert.state = "firing"
            alert.snoozed_until = None
        await db.flush()

        for alert in rows:
            org_id, server_name = await alerting._resolve_org_and_server_name(db, alert)
            await alerting._broadcast("alert_updated", alert, org_id, server_name)

        await db.commit()
        logger.info("snooze_expiry_tick: returned %d alert(s) to firing", len(rows))
