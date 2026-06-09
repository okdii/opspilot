"""Phase 9 — Unified Job Monitoring (spec §6).

Public heartbeat ping endpoints (token-based, no auth) + authed CRUD for
monitored jobs. Status transitions are owned by the watchdog
(app/services/cron_watchdog.py); this router owns ingest (pings) and management.
"""
import base64
import uuid as _uuid
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
    JobRun,
    MonitoredJob,
    Settings,
)
from app.models.server import Server
from app.models.user import UserOrganization
from app.schemas.job import (
    JobCreate,
    JobOut,
    JobRunOut,
    JobUpdate,
    TodayRunOut,
)
from app.services.alerting import OPEN_STATES, fire_alert, resolve_alert
from app.services.cron_schedule import next_fire_after

router = APIRouter(tags=["cron-backup"])

_PAGE_SIZE = 20


# ── time helpers ───────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


# ── misc helpers ───────────────────────────────────────────────────────────

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


async def _resolve_job_alerts(db: AsyncSession, job_id) -> None:
    conds = [Alert.state.in_(OPEN_STATES), Alert.job_id == job_id]
    rows = (await db.execute(select(Alert).where(*conds))).scalars().all()
    for alert in rows:
        await resolve_alert(db, alert, send_email=False, commit=False)


# ── serialization ──────────────────────────────────────────────────────────

def _job_out(job: MonitoredJob, server_name: str, base: str) -> JobOut:
    last = _aware(job.last_ping_at)
    nxt = next_fire_after(job.schedule, last) if last else next_fire_after(job.schedule, _now())
    return JobOut(
        id=str(job.id),
        server_id=str(job.server_id),
        server_name=server_name,
        name=job.name,
        description=job.description,
        schedule=job.schedule,
        grace_period_min=job.grace_period_min,
        ping_url=_ping_url(base, job.ping_token),
        status=job.status,
        last_ping_at=last,
        start_ping_at=_aware(job.start_ping_at),
        last_duration_sec=job.last_duration_sec,
        last_size_bytes=job.last_size_bytes,
        last_size_formatted=job.last_size_formatted,
        last_files_count=job.last_files_count,
        last_exit_code=job.last_exit_code,
        last_label=job.last_label,
        next_expected_at=nxt,
    )


# ════════════════════════════════════════════════════════════════════════════
# PUBLIC PING ENDPOINTS (no auth — token IS the credential)
# ════════════════════════════════════════════════════════════════════════════

