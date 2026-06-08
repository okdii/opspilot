"""Job watchdog (unified monitoring — spec 2026-06-08 §5).

APScheduler tick (every 60s, job id ``cron_backup_watchdog``). For every
MonitoredJob not already in ``missing`` status it computes the next-expected
window using ``croniter`` on ``job.schedule`` and transitions:
  Healthy → Late → Missing.
On crossing into ``missing`` it writes a ``missed`` JobRun and fires a
``job_missing`` alert. Once ``missing`` it stops re-firing until a ping
resets the job to ``healthy``.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.other import JobRun, MonitoredJob
from app.services.alerting import fire_alert
from app.services.cron_schedule import next_fire_after

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _base(job: MonitoredJob) -> datetime:
    """Anchor for next-expected computation: last ping, else now().

    A job with no ping yet is healthy until its first scheduled window elapses."""
    return _aware(job.last_ping_at) or _now()


async def _evaluate_job(db: AsyncSession, job: MonitoredJob, now: datetime) -> None:
    next_expected = next_fire_after(job.schedule, _base(job))
    if next_expected is None:
        # Invalid schedule — monitoring paused. Do not fire.
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
            JobRun(
                job_id=job.id,
                ran_at=next_expected,
                outcome="missed",
            )
        )
        job.status = "missing"
        await db.flush()
        await fire_alert(
            db,
            type="job_missing",
            severity="critical",
            message=f"Job '{job.name}' missed its scheduled run.",
            server_id=job.server_id,
            job_id=job.id,
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

    jobs = (
        await db.execute(select(MonitoredJob).where(MonitoredJob.status != "missing"))
    ).scalars().all()

    for job in jobs:
        try:
            await _evaluate_job(db, job, now)
        except Exception:  # noqa: BLE001 — one bad job must not stall the tick
            logger.warning("watchdog failed for job %s", job.id, exc_info=True)

    await db.commit()
