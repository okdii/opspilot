"""HTTP security audit module.

Performs TLS + HTTP header checks on HTTPS services. Results are stored in
`service_security_scans` and summarised as an A+-F letter grade. Severe
findings fire alerts via the standard alerting seam.
"""
import asyncio
import logging
import re
import socket
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.other import Alert, Service, ServiceSecurityScan
from app.models.server import Server
from app.services import alerting
from app.ws.manager import ws_manager

logger = logging.getLogger(__name__)

TLS_TIMEOUT = 10
HTTP_TIMEOUT = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


@dataclass
class TLSAudit:
    tls_version: str | None = None
    tls_ok: bool = True
    cipher_suite: str | None = None
    cipher_ok: bool = True
    pfs_supported: bool = False
    key_size: int | None = None
    key_size_ok: bool = True
    self_signed: bool = False
    ocsp_stapling: bool | None = None
    error: str | None = None


@dataclass
class HeaderAudit:
    https_redirect: bool = False
    hsts: bool = False
    hsts_max_age: int | None = None
    csp: bool = False
    x_frame_options: bool = False
    x_content_type: bool = False
    referrer_policy: bool = False
    permissions_policy: bool = False
    server_disclosure: bool = False
    x_powered_by: str | None = None
    error: str | None = None


@dataclass
class Finding:
    check: str
    severity: str
    passed: bool
    detail: str


def _audit_tls_sync(hostname: str, port: int) -> TLSAudit:
    """Blocking TLS probe. Run in a thread via asyncio.to_thread."""
    result = TLSAudit()

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((hostname, port), timeout=TLS_TIMEOUT) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                result.tls_version = ssock.version()
                cipher_info = ssock.cipher()
                result.cipher_suite = cipher_info[0] if cipher_info else None
                der = ssock.getpeercert(binary_form=True)
    except Exception as e:
        result.error = str(e)
        return result

    if result.cipher_suite:
        upper = result.cipher_suite.upper()
        if any(w in upper for w in ("RC4", "DES", "NULL")):
            result.cipher_ok = False
        result.pfs_supported = "ECDHE" in upper or "DHE" in upper

    if der:
        try:
            from cryptography import x509
            cert = x509.load_der_x509_certificate(der)
            pub = cert.public_key()
            key_type = type(pub).__name__
            if "RSA" in key_type:
                result.key_size = pub.key_size
                result.key_size_ok = pub.key_size >= 2048
            elif "EC" in key_type or "EllipticCurve" in key_type:
                result.key_size = pub.key_size
                result.key_size_ok = pub.key_size >= 256
            result.self_signed = cert.issuer == cert.subject
        except Exception:
            pass

    for version in (ssl.TLSVersion.TLSv1, ssl.TLSVersion.TLSv1_1):
        try:
            dctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            dctx.check_hostname = False
            dctx.verify_mode = ssl.CERT_NONE
            dctx.minimum_version = version
            dctx.maximum_version = version
            with socket.create_connection((hostname, port), timeout=TLS_TIMEOUT) as sock:
                with dctx.wrap_socket(sock, server_hostname=hostname):
                    result.tls_ok = False
                    break
        except (ssl.SSLError, OSError, ConnectionResetError):
            pass

    return result


