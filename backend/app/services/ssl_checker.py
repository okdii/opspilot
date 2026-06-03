"""SSL certificate + domain WHOIS checking (spec 07 §11).

Two check primitives:
  - check_ssl_cert(cert): open a TLS socket to domain:port, read notAfter,
    compute days_remaining + status, persist, and fire/resolve ssl_expiry alerts.
  - check_domain(domain): WHOIS lookup, compute days_remaining + status,
    persist, and fire/resolve domain_expiry alerts.

Status computation (shared):
  days_remaining > warn_days                     → 'valid'
  critical_days < days_remaining <= warn_days    → 'expiring_soon'
  0 < days_remaining <= critical_days            → 'critical'
  days_remaining <= 0                            → 'expired'
  SSL socket failure                             → 'unreachable' (days_remaining = NULL)

Scheduled jobs (wired by the coordinator in main.py — NOT here):
  ssl_checker_daily      — CronTrigger 02:00 UTC, id 'ssl_checker_daily'
  domain_checker_daily   — CronTrigger 03:00 UTC, id 'domain_checker_daily'
                           (staggered 30s between WHOIS lookups)
"""
import asyncio
import logging
import socket
import ssl
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.other import Alert, Domain, SSLCert
from app.services.alerting import fire_alert, resolve_alert

logger = logging.getLogger(__name__)

SSL_SOCKET_TIMEOUT = 10  # seconds
WHOIS_STAGGER_SEC = 30   # delay between domain WHOIS lookups


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _compute_status(days_remaining: int, warn_days: int, critical_days: int) -> str:
    if days_remaining <= 0:
        return "expired"
    if days_remaining <= critical_days:
        return "critical"
    if days_remaining <= warn_days:
        return "expiring_soon"
    return "valid"


# ── SSL cert reading (blocking; run in a thread) ──────────────────────────────

def _fetch_ssl_cert(hostname: str, port: int) -> tuple[datetime, str]:
    """Open a TLS socket, return (expiry_date_utc, issuer_cn). Raises on failure."""
    ctx = ssl.create_default_context()
    # We only need to read the cert; tolerate hostname/validation issues so we
    # can still report an expiry date for self-signed / mismatched certs.
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    with socket.create_connection((hostname, port), timeout=SSL_SOCKET_TIMEOUT) as sock:
        with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
            cert = ssock.getpeercert()

    if not cert:
        # CERT_NONE doesn't always populate getpeercert(); fall back to binary.
        der = None
        with socket.create_connection((hostname, port), timeout=SSL_SOCKET_TIMEOUT) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                der = ssock.getpeercert(binary_form=True)
        return _parse_der(der)

    not_after = cert.get("notAfter")
    if not not_after:
        raise ValueError("Certificate has no notAfter field")
    # Format: 'Jun  1 12:00:00 2026 GMT'
    expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)

    issuer = _issuer_cn(cert.get("issuer", ()))
    return expiry, issuer


def _issuer_cn(issuer_field) -> str | None:
    for rdn in issuer_field:
        for key, value in rdn:
            if key in ("commonName", "organizationName"):
                return value
    return None


def _parse_der(der: bytes | None) -> tuple[datetime, str | None]:
    from cryptography import x509
    if der is None:
        raise ValueError("No certificate returned")
    cert = x509.load_der_x509_certificate(der)
    expiry = cert.not_valid_after_utc
    issuer_cn = None
    try:
        attrs = cert.issuer.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
        if attrs:
            issuer_cn = attrs[0].value
        else:
            org = cert.issuer.get_attributes_for_oid(x509.oid.NameOID.ORGANIZATION_NAME)
            if org:
                issuer_cn = org[0].value
    except Exception:  # noqa: BLE001
        pass
    return expiry, issuer_cn


# ── SSL check ─────────────────────────────────────────────────────────────────

async def check_ssl_cert(db: AsyncSession, cert: SSLCert) -> None:
    """Check one SSL cert, persist, fire/resolve ssl_expiry alert. Commits."""
    domain = await db.get(Domain, cert.domain_id)
    hostname = domain.domain if domain else None

    if not hostname:
        logger.warning("SSLCert %s has no resolvable domain", cert.id)
        return

    try:
        expiry, issuer = await asyncio.to_thread(_fetch_ssl_cert, hostname, cert.port)
    except Exception as e:  # noqa: BLE001 — socket/TLS/timeout → unreachable
        logger.info("SSL check unreachable for %s:%s — %s", hostname, cert.port, e)
        cert.status = "unreachable"
        cert.days_remaining = None
        cert.last_checked = _now()
        await db.commit()
        return

    expiry = _aware(expiry)
    days = (expiry - _now()).days
    status = _compute_status(days, cert.warn_days, cert.critical_days)

    cert.issuer = issuer
    cert.expiry_date = expiry
    cert.days_remaining = days
    cert.status = status
    cert.last_checked = _now()
    await db.flush()

    await _evaluate_ssl_alert(db, cert, hostname)
    await db.commit()


async def _evaluate_ssl_alert(db: AsyncSession, cert: SSLCert, hostname: str) -> None:
    if cert.status in ("expiring_soon", "critical", "expired"):
        severity = "warning" if cert.status == "expiring_soon" else "critical"
        if cert.status == "expired":
            message = f"SSL certificate for {hostname}:{cert.port} has expired."
        else:
            message = (
                f"SSL certificate for {hostname}:{cert.port} expires in "
                f"{cert.days_remaining} day(s) ({cert.expiry_date.date()})."
            )
        await fire_alert(
            db,
            type="ssl_expiry",
            severity=severity,
            message=message,
            ssl_cert_id=cert.id,
            commit=False,
        )
    elif cert.status == "valid":
        await _resolve_open_alerts(db, "ssl_expiry", ssl_cert_id=cert.id)


