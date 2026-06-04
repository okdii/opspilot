"""Alerting core — the single fire_alert / resolve_alert seam (spec 10 §11, §16).

Every phase that needs to raise an alert (metric/log evaluators, service/SSL/
domain checkers, cron/backup watchdogs) calls ``fire_alert`` here. It enforces:
  (1) active-maintenance suppression on the subject server,
  (2) cooldown — a same-(type, relevant_fk) alert fired < cooldown_min ago and
      still open,
  (3) dedup — only one open (firing|acknowledged|snoozed|suppressed) alert per
      (type, relevant_fk) at a time.
On success it persists the Alert(state='firing'), sends a best-effort fire
email, and broadcasts ``alert_fired`` org-scoped over the existing ws_manager
seam. ``resolve_alert`` is the inverse.
"""
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.other import (
    Alert,
    Domain,
    MaintenanceWindow,
    Service,
    SSLCert,
)
from app.models.server import Server
from app.services import alert_email
from app.ws.manager import ws_manager

logger = logging.getLogger(__name__)

# Open states that block a re-fire (spec §16 dedup).
OPEN_STATES = ("firing", "acknowledged", "snoozed", "suppressed")

# spec §11.3 — which FK column governs dedup/cooldown for each alert type.
# Anything not listed (cpu/ram/disk/disk_inode/db_*/agent_offline/log types)
# is keyed on server_id.
_FK_BY_TYPE: dict[str, str] = {
    "service_down": "service_id",
    "ssl_expiry": "ssl_cert_id",
    "domain_expiry": "domain_id",
    "cron_missing": "cron_job_id",
    "backup_missing": "backup_job_id",
    "backup_failure": "backup_job_id",
    "backup_size_drop": "backup_job_id",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _relevant_fk(alert_type: str, fks: dict[str, object | None]) -> tuple[str, object | None]:
    """Return (fk_column_name, fk_value) governing dedup/cooldown for this type.

    Special case: ssl_expiry can be keyed on ssl_cert_id (standalone SSL cert
    objects) OR on service_id (inline SSL checks on an HTTP service).  When the
    caller supplies service_id but not ssl_cert_id we fall through to service_id
    so that dedup is scoped per-service rather than matching all NULL-cert rows.
    """
    col = _FK_BY_TYPE.get(alert_type, "server_id")
    val = fks.get(col)
    if val is None and alert_type == "ssl_expiry" and fks.get("service_id") is not None:
        return "service_id", fks["service_id"]
    return col, val


async def _active_maintenance(db: AsyncSession, server_id: object | None) -> bool:
    if server_id is None:
        return False
    rows = (
        await db.execute(
            select(MaintenanceWindow).where(MaintenanceWindow.server_id == server_id)
        )
    ).scalars().all()
    now = _now()
    for w in rows:
        starts = _aware(w.starts_at)
        ends = _aware(w.ends_at)
        if starts is not None and starts <= now and (ends is None or ends > now):
            return True
    return False


async def _resolve_org_and_server_name(
    db: AsyncSession, alert: Alert
) -> tuple[str | None, str | None]:
    """Resolve (org_id, server_name) for WS fan-out and email subjects."""
    server: Server | None = None
    if alert.server_id is not None:
        server = await db.get(Server, alert.server_id)
    elif alert.service_id is not None:
        svc = await db.get(Service, alert.service_id)
        if svc is not None:
            server = await db.get(Server, svc.server_id)
    elif alert.ssl_cert_id is not None:
        cert = await db.get(SSLCert, alert.ssl_cert_id)
        if cert is not None:
            dom = await db.get(Domain, cert.domain_id)
            if dom is not None:
                return str(dom.org_id), None
    elif alert.domain_id is not None:
        dom = await db.get(Domain, alert.domain_id)
        if dom is not None:
            return str(dom.org_id), None

    if server is not None:
        return str(server.org_id), server.name
    return None, None


async def _broadcast(event: str, alert: Alert, org_id: str | None, server_name: str | None) -> None:
    if not org_id:
        return
    if event == "alert_fired":
        data = {
            "id": str(alert.id),
            "type": alert.type,
            "severity": alert.severity,
            "message": alert.message,
            "server_id": str(alert.server_id) if alert.server_id else None,
            "server_name": server_name,
            "sent_at": _aware(alert.sent_at).isoformat() if alert.sent_at else None,
            "state": alert.state,
        }
    elif event == "alert_resolved":
        data = {
            "id": str(alert.id),
            "state": alert.state,
            "resolved_at": _aware(alert.resolved_at).isoformat() if alert.resolved_at else None,
        }
    else:  # alert_updated
        data = {
            "id": str(alert.id),
            "state": alert.state,
            "acknowledged_at": _aware(alert.acknowledged_at).isoformat()
            if alert.acknowledged_at
            else None,
            "snoozed_until": _aware(alert.snoozed_until).isoformat()
            if alert.snoozed_until
            else None,
        }
    try:
        await ws_manager.broadcast_org(org_id, {"event": event, "data": data})
    except Exception:  # noqa: BLE001 — WS fan-out must not break the fire/resolve path
        logger.warning("alert WS broadcast failed (%s)", event, exc_info=True)


async def fire_alert(
    db: AsyncSession,
    *,
    type: str,
    severity: str,
    message: str,
    server_id: UUID | str | None = None,
    service_id: UUID | str | None = None,
    domain_id: UUID | str | None = None,
    ssl_cert_id: UUID | str | None = None,
    cron_job_id: UUID | str | None = None,
    backup_job_id: UUID | str | None = None,
    cooldown_min: int = 60,
    email_meta: dict | None = None,
    commit: bool = True,
) -> Alert | None:
    """Idempotent fire. Returns the new Alert, or None if suppressed by active
    maintenance, cooldown, or dedup (see module docstring). On success: INSERT
    Alert(state='firing'), send fire email (best-effort), broadcast 'alert_fired'.
    """
    fks: dict[str, object | None] = {
        "server_id": server_id,
        "service_id": service_id,
        "domain_id": domain_id,
        "ssl_cert_id": ssl_cert_id,
        "cron_job_id": cron_job_id,
        "backup_job_id": backup_job_id,
    }

    # (1) maintenance suppression — no new alerts while the server is in a window.
    if await _active_maintenance(db, server_id):
        return None

    fk_col, fk_val = _relevant_fk(type, fks)

    # (2)+(3) dedup + cooldown: is there already an open alert for this key?
    conds = [Alert.type == type, Alert.state.in_(OPEN_STATES)]
    if fk_val is not None:
        conds.append(getattr(Alert, fk_col) == fk_val)
    else:
        conds.append(getattr(Alert, fk_col).is_(None))
    existing = (
        await db.execute(
            select(Alert).where(and_(*conds)).order_by(Alert.sent_at.desc()).limit(1)
        )
    ).scalar_one_or_none()

    if existing is not None:
        # cooldown: still within the window since it last fired → suppress.
        sent = _aware(existing.sent_at)
        if sent is not None and _now() < sent + timedelta(minutes=cooldown_min):
            return None
        # open but past cooldown — still deduped (one open alert per key, spec §16).
        return None

    alert = Alert(
        server_id=server_id,
        service_id=service_id,
        domain_id=domain_id,
        ssl_cert_id=ssl_cert_id,
        cron_job_id=cron_job_id,
        backup_job_id=backup_job_id,
        type=type,
        severity=severity,
        message=message,
        sent_at=_now(),
        state="firing",
        consecutive_clear_count=0,
    )
    db.add(alert)
    await db.flush()  # populate PK + sent_at for email/WS

    org_id, server_name = await _resolve_org_and_server_name(db, alert)

    await alert_email.send_alert_email(
        db, alert, kind="fire", server_name=server_name, email_meta=email_meta
    )
    await _broadcast("alert_fired", alert, org_id, server_name)

    if commit:
        await db.commit()
    return alert


async def resolve_alert(
    db: AsyncSession,
    alert: Alert,
    *,
    send_email: bool = True,
    commit: bool = True,
) -> None:
    """Set state='resolved', resolved_at=now, consecutive_clear_count=0; send a
    resolve email (best-effort) unless send_email is False; broadcast
    'alert_resolved'. No-op if already resolved."""
    if alert.state == "resolved":
        return

    alert.state = "resolved"
    alert.resolved_at = _now()
    alert.consecutive_clear_count = 0
    await db.flush()

    org_id, server_name = await _resolve_org_and_server_name(db, alert)

    if send_email:
        await alert_email.send_alert_email(
            db, alert, kind="resolve", server_name=server_name
        )
    await _broadcast("alert_resolved", alert, org_id, server_name)

    if commit:
        await db.commit()