@router.get("/ping/{token}")
async def ping_get(
    token: str,
    event: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Heartbeat GET ping. Supports ?event=start for start/end timing."""
    try:
        token_uuid = UUID(token)
    except ValueError:
        raise HTTPException(404, detail={"error": "unknown token"})

    job = await db.scalar(select(MonitoredJob).where(MonitoredJob.ping_token == token_uuid))
    if job is None:
        raise HTTPException(404, detail={"error": "unknown token"})

    now = _now()

    if event == "start":
        job.start_ping_at = now
        await db.commit()
        return {"ok": True}

    # Plain end ping or ?event=end → record successful run.
    duration = None
    start = _aware(job.start_ping_at)
    if start is not None:
        duration = max(0, int((now - start).total_seconds()))

    started_at_value = _aware(job.start_ping_at)
    job.last_ping_at = now
    job.last_duration_sec = duration
    job.start_ping_at = None
    job.status = "healthy"
    db.add(
        JobRun(
            job_id=job.id,
            ran_at=now,
            outcome="success",
            duration_sec=duration,
            started_at=started_at_value,
        )
    )
    await db.flush()
    await _resolve_job_alerts(db, job.id)
    await db.commit()
    return {"ok": True}


@router.post("/ping/{token}")
async def ping_post(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Heartbeat POST ping. Accepts optional form fields: size_bytes, exit_code,
    files_count, event. All optional — only fields present are applied."""
    try:
        token_uuid = UUID(token)
    except ValueError:
        raise HTTPException(404, detail={"error": "unknown token"})

    job = await db.scalar(select(MonitoredJob).where(MonitoredJob.ping_token == token_uuid))
    if job is None:
        raise HTTPException(404, detail={"error": "unknown token"})

    # Parse optional form fields — None when absent.
    form: dict = {}
    try:
        form = dict(await request.form())
    except Exception:
        form = {}

    def _as_optional_int(key: str) -> int | None:
        val = form.get(key)
        if val is None or val == "":
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    event: str | None = form.get("event") or None
    size_bytes: int | None = _as_optional_int("size_bytes")
    exit_code: int | None = _as_optional_int("exit_code")
    files_count: int | None = _as_optional_int("files_count")
    label: str | None = form.get("label") or None

    now = _now()

    if event == "start":
        job.start_ping_at = now
        await db.commit()
        return {"ok": True}

    # End ping (no event or event=end).
    prev = job.previous_size_bytes

    # Determine outcome.
    outcome = "success"
    fire_failure = False
    fire_size_drop = False

    if exit_code is not None and exit_code != 0:
        outcome = "failed"
        fire_failure = True
    elif size_bytes is not None and size_bytes == 0:
        outcome = "failed"
        fire_size_drop = True
    elif size_bytes is not None and prev is not None and size_bytes < prev * 0.80:
        outcome = "success"  # run completed but suspicious shrink
        fire_size_drop = True

    # Compute duration from start_ping_at if available.
    duration = None
    start = _aware(job.start_ping_at)
    if start is not None:
        duration = max(0, int((now - start).total_seconds()))

    # Update job fields — only touch fields when present in form.
    started_at_value = _aware(job.start_ping_at)
    job.last_ping_at = now
    job.last_duration_sec = duration
    job.start_ping_at = None
    if size_bytes is not None:
        job.last_size_bytes = size_bytes
        job.last_size_formatted = _format_bytes(size_bytes)
    if files_count is not None:
        job.last_files_count = files_count
    if exit_code is not None:
        job.last_exit_code = exit_code
    if label is not None:
        job.last_label = label
    if outcome == "success" and size_bytes is not None:
        job.previous_size_bytes = size_bytes  # baseline advances only on success
    job.status = "healthy"

    db.add(
        JobRun(
            job_id=job.id,
            ran_at=now,
            outcome=outcome,
            duration_sec=duration,
            size_bytes=size_bytes,
            files_count=files_count,
            exit_code=exit_code,
            label=label,
            started_at=started_at_value,
        )
    )
    await db.flush()

    # Resolve any open job_missing alerts — a ping arrived regardless of outcome.
    await _resolve_job_alerts(db, job.id)

    if fire_failure:
        await fire_alert(
            db,
            type="job_failure",
            severity="critical",
            message=f"Job '{job.name}' failed (exit code {exit_code}).",
            server_id=job.server_id,
            job_id=job.id,
            commit=False,
        )
    if fire_size_drop:
        if size_bytes == 0:
            msg = f"Job '{job.name}' produced a zero-byte backup."
        else:
            msg = f"Job '{job.name}' size dropped >20% (was {prev}, now {size_bytes} bytes)."
        await fire_alert(
            db,
            type="job_size_drop",
            severity="warning",
            message=msg,
            server_id=job.server_id,
            job_id=job.id,
            commit=False,
        )

    await db.commit()
    return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
# AUTHED CRUD — JOBS
# ════════════════════════════════════════════════════════════════════════════

@router.get("/api/organizations/{org_id}/jobs", response_model=list[JobOut])
async def list_jobs(
    org_id: str,
    request: Request,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _assert_org_access(org_id, user, db)
    base = await _base_url(request, db)
    rows = (
        await db.execute(
            select(MonitoredJob, Server.name)
            .join(Server, Server.id == MonitoredJob.server_id)
            .where(Server.org_id == org_id, Server.is_active == True)
            .order_by(Server.name, MonitoredJob.name)
        )
    ).all()
    return [_job_out(job, name, base) for job, name in rows]


@router.post("/api/jobs", response_model=JobOut, status_code=201)
async def create_job(
    body: JobCreate,
    request: Request,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    server = await _get_server_for_access(body.server_id, user, db)
    job = MonitoredJob(
        server_id=server.id,
        name=body.name,
        schedule=body.schedule,
        grace_period_min=body.grace_period_min,
        description=body.description,
        status="healthy",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    base = await _base_url(request, db)
    return _job_out(job, server.name, base)


@router.patch("/api/jobs/{job_id}", response_model=JobOut)
async def update_job(
    job_id: str,
    body: JobUpdate,
    request: Request,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    job = await db.scalar(select(MonitoredJob).where(MonitoredJob.id == job_id))
    if not job:
        raise HTTPException(404, detail={"error": "not_found", "message": "Job not found."})
    server = await _get_server_for_access(job.server_id, user, db)

    if body.name is not None:
        job.name = body.name
    if body.schedule is not None:
        job.schedule = body.schedule
    if body.grace_period_min is not None:
        job.grace_period_min = body.grace_period_min
    if body.description is not None:
        job.description = body.description

    await db.commit()
    await db.refresh(job)
    base = await _base_url(request, db)
    return _job_out(job, server.name, base)


@router.delete("/api/jobs/{job_id}", status_code=204)
async def delete_job(
    job_id: str,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    job = await db.scalar(select(MonitoredJob).where(MonitoredJob.id == job_id))
    if not job:
        raise HTTPException(404, detail={"error": "not_found", "message": "Job not found."})
    await _get_server_for_access(job.server_id, user, db)

    await _resolve_job_alerts(db, job.id)
    await db.delete(job)
    await db.commit()
    return None


@router.get("/api/jobs/{job_id}/runs")
async def list_job_runs(
    job_id: str,
    user: CurrentUser,
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    job = await db.scalar(select(MonitoredJob).where(MonitoredJob.id == job_id))
    if not job:
        raise HTTPException(404, detail={"error": "not_found", "message": "Job not found."})
    await _get_server_for_access(job.server_id, user, db)

    before = _decode_cursor(cursor)
    q = select(JobRun).where(JobRun.job_id == job_id)
    if before is not None:
        q = q.where(JobRun.ran_at < before)
    q = q.order_by(JobRun.ran_at.desc()).limit(_PAGE_SIZE + 1)
    rows = (await db.execute(q)).scalars().all()

    next_cursor = None
    if len(rows) > _PAGE_SIZE:
        rows = rows[:_PAGE_SIZE]
        next_cursor = _encode_cursor(rows[-1].ran_at)

    return {
        "runs": [
            JobRunOut(
                id=str(r.id),
                ran_at=_aware(r.ran_at),
                outcome=r.outcome,
                duration_sec=r.duration_sec,
                size_bytes=r.size_bytes,
                size_formatted=_format_bytes(r.size_bytes),
                files_count=r.files_count,
                exit_code=r.exit_code,
                label=r.label,
                started_at=_aware(r.started_at),
            )
            for r in rows
        ],
        "next_cursor": next_cursor,
    }


@router.get("/api/organizations/{org_id}/runs/today")
async def list_today_runs(
    org_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Return all job runs recorded today (UTC) for the given organisation."""
    await _assert_org_access(org_id, user, db)
    today_utc = datetime.now(timezone.utc).date()
    today_start = datetime(today_utc.year, today_utc.month, today_utc.day, tzinfo=timezone.utc)
    now = _now()
    rows = (
        await db.execute(
            select(JobRun, MonitoredJob.name.label("job_name"), Server.name.label("server_name"))
            .join(MonitoredJob, MonitoredJob.id == JobRun.job_id)
            .join(Server, Server.id == MonitoredJob.server_id)
            .where(
                Server.org_id == org_id,
                JobRun.ran_at >= today_start,
                JobRun.ran_at <= now,
            )
            .order_by(JobRun.ran_at.desc())
        )
    ).all()
    return [
        TodayRunOut(
            id=str(r.id),
            ran_at=_aware(r.ran_at),
            started_at=_aware(r.started_at),
            outcome=r.outcome,
            duration_sec=r.duration_sec,
            size_bytes=r.size_bytes,
            size_formatted=_format_bytes(r.size_bytes),
            files_count=r.files_count,
            exit_code=r.exit_code,
            label=r.label,
            job_id=str(r.job_id),
            job_name=job_name,
            server_name=server_name,
        )
        for r, job_name, server_name in rows
    ]


@router.post("/api/jobs/{job_id}/regenerate-token", response_model=JobOut)
async def regenerate_token(
    job_id: str,
    request: Request,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    job = await db.scalar(select(MonitoredJob).where(MonitoredJob.id == job_id))
    if not job:
        raise HTTPException(404, detail={"error": "not_found", "message": "Job not found."})
    server = await _get_server_for_access(job.server_id, user, db)

    job.ping_token = _uuid.uuid4()
    await db.commit()
    await db.refresh(job)
    base = await _base_url(request, db)
    return _job_out(job, server.name, base)
