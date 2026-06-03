"""Cron & Backup watchdog (spec 09 §9.3).

APScheduler tick (every 60s, job id ``cron_backup_watchdog``). For every cron and
backup job not already in ``missing`` status it computes the next-expected window
and transitions status Healthy → Late → Missing. On crossing into ``missing`` it
writes a ``missed`` run row and fires the appropriate alert via the LIVE
``fire_alert`` seam. Once ``missing`` it stops re-firing until a ping resets the
job to ``healthy``.

Backup window: the persisted BackupJob model has no cron schedule, so the
watchdog derives the expected window from ``expected_interval_hours`` plus the
per-job grace. Cron jobs use their cron expression + ``grace_period_min``.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.other import BackupJob, BackupRun, CronJob, CronJobRun
from app.services.alerting import fire_alert
from app.services.cron_schedule import next_fire_after

logger = logging.getLogger(__name__)

# Default grace for backup jobs (the model carries no per-job grace column).
_BACKUP_GRACE = timedelta(minutes=30)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _cron_base(job: CronJob) -> datetime:
    """Anchor for next-expected computation: last ping, else created_at, else now.

    CronJob has no created_at column in the model, so fall back to now() — a job
    with no ping yet is healthy until its first scheduled window elapses."""
    base = _aware(job.last_ping_at)
    if base is not None:
        return base
    return _now()


async def _evaluate_cron(db: AsyncSession, job: CronJob, now: datetime) -> None:
    next_expected = next_fire_after(job.schedule, _cron_base(job))
    if next_expected is None:
        # Invalid schedule — monitoring paused (spec §12). Do not fire.
        return

    grace = timedelta(minutes=job.grace_period_min)
    if now < next_expected:
        new_status = "healthy"
    elif now < next_expected + grace:
        new_status = "late"
    else:
        new_status = "missing"

    if new_status == "missing":
        db.add(
            CronJobRun(
                cron_job_id=job.id,
                ran_at=next_expected,
                duration_sec=None,
                outcome="missed",
            )
        )
        job.status = "missing"
        await db.flush()
        await fire_alert(
            db,
            type="cron_missing",
            severity="critical",
            message=f"Cron job '{job.name}' missed its scheduled run.",
            server_id=job.server_id,
            cron_job_id=job.id,
            commit=False,
        )
    else:
        job.status = new_status


def _backup_base(job: BackupJob) -> datetime:
    base = _aware(job.last_ping_at)
    if base is not None:
        return base
    created = _aware(getattr(job, "created_at", None))
    return created if created is not None else _now()


async def _evaluate_backup(db: AsyncSession, job: BackupJob, now: datetime) -> None:
    base = _backup_base(job)
    next_expected = base + timedelta(hours=job.expected_interval_hours)
    deadline = next_expected + _BACKUP_GRACE

    if now < next_expected:
        new_status = "healthy"
    elif now < deadline:
        new_status = "late"
    else:
        new_status = "missing"

    if new_status == "missing":
        db.add(
            BackupRun(
                backup_job_id=job.id,
                ran_at=next_expected,
                size_bytes=None,
                exit_code=None,
                outcome="missed",
            )
        )
        job.status = "missing"
        await db.flush()
        await fire_alert(
            db,
            type="backup_missing",
            severity="critical",
            message=f"Backup job '{job.name}' missed its expected run window.",
            server_id=job.server_id,
            backup_job_id=job.id,
            commit=False,
        )
    else:
        job.status = new_status


async def cron_backup_watchdog() -> None:
    """APScheduler entrypoint — owns its own DB session."""
    async with AsyncSessionLocal() as db:
        await run_watchdog(db)


async def run_watchdog(db: AsyncSession) -> None:
    """Core pass — separated so smoke tests can drive it with their own session."""
    now = _now()

    cron_jobs = (
        await db.execute(select(CronJob).where(CronJob.status != "missing"))
    ).scalars().all()
    for job in cron_jobs:
        try:
            await _evaluate_cron(db, job, now)
        except Exception:  # noqa: BLE001 — one bad job must not stall the tick
            logger.warning("cron watchdog failed for job %s", job.id, exc_info=True)

    backup_jobs = (
        await db.execute(select(BackupJob).where(BackupJob.status != "missing"))
    ).scalars().all()
    for job in backup_jobs:
        try:
            await _evaluate_backup(db, job, now)
        except Exception:  # noqa: BLE001
            logger.warning("backup watchdog failed for job %s", job.id, exc_info=True)

    await db.commit()
