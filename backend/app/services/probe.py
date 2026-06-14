"""Service-monitoring probe evaluator (spec 06 §8).

A single probe job per active service (job id ``service_probe:{service_id}``)
runs ``probe_service`` which:
  1. Performs the HTTP / TCP / DB-port check (max 50 concurrent via Semaphore).
  2. Writes a ``service_checks`` hypertable row + updates Service.last_status /
     last_checked / consecutive_failures in one transaction.
  3. On the 2nd consecutive failure (no open incident) → opens an Incident and
     fires a 'service_down' critical alert via app.services.alerting.fire_alert.
  4. On recovery ('up' with an open incident) → closes the incident and resolves
     the linked alert.
  5. Broadcasts service_check / incident_opened / incident_resolved over the
     in-process ws_manager (org-scoped), matching the alerting WS seam.

Job registration helpers (register_probe_job / unregister_probe_job /
schedule_all_active) are exposed for the app lifespan / router to wire; this
module never imports the scheduler at import time to avoid cycles.
"""
import asyncio
import logging
import socket
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.other import Incident, Service
from app.models.server import Server
from app.services import alerting
from app.ws.manager import ws_manager

logger = logging.getLogger(__name__)

# In-process cap on concurrent probe tasks (spec §8.4).
_semaphore = asyncio.Semaphore(50)

FAILURE_THRESHOLD = 2  # open incident / fire alert on the 2nd consecutive failure

FORBIDDEN_KEYWORDS: frozenset[str] = frozenset([
    "judi", "casino", "togel", "taruhan", "sportsbook",
    "jackpot", "gambling", "betting", "poker",
])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _parse_ssl_target(url: str) -> tuple[str, int]:
    """Return (hostname, port) from an https:// URL for TLS socket connection."""
    parsed = urlparse(url)
    return parsed.hostname or "", parsed.port or 443


async def _maybe_check_ssl(service_id: str) -> None:
    """Read the TLS cert for an HTTPS service if last check was >6 h ago.

    Uses a fresh DB session so it never delays the uptime write path.
    On socket/TLS failure sets ssl_status='unreachable' and updates ssl_last_checked.
    Unreachable does not change alert state (preserve last known state).
    """
    from app.models.other import Alert
    from app.services import alerting
    from app.services.ssl_checker import _compute_status, _fetch_ssl_cert

    async with AsyncSessionLocal() as db:
        service = await db.get(Service, service_id)
        if service is None or not service.ssl_enabled:
            return

        server = await db.get(Server, service.server_id)
        org_id = str(server.org_id) if server else None

        now = _now()
        last = _aware(service.ssl_last_checked)
        if last is not None and (now - last) < timedelta(hours=6):
            return

        hostname, port = _parse_ssl_target(service.url or "")
        if not hostname:
            return

        try:
            expiry, issuer = await asyncio.to_thread(_fetch_ssl_cert, hostname, port)
            expiry = _aware(expiry)
            days = (expiry - now).days
            ssl_status = _compute_status(days, service.ssl_warn_days, service.ssl_critical_days)

            service.ssl_expiry_date = expiry
            service.ssl_days_remaining = days
            service.ssl_issuer = issuer
            service.ssl_status = ssl_status
            service.ssl_last_checked = now
            await db.flush()

            if ssl_status in ("expiring_soon", "critical", "expired"):
                severity = "warning" if ssl_status == "expiring_soon" else "critical"
                msg = (
                    f"SSL certificate for {hostname} has expired."
                    if ssl_status == "expired"
                    else f"SSL certificate for {hostname} expires in {days} day(s) ({expiry.date()})."
                )
                await alerting.fire_alert(
                    db,
                    type="ssl_expiry",
                    severity=severity,
                    message=msg,
                    service_id=service.id,
                    commit=False,
                )
            elif ssl_status == "valid":
                open_alerts = (
                    await db.execute(
                        select(Alert).where(
                            Alert.service_id == service.id,
                            Alert.type == "ssl_expiry",
                            Alert.state.in_(alerting.OPEN_STATES),
                        )
                    )
                ).scalars().all()
                for alert in open_alerts:
                    await alerting.resolve_alert(db, alert, commit=False)

            await db.commit()
            await _broadcast(org_id, "service_ssl_updated", {
                "service_id": service_id,
                "ssl_status": ssl_status,
                "ssl_expiry_date": expiry.isoformat(),
                "ssl_days_remaining": days,
                "ssl_issuer": issuer,
                "ssl_last_checked": now.isoformat(),
            })

        except Exception:  # noqa: BLE001
            logger.info(
                "SSL check failed for service %s (%s:%s)", service_id, hostname, port, exc_info=True
            )
            service.ssl_status = "unreachable"
            service.ssl_last_checked = now
            await db.commit()


