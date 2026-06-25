"""Collects all data needed to generate a daily server report.

Queries server_metrics_hourly, alert, service, incident, monitored_job,
job_run, and server_logs for a given server + calendar date (UTC).
Returns a dict that is both stored in data_snapshot and sent to the AI.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def collect_for_date(
    db: AsyncSession, server_id: uuid.UUID, report_date: date
) -> dict:
    sid = str(server_id)
    day_start = datetime(report_date.year, report_date.month, report_date.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    return {
        "metrics": await _metrics(db, sid, day_start, day_end),
        "alerts": await _alerts(db, server_id, day_start, day_end),
        "services": await _services(db, server_id, day_start, day_end),
        "jobs": await _jobs(db, server_id, day_start, day_end),
        "logs": await _logs(db, sid, day_start, day_end),
    }


async def _metrics(db: AsyncSession, sid: str, day_start: datetime, day_end: datetime) -> dict:
    stmt = text("""
        SELECT
            metric_name,
            ROUND(AVG(avg_value)::numeric, 2) AS day_avg,
            ROUND(MAX(avg_value)::numeric, 2) AS day_max
        FROM server_metrics_hourly
        WHERE server_id = CAST(:sid AS uuid)
          AND bucket >= :day_start AND bucket < :day_end
          AND metric_name IN (
              'cpu.usage_idle', 'cpu.usage_iowait',
              'mem.used_percent', 'disk.used_percent'
          )
        GROUP BY metric_name
    """)
    rows = (await db.execute(stmt, {"sid": sid, "day_start": day_start, "day_end": day_end})).all()
    raw = {r[0]: {"avg": float(r[1] or 0), "max": float(r[2] or 0)} for r in rows}

    cpu_avg = round(100 - raw.get("cpu.usage_idle", {}).get("avg", 100), 2)
    peak_stmt = text("""
        SELECT bucket, ROUND((100 - avg_value)::numeric, 2) AS cpu_pct
        FROM server_metrics_hourly
        WHERE server_id = CAST(:sid AS uuid) AND bucket >= :day_start AND bucket < :day_end
          AND metric_name = 'cpu.usage_idle'
        ORDER BY avg_value ASC LIMIT 1
    """)
    peak_row = (await db.execute(peak_stmt, {"sid": sid, "day_start": day_start, "day_end": day_end})).one_or_none()
    cpu_peak = float(peak_row[1]) if peak_row else cpu_avg
    cpu_peak_at = peak_row[0].strftime("%H:%M") if peak_row else None

    disk_stmt = text("""
        SELECT ROUND(avg_value::numeric, 2)
        FROM server_metrics_hourly
        WHERE server_id = CAST(:sid AS uuid) AND bucket >= :day_start AND bucket < :day_end
          AND metric_name = 'disk.used_percent'
        ORDER BY bucket DESC LIMIT 1
    """)
    disk_row = (await db.execute(disk_stmt, {"sid": sid, "day_start": day_start, "day_end": day_end})).one_or_none()

    return {
        "cpu_avg_pct": cpu_avg,
        "cpu_peak_pct": cpu_peak,
        "cpu_peak_at": cpu_peak_at,
        "iowait_avg_pct": raw.get("cpu.usage_iowait", {}).get("avg", 0),
        "iowait_max_pct": raw.get("cpu.usage_iowait", {}).get("max", 0),
        "ram_avg_pct": raw.get("mem.used_percent", {}).get("avg", 0),
        "ram_max_pct": raw.get("mem.used_percent", {}).get("max", 0),
        "disk_eod_pct": float(disk_row[0]) if disk_row else None,
    }


async def _alerts(
    db: AsyncSession, server_id: uuid.UUID, day_start: datetime, day_end: datetime
) -> list[dict]:
    from sqlalchemy import select, and_
    from app.models.other import Alert

    rows = (
        await db.execute(
            select(Alert)
            .where(
                and_(
                    Alert.server_id == server_id,
                    Alert.sent_at >= day_start,
                    Alert.sent_at < day_end,
                )
            )
            .order_by(Alert.sent_at)
        )
    ).scalars().all()

    result = []
    for a in rows:
        dur = None
        if a.resolved_at and a.sent_at:
            dur = int((a.resolved_at - a.sent_at).total_seconds() // 60)
        result.append({
            "severity": a.severity,
            "message": a.message,
            "type": a.type,
            "state": a.state,
            "fired_at": a.sent_at.strftime("%H:%M") if a.sent_at else None,
            "resolved_at": a.resolved_at.strftime("%H:%M") if a.resolved_at else None,
            "duration_min": dur,
        })
    return result


async def _services(
    db: AsyncSession, server_id: uuid.UUID, day_start: datetime, day_end: datetime
) -> list[dict]:
    from sqlalchemy import select, and_
    from app.models.other import Service, Incident

    services = (
        await db.execute(
            select(Service).where(Service.server_id == server_id, Service.is_active == True)
        )
    ).scalars().all()

    result = []
    for svc in services:
        incidents = (
            await db.execute(
                select(Incident).where(
                    and_(
                        Incident.service_id == svc.id,
                        Incident.started_at < day_end,
                        (Incident.resolved_at.is_(None)) | (Incident.resolved_at >= day_start),
                    )
                )
            )
        ).scalars().all()

        total_down_sec = sum(
            (
                min(i.resolved_at or day_end, day_end) - max(i.started_at, day_start)
            ).total_seconds()
            for i in incidents
        )
        day_sec = 86400
        uptime_pct = round(max(0, (day_sec - total_down_sec) / day_sec * 100), 2)

        result.append({
            "name": svc.name,
            "type": svc.type,
            "url": svc.url,
            "uptime_pct": uptime_pct,
            "incident_count": len(incidents),
            "total_down_min": int(total_down_sec // 60),
        })
    return result


async def _jobs(
    db: AsyncSession, server_id: uuid.UUID, day_start: datetime, day_end: datetime
) -> list[dict]:
    from sqlalchemy import select, and_
    from app.models.other import MonitoredJob, JobRun

    jobs = (
        await db.execute(
            select(MonitoredJob).where(MonitoredJob.server_id == server_id)
        )
    ).scalars().all()

    result = []
    for job in jobs:
        runs = (
            await db.execute(
                select(JobRun).where(
                    and_(
                        JobRun.job_id == job.id,
                        JobRun.ran_at >= day_start,
                        JobRun.ran_at < day_end,
                    )
                ).order_by(JobRun.ran_at)
            )
        ).scalars().all()

        result.append({
            "name": job.name,
            "schedule": job.schedule,
            "status": job.status,
            "runs": [
                {
                    "outcome": r.outcome,
                    "ran_at": r.ran_at.strftime("%H:%M"),
                    "duration_sec": r.duration_sec,
                }
                for r in runs
            ],
        })
    return result


async def _logs(
    db: AsyncSession, sid: str, day_start: datetime, day_end: datetime
) -> dict:
    sev_stmt = text("""
        SELECT COALESCE(NULLIF(severity, ''), 'info') AS sev, COUNT(*) AS n
        FROM server_logs
        WHERE server_id = CAST(:sid AS uuid) AND time >= :day_start AND time < :day_end
        GROUP BY sev
    """)
    sev_rows = (await db.execute(sev_stmt, {"sid": sid, "day_start": day_start, "day_end": day_end})).all()
    severity_counts: dict = {"fatal": 0, "error": 0, "warn": 0, "info": 0}
    total = 0
    for sev, n in sev_rows:
        n = int(n)
        total += n
        if sev in severity_counts:
            severity_counts[sev] += n

    err_stmt = text("""
        SELECT LEFT(message, 120) AS msg, COUNT(*) AS n, source
        FROM server_logs
        WHERE server_id = CAST(:sid AS uuid) AND time >= :day_start AND time < :day_end
          AND severity IN ('error', 'fatal')
        GROUP BY LEFT(message, 120), source
        ORDER BY n DESC
        LIMIT 10
    """)
    err_rows = (await db.execute(err_stmt, {"sid": sid, "day_start": day_start, "day_end": day_end})).all()
    top_errors = [{"message": r[0], "count": int(r[1]), "source": r[2]} for r in err_rows]

    auth_stmt = text("""
        SELECT COUNT(*) AS n,
               raw->>'remote_host' AS remote_host
        FROM server_logs
        WHERE server_id = CAST(:sid AS uuid) AND time >= :day_start AND time < :day_end
          AND source IN ('auth', 'syslog')
          AND (message ILIKE '%failed password%' OR message ILIKE '%invalid user%'
               OR message ILIKE '%authentication failure%')
        GROUP BY raw->>'remote_host'
        ORDER BY n DESC
        LIMIT 5
    """)
    auth_rows = (await db.execute(auth_stmt, {"sid": sid, "day_start": day_start, "day_end": day_end})).all()
    failed_logins = [{"count": int(r[0]), "remote_host": r[1]} for r in auth_rows]

    slow_stmt = text("""
        SELECT COUNT(*) AS n,
               ROUND(AVG((raw->>'query_time')::float)::numeric, 2) AS avg_s,
               ROUND(MAX((raw->>'query_time')::float)::numeric, 2) AS max_s
        FROM server_logs
        WHERE server_id = CAST(:sid AS uuid) AND time >= :day_start AND time < :day_end
          AND source = 'mariadb_slow'
          AND raw->>'query_time' ~ '^[0-9.]+$'
    """)
    slow_row = (await db.execute(slow_stmt, {"sid": sid, "day_start": day_start, "day_end": day_end})).one_or_none()
    slow_queries = None
    if slow_row and slow_row[0]:
        slow_queries = {"count": int(slow_row[0]), "avg_sec": float(slow_row[1] or 0), "max_sec": float(slow_row[2] or 0)}

    src_stmt = text("""
        SELECT source, COUNT(*) AS n
        FROM server_logs
        WHERE server_id = CAST(:sid AS uuid) AND time >= :day_start AND time < :day_end
        GROUP BY source
        ORDER BY n DESC
    """)
    src_rows = (await db.execute(src_stmt, {"sid": sid, "day_start": day_start, "day_end": day_end})).all()
    sources = [{"source": r[0], "count": int(r[1])} for r in src_rows]

    return {
        "total_lines": total,
        "severity_counts": severity_counts,
        "top_errors": top_errors,
        "failed_logins": failed_logins,
        "slow_queries": slow_queries,
        "sources": sources,
    }