# ── Domain WHOIS check ────────────────────────────────────────────────────────

def _whois_expiry(domain_name: str) -> tuple[datetime | None, str | None]:
    """WHOIS lookup → (expiry_date_utc | None, registrar | None). Raises on failure."""
    import whois  # imported lazily; raises ImportError if not installed

    data = whois.whois(domain_name)
    exp = data.expiration_date
    if isinstance(exp, list):
        exp = exp[0] if exp else None
    registrar = data.registrar
    if isinstance(registrar, list):
        registrar = registrar[0] if registrar else None

    if exp is not None:
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        else:
            exp = exp.astimezone(timezone.utc)
    return exp, registrar


async def check_domain(db: AsyncSession, domain: Domain) -> None:
    """Check one domain via WHOIS, persist, fire/resolve domain_expiry alert.

    On WHOIS failure (library missing, parse error, unsupported TLD): log and
    preserve last known state — do NOT touch days_remaining/status/last_checked.
    """
    try:
        expiry, registrar = await asyncio.to_thread(_whois_expiry, domain.domain)
    except Exception as e:  # noqa: BLE001 — preserve last known state per spec §11.2
        logger.warning("WHOIS check failed for %s — %s", domain.domain, e)
        return

    if expiry is None:
        # Some TLDs don't expose expiry — assume ok (spec §14).
        domain.registrar = registrar
        domain.expiry_date = None
        domain.days_remaining = None
        domain.status = "valid"
        domain.last_checked = _now()
        await db.flush()
        await _resolve_open_alerts(db, "domain_expiry", domain_id=domain.id)
        await db.commit()
        return

    days = (expiry - _now()).days
    status = _compute_status(days, domain.warn_days, domain.critical_days)

    domain.registrar = registrar
    domain.expiry_date = expiry
    domain.days_remaining = days
    domain.status = status
    domain.last_checked = _now()
    await db.flush()

    await _evaluate_domain_alert(db, domain)
    await db.commit()


async def _evaluate_domain_alert(db: AsyncSession, domain: Domain) -> None:
    if domain.status in ("expiring_soon", "critical", "expired"):
        severity = "warning" if domain.status == "expiring_soon" else "critical"
        if domain.status == "expired":
            message = f"Domain registration for {domain.domain} has expired."
        else:
            message = (
                f"Domain registration for {domain.domain} expires in "
                f"{domain.days_remaining} day(s) ({domain.expiry_date.date()})."
            )
        await fire_alert(
            db,
            type="domain_expiry",
            severity=severity,
            message=message,
            domain_id=domain.id,
            commit=False,
        )
    elif domain.status == "valid":
        await _resolve_open_alerts(db, "domain_expiry", domain_id=domain.id)


# ── Alert resolution helper ───────────────────────────────────────────────────

async def _resolve_open_alerts(db: AsyncSession, alert_type: str, *, domain_id=None, ssl_cert_id=None) -> None:
    conds = [Alert.type == alert_type, Alert.state.in_(("firing", "acknowledged", "snoozed", "suppressed"))]
    if domain_id is not None:
        conds.append(Alert.domain_id == domain_id)
    if ssl_cert_id is not None:
        conds.append(Alert.ssl_cert_id == ssl_cert_id)
    rows = (await db.execute(select(Alert).where(*conds))).scalars().all()
    for alert in rows:
        await resolve_alert(db, alert, commit=False)


# ── One-shot first-check (scheduled on add via APScheduler date trigger) ──────

async def check_ssl_cert_by_id(ssl_cert_id: str) -> None:
    async with AsyncSessionLocal() as db:
        cert = await db.get(SSLCert, ssl_cert_id)
        if cert is not None:
            await check_ssl_cert(db, cert)


async def check_domain_by_id(domain_id: str) -> None:
    async with AsyncSessionLocal() as db:
        domain = await db.get(Domain, domain_id)
        if domain is not None:
            await check_domain(db, domain)


# ── Daily jobs (registered by coordinator in main.py) ─────────────────────────

async def ssl_checker_daily() -> None:
    """Daily 02:00 UTC: check every SSL cert sequentially."""
    async with AsyncSessionLocal() as db:
        certs = (await db.execute(select(SSLCert))).scalars().all()
    for cert in certs:
        async with AsyncSessionLocal() as db:
            fresh = await db.get(SSLCert, cert.id)
            if fresh is not None:
                try:
                    await check_ssl_cert(db, fresh)
                except Exception:  # noqa: BLE001
                    logger.exception("ssl_checker_daily failed for cert %s", cert.id)


async def domain_checker_daily() -> None:
    """Daily 03:00 UTC: check every domain via WHOIS, staggered 30s apart."""
    async with AsyncSessionLocal() as db:
        domains = (
            await db.execute(select(Domain).order_by(Domain.last_checked.asc().nulls_first()))
        ).scalars().all()
    for i, domain in enumerate(domains):
        async with AsyncSessionLocal() as db:
            fresh = await db.get(Domain, domain.id)
            if fresh is not None:
                try:
                    await check_domain(db, fresh)
                except Exception:  # noqa: BLE001
                    logger.exception("domain_checker_daily failed for domain %s", domain.id)
        if i < len(domains) - 1:
            await asyncio.sleep(WHOIS_STAGGER_SEC)
