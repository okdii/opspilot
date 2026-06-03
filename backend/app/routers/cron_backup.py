"""Phase 7 — Cron & Backup Job Monitoring (spec 09).

Public heartbeat ping endpoints (token-based, no auth) + authed CRUD for cron
and backup jobs. Status transitions are owned by the watchdog
(app/services/cron_watchdog.py); this router owns ingest (pings) and management.
"""
import base64
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.database import get_db
from app.deps import AdminUser, CurrentUser
from app.models.other import (
    Alert,
    BackupJob,
    BackupRun,
    CronJob,
    CronJobRun,
    Settings,
)
from app.models.server import Server
from app.models.user import UserOrganization
from app.schemas.cron_backup import (
    BackupJobCreate,
    BackupJobOut,
    BackupJobUpdate,
    BackupRunOut,
    CronJobCreate,
    CronJobOut,
    CronJobUpdate,
    CronRunOut,
)
from app.services.alerting import OPEN_STATES, resolve_alert
from app.services.cron_schedule import next_fire_after

router = APIRouter(tags=["cron-backup"])

_PAGE_SIZE = 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


# ── helpers ────────────────────────────────────────────────────────────────

def _format_bytes(n: int | None) -> str | None:
    if n is None:
        return None
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1024 or unit == "PB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    return f"{n} B"


async def _base_url(request: Request, db: AsyncSession) -> str:
    row = await db.scalar(select(Settings).where(Settings.id == 1))
    if row and row.base_url:
        return row.base_url.rstrip("/")
    if app_settings.opspilot_base_url:
        return app_settings.opspilot_base_url.rstrip("/")
    return str(request.base_url).rstrip("/")


def _ping_url(base: str, token: UUID) -> str:
    return f"{base}/ping/{token}"


async def _assert_org_access(org_id: str, user, db: AsyncSession) -> None:
    from app.models.organization import Organization

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


async def _get_server_for_access(server_id, user, db: AsyncSession) -> Server:
    server = await db.scalar(select(Server).where(Server.id == server_id, Server.is_active == True))
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
    return server


def _decode_cursor(cursor: str | None) -> datetime | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        return datetime.fromisoformat(raw)
    except Exception:
        raise HTTPException(400, detail={"error": "bad_cursor", "message": "Invalid cursor."})


def _encode_cursor(dt: datetime) -> str:
    return base64.urlsafe_b64encode(_aware(dt).isoformat().encode()).decode()


async def _resolve_open_alerts(db: AsyncSession, *, cron_job_id=None, backup_job_id=None, types=None) -> None:
    conds = [Alert.state.in_(OPEN_STATES)]
    if cron_job_id is not None:
        conds.append(Alert.cron_job_id == cron_job_id)
    if backup_job_id is not None:
        conds.append(Alert.backup_job_id == backup_job_id)
    if types:
        conds.append(Alert.type.in_(types))
    rows = (await db.execute(select(Alert).where(*conds))).scalars().all()
    for alert in rows:
        await resolve_alert(db, alert, send_email=False, commit=False)


# ── serialization ──────────────────────────────────────────────────────────

def _cron_out(job: CronJob, server_name: str, base: str) -> CronJobOut:
    last = _aware(job.last_ping_at)
    nxt = next_fire_after(job.schedule, last) if last else next_fire_after(job.schedule, _now())
    return CronJobOut(
        id=str(job.id),
        server_id=str(job.server_id),
        server_name=server_name,
        name=job.name,
        schedule=job.schedule,
        grace_period_min=job.grace_period_min,
        ping_url=_ping_url(base, job.ping_token),
        last_ping_at=last,
        start_ping_at=_aware(job.start_ping_at),
        last_duration_sec=job.last_duration_sec,
        status=job.status,
        next_expected_at=nxt,
    )


def _backup_out(job: BackupJob, server_name: str, base: str) -> BackupJobOut:
    from datetime import timedelta

    last = _aware(job.last_ping_at)
    anchor = last or _aware(job.created_at) or _now()
    nxt = anchor + timedelta(hours=job.expected_interval_hours)
    return BackupJobOut(
        id=str(job.id),
        server_id=str(job.server_id),
        server_name=server_name,
        name=job.name,
        description=job.description,
        expected_interval_hours=job.expected_interval_hours,
        ping_url=_ping_url(base, job.ping_token),
        last_ping_at=last,
        last_size_bytes=job.last_size_bytes,
        last_size_formatted=_format_bytes(job.last_size_bytes),
        last_status_text=job.last_status_text,
        previous_size_bytes=job.previous_size_bytes,
        status=job.status,
        next_expected_at=nxt,
    )