async def _audit_headers(url: str) -> HeaderAudit:
    result = HeaderAudit()
    parsed = urlparse(url)
    http_url = f"http://{parsed.netloc}{parsed.path or '/'}"
    if parsed.query:
        http_url += f"?{parsed.query}"

    try:
        async with httpx.AsyncClient(verify=False, timeout=HTTP_TIMEOUT, follow_redirects=False) as client:
            r = await client.get(http_url)
            if r.status_code in (301, 302, 307, 308):
                loc = r.headers.get("location", "")
                result.https_redirect = loc.lower().startswith("https://")
    except Exception as e:
        result.error = str(e)

    try:
        async with httpx.AsyncClient(verify=False, timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url)
            h = r.headers

            sts = h.get("strict-transport-security", "")
            if sts:
                result.hsts = True
                m = re.search(r"max-age=(\d+)", sts, re.IGNORECASE)
                result.hsts_max_age = int(m.group(1)) if m else 0

            result.csp = bool(h.get("content-security-policy"))
            result.x_frame_options = bool(h.get("x-frame-options"))
            result.x_content_type = h.get("x-content-type-options", "").lower() == "nosniff"
            result.referrer_policy = bool(h.get("referrer-policy"))
            result.permissions_policy = bool(h.get("permissions-policy"))

            server_hdr = h.get("server", "")
            result.server_disclosure = bool(re.search(r"[\d.]{2,}", server_hdr))
            xpb = h.get("x-powered-by")
            result.x_powered_by = xpb if xpb else None
    except Exception as e:
        if not result.error:
            result.error = str(e)

    return result


def _compute_score(tls: TLSAudit, hdr: HeaderAudit) -> tuple[int, str, list[dict]]:
    pts = 0
    findings: list[Finding] = []

    v = tls.tls_version or ""
    if "1.3" in v:
        tls_pts = 25
    elif "1.2" in v:
        tls_pts = 20
    elif "1.1" in v:
        tls_pts = 5
    else:
        tls_pts = 0
    pts += tls_pts
    findings.append(Finding(
        check="TLS Protocol",
        severity="critical" if tls_pts == 0 else ("warning" if tls_pts <= 5 else "info"),
        passed=tls_pts >= 20,
        detail=f"Negotiated: {tls.tls_version or 'unknown'}",
    ))
    if not tls.tls_ok:
        findings.append(Finding(
            check="Deprecated Protocol Accepted",
            severity="critical",
            passed=False,
            detail="Server accepts TLS 1.0 or TLS 1.1 — deprecated since 2021",
        ))

    if tls.cipher_ok and tls.pfs_supported:
        cipher_pts = 20
    elif tls.cipher_ok:
        cipher_pts = 15
    elif tls.cipher_suite and "3DES" in tls.cipher_suite.upper():
        cipher_pts = 5
    else:
        cipher_pts = 0
    pts += cipher_pts
    findings.append(Finding(
        check="Cipher Suite",
        severity="critical" if cipher_pts == 0 else ("warning" if cipher_pts < 20 else "info"),
        passed=cipher_pts >= 15,
        detail=f"{tls.cipher_suite or 'unknown'}, PFS: {'yes' if tls.pfs_supported else 'no'}",
    ))

    key_pts = 5 if tls.key_size_ok else 0
    pts += key_pts
    findings.append(Finding(
        check="Key Size",
        severity="warning" if not tls.key_size_ok else "info",
        passed=tls.key_size_ok,
        detail=f"{tls.key_size} bits" if tls.key_size else "unknown",
    ))
    selfsign_pts = 0 if tls.self_signed else 5
    pts += selfsign_pts
    findings.append(Finding(
        check="Self-Signed Certificate",
        severity="warning",
        passed=not tls.self_signed,
        detail="Certificate is self-signed" if tls.self_signed else "Certificate is CA-signed",
    ))
    findings.append(Finding(
        check="OCSP Stapling",
        severity="info",
        passed=False,
        detail="OCSP stapling detection requires OpenSSL-level access (not available via Python stdlib)",
    ))

    if hdr.hsts:
        pts += 10
    findings.append(Finding(
        check="HSTS",
        severity="warning" if not hdr.hsts else "info",
        passed=hdr.hsts,
        detail=f"max-age={hdr.hsts_max_age}" if hdr.hsts else "Strict-Transport-Security header missing",
    ))
    if hdr.csp:
        pts += 8
    findings.append(Finding(
        check="Content-Security-Policy",
        severity="warning" if not hdr.csp else "info",
        passed=hdr.csp,
        detail="CSP header present" if hdr.csp else "Content-Security-Policy header missing",
    ))
    if hdr.x_frame_options:
        pts += 4
    findings.append(Finding(
        check="X-Frame-Options",
        severity="warning" if not hdr.x_frame_options else "info",
        passed=hdr.x_frame_options,
        detail="Clickjacking protection present" if hdr.x_frame_options else "X-Frame-Options header missing",
    ))
    if hdr.x_content_type:
        pts += 3
    findings.append(Finding(
        check="X-Content-Type-Options",
        severity="info",
        passed=hdr.x_content_type,
        detail="nosniff set" if hdr.x_content_type else "X-Content-Type-Options: nosniff missing",
    ))
    if hdr.referrer_policy:
        pts += 3
    findings.append(Finding(
        check="Referrer-Policy",
        severity="info",
        passed=hdr.referrer_policy,
        detail="Referrer-Policy header present" if hdr.referrer_policy else "Referrer-Policy header missing",
    ))
    if hdr.permissions_policy:
        pts += 2
    findings.append(Finding(
        check="Permissions-Policy",
        severity="info",
        passed=hdr.permissions_policy,
        detail="Permissions-Policy header present" if hdr.permissions_policy else "Permissions-Policy header missing",
    ))

    if hdr.https_redirect:
        pts += 5
    findings.append(Finding(
        check="HTTPS Redirect",
        severity="warning" if not hdr.https_redirect else "info",
        passed=hdr.https_redirect,
        detail="HTTP → HTTPS redirect present" if hdr.https_redirect else "No HTTP → HTTPS redirect detected",
    ))
    if not hdr.server_disclosure:
        pts += 3
    findings.append(Finding(
        check="Server Header Disclosure",
        severity="info",
        passed=not hdr.server_disclosure,
        detail="Server version not disclosed" if not hdr.server_disclosure else "Server header leaks version number",
    ))
    if not hdr.x_powered_by:
        pts += 2
    findings.append(Finding(
        check="X-Powered-By Disclosure",
        severity="info",
        passed=not hdr.x_powered_by,
        detail="X-Powered-By absent" if not hdr.x_powered_by else f"X-Powered-By: {hdr.x_powered_by}",
    ))

    score = max(0, min(100, pts))
    if score == 100:
        grade = "A+"
    elif score >= 90:
        grade = "A"
    elif score >= 75:
        grade = "B"
    elif score >= 60:
        grade = "C"
    elif score >= 45:
        grade = "D"
    elif score >= 30:
        grade = "E"
    else:
        grade = "F"

    findings_dicts = [
        {"check": f.check, "severity": f.severity, "passed": f.passed, "detail": f.detail}
        for f in findings
    ]
    return score, grade, findings_dicts