async def _maybe_run_security_check(service_id: str) -> None:
    """Trigger a security audit for an HTTPS service if >24 h since last scan."""
    from app.services.security_checker import run_security_check

    async with AsyncSessionLocal() as db:
        service = await db.get(Service, service_id)
        if service is None or not service.is_active or service.type != "http":
            return
        url = service.url or ""
        if not url.lower().startswith("https://"):
            return
        now = _now()
        last = _aware(service.last_security_scan)
        if last is not None and (now - last) < timedelta(hours=24):
            return

    await run_security_check(service_id)


# ── Low-level probes ────────────────────────────────────────────────────────
# Each returns (status, response_time_ms, cause) where:
#   status: 'up' | 'down' | 'timeout'
#   response_time_ms: int | None
#   cause: None when up, else one of
#          'wrong_status_code' | 'timeout' | 'connection_refused' | 'http_error'


async def _probe_http(service: Service) -> tuple[str, int | None, str | None]:
    url = service.url or ""
    expected = service.expected_status or 200
    timeout = service.timeout_sec or 5
    verify = not service.ignore_ssl_errors
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            verify=verify, timeout=timeout, follow_redirects=True
        ) as client:
            resp = await client.get(url)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        if resp.status_code != expected:
            return "down", elapsed_ms, "wrong_status_code"

        body_lower = resp.text[:500_000].lower()
        if service.expected_keyword:
            keywords = [kw.strip().lower() for kw in service.expected_keyword.split(",") if kw.strip()]
            for kw in keywords:
                if kw not in body_lower:
                    return "down", elapsed_ms, "content_mismatch"
        if service.forbidden_keywords_enabled:
            for kw in FORBIDDEN_KEYWORDS:
                if kw in body_lower:
                    return "down", elapsed_ms, "malicious_content"

        return "up", elapsed_ms, None
    except httpx.TimeoutException:
        return "timeout", None, "timeout"
    except httpx.ConnectError as e:
        msg = str(e).lower()
        if "refused" in msg:
            return "down", None, "connection_refused"
        return "down", None, "connection_refused"
    except httpx.HTTPError:
        return "down", None, "http_error"
    except Exception:  # noqa: BLE001
        logger.warning("HTTP probe error for service %s", service.id, exc_info=True)
        return "down", None, "http_error"