# ════════════════════════════════════════════════════════════════════════════
# PUBLIC PING ENDPOINTS (no auth — token IS the credential)
# ════════════════════════════════════════════════════════════════════════════

@router.get("/ping/{token}")
async def ping_get(
    token: str,
    request: Request,
    event: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Cron heartbeat (GET). Also accepted for backup jobs (some tools use GET)."""
    try:
        token_uuid = UUID(token)
    except ValueError:
        raise HTTPException(404, detail={"error": "unknown token"})

    cron = await db.scalar(select(CronJob).where(CronJob.ping_token == token_uuid))
    if cron is not None:
        return await _handle_cron_ping(db, cron, event)

    backup = await db.scalar(select(BackupJob).where(BackupJob.ping_token == token_uuid))
    if backup is not None:
        # GET on a backup token → zero-value payload (spec §9.2 note).
        return await _handle_backup_ping(db, backup, size_bytes=0, exit_code=0, status="success")

    raise HTTPException(404, detail={"error": "unknown token"})


@router.post("/ping/{token}")
async def ping_post(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Backup heartbeat (POST form body). Falls back to cron if token is a cron job."""
    try:
        token_uuid = UUID(token)
    except ValueError:
        raise HTTPException(404, detail={"error": "unknown token"})

    form = {}
    try:
        form = dict(await request.form())
    except Exception:
        form = {}

    def _as_int(key: str, default: int) -> int:
        val = form.get(key)
        if val is None or val == "":
            return default
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    backup = await db.scalar(select(BackupJob).where(BackupJob.ping_token == token_uuid))
    if backup is not None:
        return await _handle_backup_ping(
            db,
            backup,
            size_bytes=_as_int("size_bytes", 0),
            exit_code=_as_int("exit_code", 0),
            status=str(form.get("status") or "success"),
        )

    cron = await db.scalar(select(CronJob).where(CronJob.ping_token == token_uuid))
    if cron is not None:
        return await _handle_cron_ping(db, cron, str(form.get("event") or "") or None)

    raise HTTPException(404, detail={"error": "unknown token"})


async def _handle_cron_ping(db: AsyncSession, job: CronJob, event: str | None):
    now = _now()

    if event == "start":
        job.start_ping_at = now
        await db.commit()
        return {"ok": True}

    # Plain ping or ?event=end → record a successful run.
    duration = None
    start = _aware(job.start_ping_at)
    if start is not None:
        duration = max(0, int((now - start).total_seconds()))

    job.last_ping_at = now
    job.last_duration_sec = duration
    job.start_ping_at = None
    job.status = "healthy"
    db.add(
        CronJobRun(
            cron_job_id=job.id,
            ran_at=now,
            duration_sec=duration,
            outcome="success",
        )
    )
    await db.flush()
    await _resolve_open_alerts(db, cron_job_id=job.id, types=["cron_missing"])
    await db.commit()
    return {"ok": True}


async def _handle_backup_ping(db: AsyncSession, job: BackupJob, *, size_bytes: int, exit_code: int, status: str):
    from app.services.alerting import fire_alert

    now = _now()
    prev = job.previous_size_bytes

    # Determine outcome — exit_code is authoritative (spec §9.2 / §12).
    outcome = "success"
    fire_failure = False
    fire_size_drop = False

    if exit_code != 0:
        outcome = "failed"
        fire_failure = True
    elif size_bytes == 0:
        outcome = "failed"
        fire_size_drop = True  # size is zero
    elif prev is not None and size_bytes < prev * 0.80:
        outcome = "success"  # run completed but suspicious shrink
        fire_size_drop = True

    job.last_ping_at = now
    job.last_size_bytes = size_bytes
    job.last_status_text = status
    job.status = "healthy"
    if outcome == "success":
        job.previous_size_bytes = size_bytes  # baseline only advances on success

    db.add(
        BackupRun(
            backup_job_id=job.id,
            ran_at=now,
            size_bytes=size_bytes,
            exit_code=exit_code,
            outcome=outcome,
        )
    )
    await db.flush()

    # A ping arrived → clear any open "missing" alert regardless of outcome.
    await _resolve_open_alerts(db, backup_job_id=job.id, types=["backup_missing"])

    if fire_failure:
        await fire_alert(
            db,
            type="backup_failure",
            severity="critical",
            message=f"Backup job '{job.name}' failed (exit code {exit_code}).",
            server_id=job.server_id,
            backup_job_id=job.id,
            commit=False,
        )
    if fire_size_drop:
        if size_bytes == 0:
            msg = f"Backup job '{job.name}' produced a zero-byte backup."
        else:
            msg = f"Backup job '{job.name}' size dropped >20% (was {prev}, now {size_bytes} bytes)."
        await fire_alert(
            db,
            type="backup_size_drop",
            severity="warning",
            message=msg,
            server_id=job.server_id,
            backup_job_id=job.id,
            commit=False,
        )

    await db.commit()
    return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
# AUTHED CRUD — CRON JOBS
# ════════════════════════════════════════════════════════════════════════════

@router.get("/api/organizations/{org_id}/cron-jobs", response_model=list[CronJobOut])
async def list_cron_jobs(org_id: str, request: Request, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_org_access(org_id, user, db)
    base = await _base_url(request, db)
    rows = (
        await db.execute(
            select(CronJob, Server.name)
            .join(Server, Server.id == CronJob.server_id)
            .where(Server.org_id == org_id, Server.is_active == True)
            .order_by(CronJob.name)
        )
    ).all()
    return [_cron_out(job, name, base) for job, name in rows]


@router.post("/api/cron-jobs", response_model=CronJobOut, status_code=201)
async def create_cron_job(body: CronJobCreate, request: Request, user: AdminUser, db: AsyncSession = Depends(get_db)):
    server = await _get_server_for_access(body.server_id, user, db)
    job = CronJob(
        server_id=server.id,
        name=body.name,
        schedule=body.schedule,
        grace_period_min=body.grace_period_min,
        status="healthy",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    base = await _base_url(request, db)
    return _cron_out(job, server.name, base)


@router.patch("/api/cron-jobs/{job_id}", response_model=CronJobOut)
async def update_cron_job(job_id: str, body: CronJobUpdate, request: Request, user: AdminUser, db: AsyncSession = Depends(get_db)):
    job = await db.scalar(select(CronJob).where(CronJob.id == job_id))
    if not job:
        raise HTTPException(404, detail={"error": "not_found", "message": "Cron job not found."})
    server = await _get_server_for_access(job.server_id, user, db)

    if body.name is not None:
        job.name = body.name
    if body.schedule is not None:
        job.schedule = body.schedule
    if body.grace_period_min is not None:
        job.grace_period_min = body.grace_period_min

    await db.commit()
    await db.refresh(job)
    base = await _base_url(request, db)
    return _cron_out(job, server.name, base)


@router.delete("/api/cron-jobs/{job_id}", status_code=204)
async def delete_cron_job(job_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)):
    job = await db.scalar(select(CronJob).where(CronJob.id == job_id))
    if not job:
        raise HTTPException(404, detail={"error": "not_found", "message": "Cron job not found."})
    await _get_server_for_access(job.server_id, user, db)

    await _resolve_open_alerts(db, cron_job_id=job.id)
    await db.delete(job)
    await db.commit()
    return None


@router.get("/api/cron-jobs/{job_id}/runs")
async def list_cron_runs(
    job_id: str,
    user: CurrentUser,
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    job = await db.scalar(select(CronJob).where(CronJob.id == job_id))
    if not job:
        raise HTTPException(404, detail={"error": "not_found", "message": "Cron job not found."})
    await _get_server_for_access(job.server_id, user, db)

    before = _decode_cursor(cursor)
    q = select(CronJobRun).where(CronJobRun.cron_job_id == job_id)
    if before is not None:
        q = q.where(CronJobRun.ran_at < before)
    q = q.order_by(CronJobRun.ran_at.desc()).limit(_PAGE_SIZE + 1)
    rows = (await db.execute(q)).scalars().all()

    next_cursor = None
    if len(rows) > _PAGE_SIZE:
        rows = rows[:_PAGE_SIZE]
        next_cursor = _encode_cursor(rows[-1].ran_at)

    return {
        "runs": [
            CronRunOut(
                id=str(r.id),
                ran_at=_aware(r.ran_at),
                duration_sec=r.duration_sec,
                outcome=r.outcome,
            )
            for r in rows
        ],
        "next_cursor": next_cursor,
    }


@router.post("/api/cron-jobs/{job_id}/regenerate-token", response_model=CronJobOut)
async def regenerate_cron_token(job_id: str, request: Request, user: AdminUser, db: AsyncSession = Depends(get_db)):
    import uuid as _uuid

    job = await db.scalar(select(CronJob).where(CronJob.id == job_id))
    if not job:
        raise HTTPException(404, detail={"error": "not_found", "message": "Cron job not found."})
    server = await _get_server_for_access(job.server_id, user, db)

    job.ping_token = _uuid.uuid4()
    await db.commit()
    await db.refresh(job)
    base = await _base_url(request, db)
    return _cron_out(job, server.name, base)


# ════════════════════════════════════════════════════════════════════════════
# AUTHED CRUD — BACKUP JOBS
# ════════════════════════════════════════════════════════════════════════════

@router.get("/api/organizations/{org_id}/backup-jobs", response_model=list[BackupJobOut])
async def list_backup_jobs(org_id: str, request: Request, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_org_access(org_id, user, db)
    base = await _base_url(request, db)
    rows = (
        await db.execute(
            select(BackupJob, Server.name)
            .join(Server, Server.id == BackupJob.server_id)
            .where(Server.org_id == org_id, Server.is_active == True)
            .order_by(BackupJob.name)
        )
    ).all()
    return [_backup_out(job, name, base) for job, name in rows]


@router.post("/api/backup-jobs", response_model=BackupJobOut, status_code=201)
async def create_backup_job(body: BackupJobCreate, request: Request, user: AdminUser, db: AsyncSession = Depends(get_db)):
    server = await _get_server_for_access(body.server_id, user, db)
    job = BackupJob(
        server_id=server.id,
        name=body.name,
        description=body.description,
        expected_interval_hours=body.expected_interval_hours,
        status="healthy",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    base = await _base_url(request, db)
    return _backup_out(job, server.name, base)


@router.patch("/api/backup-jobs/{job_id}", response_model=BackupJobOut)
async def update_backup_job(job_id: str, body: BackupJobUpdate, request: Request, user: AdminUser, db: AsyncSession = Depends(get_db)):
    job = await db.scalar(select(BackupJob).where(BackupJob.id == job_id))
    if not job:
        raise HTTPException(404, detail={"error": "not_found", "message": "Backup job not found."})
    server = await _get_server_for_access(job.server_id, user, db)

    if body.name is not None:
        job.name = body.name
    if body.description is not None:
        job.description = body.description
    if body.expected_interval_hours is not None:
        job.expected_interval_hours = body.expected_interval_hours

    await db.commit()
    await db.refresh(job)
    base = await _base_url(request, db)
    return _backup_out(job, server.name, base)


@router.delete("/api/backup-jobs/{job_id}", status_code=204)
async def delete_backup_job(job_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)):
    job = await db.scalar(select(BackupJob).where(BackupJob.id == job_id))
    if not job:
        raise HTTPException(404, detail={"error": "not_found", "message": "Backup job not found."})
    await _get_server_for_access(job.server_id, user, db)

    await _resolve_open_alerts(db, backup_job_id=job.id)
    await db.delete(job)
    await db.commit()
    return None


@router.get("/api/backup-jobs/{job_id}/runs")
async def list_backup_runs(
    job_id: str,
    user: CurrentUser,
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    job = await db.scalar(select(BackupJob).where(BackupJob.id == job_id))
    if not job:
        raise HTTPException(404, detail={"error": "not_found", "message": "Backup job not found."})
    await _get_server_for_access(job.server_id, user, db)

    before = _decode_cursor(cursor)
    q = select(BackupRun).where(BackupRun.backup_job_id == job_id)
    if before is not None:
        q = q.where(BackupRun.ran_at < before)
    q = q.order_by(BackupRun.ran_at.desc()).limit(_PAGE_SIZE + 1)
    rows = (await db.execute(q)).scalars().all()

    next_cursor = None
    if len(rows) > _PAGE_SIZE:
        rows = rows[:_PAGE_SIZE]
        next_cursor = _encode_cursor(rows[-1].ran_at)

    return {
        "runs": [
            BackupRunOut(
                id=str(r.id),
                ran_at=_aware(r.ran_at),
                size_bytes=r.size_bytes,
                size_formatted=_format_bytes(r.size_bytes),
                exit_code=r.exit_code,
                outcome=r.outcome,
            )
            for r in rows
        ],
        "next_cursor": next_cursor,
    }


@router.post("/api/backup-jobs/{job_id}/regenerate-token", response_model=BackupJobOut)
async def regenerate_backup_token(job_id: str, request: Request, user: AdminUser, db: AsyncSession = Depends(get_db)):
    import uuid as _uuid

    job = await db.scalar(select(BackupJob).where(BackupJob.id == job_id))
    if not job:
        raise HTTPException(404, detail={"error": "not_found", "message": "Backup job not found."})
    server = await _get_server_for_access(job.server_id, user, db)

    job.ping_token = _uuid.uuid4()
    await db.commit()
    await db.refresh(job)
    base = await _base_url(request, db)
    return _backup_out(job, server.name, base)