async def _fire_security_alerts(db, service: Service, tls: TLSAudit, grade: str, server_id) -> None:
    if not tls.tls_ok:
        await alerting.fire_alert(
            db,
            type="security_tls_deprecated",
            severity="critical",
            message=f"Service '{service.name}' accepts deprecated TLS 1.0/1.1 — upgrade your server TLS config.",
            service_id=service.id,
            server_id=server_id,
            commit=False,
        )
    else:
        open_alerts = (
            await db.execute(
                select(Alert).where(
                    Alert.service_id == service.id,
                    Alert.type == "security_tls_deprecated",
                    Alert.state.in_(alerting.OPEN_STATES),
                )
            )
        ).scalars().all()
        for a in open_alerts:
            await alerting.resolve_alert(db, a, commit=False)

    if not tls.cipher_ok:
        await alerting.fire_alert(
            db,
            type="security_weak_cipher",
            severity="critical",
            message=f"Service '{service.name}' uses a weak cipher ({tls.cipher_suite}) — RC4/DES/NULL ciphers are broken.",
            service_id=service.id,
            server_id=server_id,
            commit=False,
        )
    else:
        open_alerts = (
            await db.execute(
                select(Alert).where(
                    Alert.service_id == service.id,
                    Alert.type == "security_weak_cipher",
                    Alert.state.in_(alerting.OPEN_STATES),
                )
            )
        ).scalars().all()
        for a in open_alerts:
            await alerting.resolve_alert(db, a, commit=False)

    if tls.self_signed:
        await alerting.fire_alert(
            db,
            type="security_self_signed",
            severity="warning",
            message=f"Service '{service.name}' uses a self-signed certificate — browsers will show a security warning.",
            service_id=service.id,
            server_id=server_id,
            commit=False,
        )
    else:
        open_alerts = (
            await db.execute(
                select(Alert).where(
                    Alert.service_id == service.id,
                    Alert.type == "security_self_signed",
                    Alert.state.in_(alerting.OPEN_STATES),
                )
            )
        ).scalars().all()
        for a in open_alerts:
            await alerting.resolve_alert(db, a, commit=False)

    if grade == "F":
        await alerting.fire_alert(
            db,
            type="security_grade_f",
            severity="warning",
            message=f"Service '{service.name}' received a security grade of F — critical configuration issues detected.",
            service_id=service.id,
            server_id=server_id,
            commit=False,
        )
    else:
        open_alerts = (
            await db.execute(
                select(Alert).where(
                    Alert.service_id == service.id,
                    Alert.type == "security_grade_f",
                    Alert.state.in_(alerting.OPEN_STATES),
                )
            )
        ).scalars().all()
        for a in open_alerts:
            await alerting.resolve_alert(db, a, commit=False)