async def _probe_tcp(host: str, port: int, timeout: int) -> tuple[str, int | None, str | None]:
    start = time.perf_counter()
    try:
        fut = asyncio.open_connection(host=host, port=port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        return "up", elapsed_ms, None
    except asyncio.TimeoutError:
        return "timeout", None, "timeout"
    except (ConnectionRefusedError, OSError, socket.gaierror):
        return "down", None, "connection_refused"
    except Exception:  # noqa: BLE001
        logger.warning("TCP probe error for %s:%s", host, port, exc_info=True)
        return "down", None, "connection_refused"


async def _run_check(service: Service) -> tuple[str, int | None, str | None]:
    """Dispatch to the right probe based on service.type. DB == TCP (spec §8.3)."""
    if service.type == "http":
        return await _probe_http(service)
    # tcp / db → identical TCP reachability check
    host = service.url or ""  # for TCP/DB the host is stored in `url`
    port = service.port or 0
    if not host or not port:
        return "down", None, "connection_refused"
    return await _probe_tcp(host, port, service.timeout_sec or 5)


# ── Persistence + incident/alert lifecycle ──────────────────────────────────


async def _open_incident_for(db: AsyncSession, service_id) -> Incident | None:
    return (
        await db.execute(
            select(Incident)
            .where(Incident.service_id == service_id, Incident.resolved_at.is_(None))
            .order_by(Incident.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _broadcast(org_id: str | None, event: str, data: dict) -> None:
    if not org_id:
        return
    try:
        await ws_manager.broadcast_org(org_id, {"event": event, "data": data})
    except Exception:  # noqa: BLE001 — WS fan-out must never break the probe path
        logger.warning("service probe WS broadcast failed (%s)", event, exc_info=True)


async def evaluate_result(
    db: AsyncSession,
    service: Service,
    status: str,
    response_time_ms: int | None,
    cause: str | None,
    org_id: str | None,
) -> None:
    """Apply one check result: write the row, update the service, manage the
    incident + alert lifecycle, and broadcast. Commits once at the end."""
    now = _now()

    # 1. Persist the raw check row.
    await db.execute(
        text(
            "INSERT INTO service_checks (time, service_id, status, response_time_ms) "
            "VALUES (:t, :sid, :status, :rt)"
        ),
        {"t": now, "sid": str(service.id), "status": status, "rt": response_time_ms},
    )

    # 2. Update service rollup fields.
    service.last_checked = now
    service.last_status = status
    is_failure = status in ("down", "timeout")
    if is_failure:
        service.consecutive_failures = (service.consecutive_failures or 0) + 1
    else:
        service.consecutive_failures = 0

    open_incident = await _open_incident_for(db, service.id)

    incident_event: tuple[str, dict] | None = None

    # 3. Open incident + fire alert on the 2nd consecutive failure.
    if is_failure and service.consecutive_failures == FAILURE_THRESHOLD and open_incident is None:
        incident = Incident(service_id=service.id, started_at=now)
        db.add(incident)
        await db.flush()
        open_incident = incident
        incident_event = (
            "incident_opened",
            {
                "incident_id": str(incident.id),
                "service_id": str(service.id),
                "started_at": now.isoformat(),
                "cause": cause or "http_error",
            },
        )
        _content_causes = {"content_mismatch", "malicious_content"}
        if cause in _content_causes:
            _alert_type = cause
            _alert_msg = (
                f"Malicious content detected on '{service.name}': forbidden keyword found in response body."
                if cause == "malicious_content"
                else f"Content check failed for '{service.name}': expected keyword not found in response body."
            )
        else:
            _alert_type = "service_down"
            _alert_msg = f"Service '{service.name}' is down ({cause or 'unreachable'})."
        await alerting.fire_alert(
            db,
            type=_alert_type,
            severity="critical",
            message=_alert_msg,
            server_id=service.server_id,
            service_id=service.id,
            commit=False,
        )

    # 4. Recovery: close incident + resolve alert.
    if not is_failure and open_incident is not None:
        open_incident.resolved_at = now
        started = _aware(open_incident.started_at) or now
        open_incident.duration_sec = max(0, int((now - started).total_seconds()))
        incident_event = (
            "incident_resolved",
            {
                "incident_id": str(open_incident.id),
                "service_id": str(service.id),
                "resolved_at": now.isoformat(),
                "duration_sec": open_incident.duration_sec,
            },
        )
        # Resolve any open service_down / content alert(s) for this service.
        from app.models.other import Alert

        open_alerts = (
            await db.execute(
                select(Alert).where(
                    Alert.service_id == service.id,
                    Alert.type.in_(["service_down", "content_mismatch", "malicious_content"]),
                    Alert.state.in_(alerting.OPEN_STATES),
                )
            )
        ).scalars().all()
        for alert in open_alerts:
            await alerting.resolve_alert(db, alert, commit=False)

    await db.commit()

    # 5. Broadcast (after commit so the WS reflects persisted state).
    await _broadcast(
        org_id,
        "service_check",
        {
            "service_id": str(service.id),
            "status": status,
            "response_time_ms": response_time_ms,
            "checked_at": now.isoformat(),
            "consecutive_failures": service.consecutive_failures,
            "last_status": service.last_status,
        },
    )
    if incident_event is not None:
        await _broadcast(org_id, incident_event[0], incident_event[1])


async def probe_service(service_id: str) -> None:
    """Entry point invoked by APScheduler (one job per service). Loads the
    service, runs the check under the concurrency semaphore, and applies the
    result. Skips paused services. Never raises into the scheduler."""
    async with _semaphore:
        try:
            needs_ssl = False
            async with AsyncSessionLocal() as db:
                service = await db.scalar(select(Service).where(Service.id == service_id))
                if service is None or not service.is_active:
                    return
                server = await db.get(Server, service.server_id)
                org_id = str(server.org_id) if server else None
                needs_ssl = service.type == "http" and service.ssl_enabled
                status, rt, cause = await _run_check(service)
                await evaluate_result(db, service, status, rt, cause, org_id)
            if needs_ssl:
                await _maybe_check_ssl(service_id)
            await _maybe_run_security_check(service_id)
        except Exception:  # noqa: BLE001
            logger.exception("probe_service failed for %s", service_id)


# ── Scheduler job registration (wired by the coordinator) ───────────────────


def register_probe_job(service_id: str, interval_sec: int) -> None:
    """Add/replace the APScheduler interval job for a service."""
    from app.jobs.scheduler import scheduler

    scheduler.add_job(
        probe_service,
        "interval",
        seconds=interval_sec,
        id=f"service_probe:{service_id}",
        args=[service_id],
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


def unregister_probe_job(service_id: str) -> None:
    """Remove the probe job for a service (paused or deleted). Safe if absent."""
    from app.jobs.scheduler import scheduler

    try:
        scheduler.remove_job(f"service_probe:{service_id}")
    except Exception:  # noqa: BLE001 — job may not exist
        pass


async def schedule_all_active() -> None:
    """On startup: schedule a probe job for every active service."""
    async with AsyncSessionLocal() as db:
        services = (
            await db.execute(select(Service).where(Service.is_active == True))  # noqa: E712
        ).scalars().all()
        for svc in services:
            register_probe_job(str(svc.id), svc.interval_sec)


async def probe_now(service_id: str) -> None:
    """Trigger an immediate one-off probe (used right after create)."""
    await probe_service(service_id)
