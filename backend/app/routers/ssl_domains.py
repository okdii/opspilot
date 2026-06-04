"""SSL & Domain Monitoring router (spec 07 §13).

Combined list + CRUD for Domains and SSLCerts, plus manual re-check triggers.
First-check on add and manual re-checks are scheduled as one-shot APScheduler
`date` jobs (run_date = now + 2s) that run the same check logic as the daily job
for a single record.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AdminUser, CurrentUser
from app.jobs.scheduler import scheduler
from app.models.organization import Organization
from app.models.other import Alert, Domain, Service, SSLCert
from app.models.server import Server
from app.models.user import UserOrganization
from app.schemas.ssl_domains import (
    DomainCreate,
    DomainOut,
    DomainUpdate,
    ServiceSslOut,
    SSLCertCreate,
    SSLCertOut,
    SSLCertUpdate,
    SSLDomainsResponse,
)
from app.services import ssl_checker

router = APIRouter(tags=["ssl-domains"])

# In-process manual-trigger rate limiting (5 min per record). Resets on restart.
_MANUAL_CHECK_WINDOW = timedelta(minutes=5)
_last_manual_check: dict[str, datetime] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


async def _get_domain_for_admin(domain_id: str, db: AsyncSession) -> Domain:
    domain = await db.scalar(select(Domain).where(Domain.id == domain_id))
    if not domain:
        raise HTTPException(404, detail={"error": "not_found", "message": "Domain not found."})
    return domain


async def _get_ssl_cert_for_admin(ssl_cert_id: str, db: AsyncSession) -> SSLCert:
    cert = await db.scalar(select(SSLCert).where(SSLCert.id == ssl_cert_id))
    if not cert:
        raise HTTPException(404, detail={"error": "not_found", "message": "SSL certificate not found."})
    return cert


def _domain_out(d: Domain) -> DomainOut:
    return DomainOut.model_validate(d)


def _ssl_out(c: SSLCert, domain_name: str | None) -> SSLCertOut:
    return SSLCertOut(
        id=c.id,
        domain_id=c.domain_id,
        domain=domain_name,
        port=c.port,
        issuer=c.issuer,
        expiry_date=c.expiry_date,
        days_remaining=c.days_remaining,
        warn_days=c.warn_days,
        critical_days=c.critical_days,
        last_checked=c.last_checked,
        status=c.status,
    )


def _schedule_once(job_id: str, func, *args) -> None:
    """Schedule a one-shot check (date trigger, now + 2s)."""
    scheduler.add_job(
        func,
        "date",
        run_date=_now() + timedelta(seconds=2),
        args=list(args),
        id=job_id,
        replace_existing=True,
    )


# ── Combined list ─────────────────────────────────────────────────────────────

@router.get("/api/organizations/{org_id}/ssl-domains", response_model=SSLDomainsResponse)
async def list_ssl_domains(org_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_org_access(org_id, user, db)

    domains = (
        await db.execute(select(Domain).where(Domain.org_id == org_id).order_by(Domain.domain))
    ).scalars().all()

    domain_ids = [d.id for d in domains]
    domain_name_by_id = {d.id: d.domain for d in domains}

    ssl_certs = []
    if domain_ids:
        ssl_certs = (
            await db.execute(select(SSLCert).where(SSLCert.domain_id.in_(domain_ids)))
        ).scalars().all()

    # Fetch HTTPS services for this org
    server_ids_result = await db.execute(
        select(Server.id).where(Server.org_id == org_id)
    )
    server_ids = [str(sid) for sid in server_ids_result.scalars().all()]
    service_ssl_rows: list[Service] = []
    if server_ids:
        service_ssl_rows = (
            await db.execute(
                select(Service).where(
                    Service.server_id.in_(server_ids),
                    Service.ssl_enabled == True,  # noqa: E712
                )
            )
        ).scalars().all()

    return SSLDomainsResponse(
        domains=[_domain_out(d) for d in domains],
        ssl_certs=[_ssl_out(c, domain_name_by_id.get(c.domain_id)) for c in ssl_certs],
        service_ssl=[ServiceSslOut.model_validate(s) for s in service_ssl_rows],
    )


# ── Domain CRUD ───────────────────────────────────────────────────────────────

@router.post("/api/domains", status_code=201, response_model=DomainOut)
async def create_domain(body: DomainCreate, user: AdminUser, db: AsyncSession = Depends(get_db)):
    await _assert_org_access(str(body.org_id), user, db)

    existing = await db.scalar(
        select(Domain).where(Domain.org_id == body.org_id, Domain.domain == body.domain)
    )
    if existing:
        raise HTTPException(
            409,
            detail={"error": "duplicate", "message": f"{body.domain} is already tracked in this organisation."},
        )

    domain = Domain(
        org_id=body.org_id,
        domain=body.domain,
        warn_days=body.warn_days,
        critical_days=body.critical_days,
        status="checking",
    )
    db.add(domain)
    await db.commit()
    await db.refresh(domain)

    _schedule_once(f"domain_check_once:{domain.id}", ssl_checker.check_domain_by_id, str(domain.id))
    return _domain_out(domain)


@router.patch("/api/domains/{domain_id}", response_model=DomainOut)
async def update_domain(domain_id: str, body: DomainUpdate, user: AdminUser, db: AsyncSession = Depends(get_db)):
    domain = await _get_domain_for_admin(domain_id, db)

    warn = body.warn_days if body.warn_days is not None else domain.warn_days
    crit = body.critical_days if body.critical_days is not None else domain.critical_days
    if not (1 <= warn <= 365) or not (1 <= crit <= 365):
        raise HTTPException(422, detail={"error": "validation_error", "message": "Thresholds must be between 1 and 365 days."})
    if crit >= warn:
        raise HTTPException(422, detail={"error": "validation_error", "message": "Critical threshold must be lower than warning threshold."})

    domain.warn_days = warn
    domain.critical_days = crit
    await db.commit()
    await db.refresh(domain)
    return _domain_out(domain)


@router.delete("/api/domains/{domain_id}", status_code=204)
async def delete_domain(domain_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)):
    domain = await _get_domain_for_admin(domain_id, db)

    has_cert = await db.scalar(select(SSLCert.id).where(SSLCert.domain_id == domain_id).limit(1))
    if has_cert:
        raise HTTPException(
            409,
            detail={
                "error": "ssl_cert_exists",
                "message": f"{domain.domain} has a linked SSL certificate. Delete the SSL cert first, then delete the domain.",
            },
        )

    await db.delete(domain)
    await db.commit()
    return None


@router.post("/api/domains/{domain_id}/check")
async def check_domain_now(domain_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)):
    domain = await _get_domain_for_admin(domain_id, db)
    _enforce_rate_limit(f"domain:{domain.id}")
    _schedule_once(f"domain_check_once:{domain.id}", ssl_checker.check_domain_by_id, str(domain.id))
    return {"ok": True}


# ── SSL Cert CRUD ─────────────────────────────────────────────────────────────

@router.post("/api/ssl-certs", status_code=201, response_model=SSLCertOut)
async def create_ssl_cert(body: SSLCertCreate, user: AdminUser, db: AsyncSession = Depends(get_db)):
    domain = await db.scalar(select(Domain).where(Domain.id == body.domain_id))
    if not domain:
        raise HTTPException(404, detail={"error": "not_found", "message": "Parent domain not found."})
    await _assert_org_access(str(domain.org_id), user, db)

    cert = SSLCert(
        domain_id=body.domain_id,
        port=body.port,
        warn_days=body.warn_days,
        critical_days=body.critical_days,
        status="checking",
    )
    db.add(cert)
    await db.commit()
    await db.refresh(cert)

    _schedule_once(f"ssl_check_once:{cert.id}", ssl_checker.check_ssl_cert_by_id, str(cert.id))
    return _ssl_out(cert, domain.domain)


@router.patch("/api/ssl-certs/{ssl_cert_id}", response_model=SSLCertOut)
async def update_ssl_cert(ssl_cert_id: str, body: SSLCertUpdate, user: AdminUser, db: AsyncSession = Depends(get_db)):
    cert = await _get_ssl_cert_for_admin(ssl_cert_id, db)

    warn = body.warn_days if body.warn_days is not None else cert.warn_days
    crit = body.critical_days if body.critical_days is not None else cert.critical_days
    if not (1 <= warn <= 365) or not (1 <= crit <= 365):
        raise HTTPException(422, detail={"error": "validation_error", "message": "Thresholds must be between 1 and 365 days."})
    if crit >= warn:
        raise HTTPException(422, detail={"error": "validation_error", "message": "Critical threshold must be lower than warning threshold."})
    if body.port is not None and not (1 <= body.port <= 65535):
        raise HTTPException(422, detail={"error": "validation_error", "message": "Enter a valid port number."})

    if body.port is not None:
        cert.port = body.port
    cert.warn_days = warn
    cert.critical_days = crit
    await db.commit()
    await db.refresh(cert)

    domain = await db.get(Domain, cert.domain_id)
    return _ssl_out(cert, domain.domain if domain else None)


@router.delete("/api/ssl-certs/{ssl_cert_id}", status_code=204)
async def delete_ssl_cert(ssl_cert_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)):
    cert = await _get_ssl_cert_for_admin(ssl_cert_id, db)
    await db.delete(cert)
    await db.commit()
    return None


@router.post("/api/ssl-certs/{ssl_cert_id}/check")
async def check_ssl_cert_now(ssl_cert_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)):
    cert = await _get_ssl_cert_for_admin(ssl_cert_id, db)
    _enforce_rate_limit(f"ssl:{cert.id}")
    _schedule_once(f"ssl_check_once:{cert.id}", ssl_checker.check_ssl_cert_by_id, str(cert.id))
    return {"ok": True}


# ── Rate limit ────────────────────────────────────────────────────────────────

def _enforce_rate_limit(key: str) -> None:
    now = _now()
    last = _last_manual_check.get(key)
    if last is not None and now < last + _MANUAL_CHECK_WINDOW:
        retry_after = int((last + _MANUAL_CHECK_WINDOW - now).total_seconds())
        raise HTTPException(429, detail={"error": "rate_limited", "retry_after_sec": retry_after})
    _last_manual_check[key] = now