async def run_security_check(service_id: str) -> None:
    """Run a full security audit for one HTTPS service. Never raises."""
    try:
        async with AsyncSessionLocal() as db:
            service = await db.get(Service, service_id)
            if service is None or not service.is_active or service.type != "http":
                return
            url = service.url or ""
            if not url.lower().startswith("https://"):
                return

            parsed = urlparse(url)
            hostname = parsed.hostname or ""
            port = parsed.port or 443
            if not hostname:
                return

            server = await db.get(Server, service.server_id)
            server_id = server.id if server else None
            org_id = str(server.org_id) if server else None

            tls = await asyncio.to_thread(_audit_tls_sync, hostname, port)
            hdr = await _audit_headers(url)
            score, grade, findings = _compute_score(tls, hdr)
            now = _now()

            scan = ServiceSecurityScan(
                service_id=service.id,
                scanned_at=now,
                grade=grade,
                score=score,
                tls_version=tls.tls_version,
                tls_ok=tls.tls_ok,
                cipher_suite=tls.cipher_suite,
                cipher_ok=tls.cipher_ok,
                pfs_supported=tls.pfs_supported,
                key_size=tls.key_size,
                key_size_ok=tls.key_size_ok,
                self_signed=tls.self_signed,
                ocsp_stapling=tls.ocsp_stapling,
                https_redirect=hdr.https_redirect,
                hsts=hdr.hsts,
                hsts_max_age=hdr.hsts_max_age,
                csp=hdr.csp,
                x_frame_options=hdr.x_frame_options,
                x_content_type=hdr.x_content_type,
                referrer_policy=hdr.referrer_policy,
                permissions_policy=hdr.permissions_policy,
                server_disclosure=hdr.server_disclosure,
                x_powered_by=hdr.x_powered_by,
                findings=findings,
            )
            db.add(scan)
            service.last_security_scan = now
            await db.flush()

            if tls.error is None:
                await _fire_security_alerts(db, service, tls, grade, server_id)
            await db.commit()

            if org_id:
                try:
                    await ws_manager.broadcast_org(org_id, {
                        "event": "service_security_updated",
                        "data": {
                            "service_id": service_id,
                            "grade": grade,
                            "score": score,
                            "scanned_at": now.isoformat(),
                        },
                    })
                except Exception:
                    logger.warning("security WS broadcast failed for service %s", service_id, exc_info=True)

    except Exception:
        logger.exception("run_security_check failed for service %s", service_id)
