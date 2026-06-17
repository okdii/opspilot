"""APScheduler setup with SQLAlchemy job store."""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from app.config import settings

jobstores = {
    "default": SQLAlchemyJobStore(url=settings.database_url_sync),
}

scheduler = AsyncIOScheduler(jobstores=jobstores)


async def session_cleanup() -> None:
    """Nightly: delete expired sessions."""
    from datetime import datetime, timezone
    from sqlalchemy import delete
    from app.database import AsyncSessionLocal
    from app.models.session import Session

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(Session).where(Session.expires_at < datetime.now(timezone.utc))
        )
        await db.commit()


async def ticket_sweep() -> None:
    """Every 60s: remove expired WS tickets from memory."""
    from app.ws.tickets import ticket_store
    ticket_store.sweep_expired()


async def maintenance_expiry() -> None:
    """Every 60s: lapse expired maintenance windows.

    Windows already read as inactive once ends_at passes (the maintenance
    router's _active_window check), so no state mutation is required here.
    This tick exists per spec for future alert re-evaluation / un-suppression
    (Phase 8 owns alert re-fire)."""
    return None


async def daily_report_nightly() -> None:
    """00:05 daily: generate AI daily reports for all active servers."""
    import logging
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.server import Server
    from app.models.other import Settings
    from app.services.ai.provider import get_provider
    from app.services.daily_report_generator import generate_and_store

    log = logging.getLogger(__name__)
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    async with AsyncSessionLocal() as db:
        provider = await get_provider(db)
        if provider is None:
            return
        s = await db.scalar(select(Settings).where(Settings.id == 1))
        servers = (await db.execute(select(Server).where(Server.is_active == True))).scalars().all()

    for server in servers:
        async with AsyncSessionLocal() as db:
            try:
                await generate_and_store(
                    db=db,
                    server_id=server.id,
                    report_date=yesterday,
                    provider=provider,
                    provider_name=s.ai_provider,
                    model_name=s.ai_model,
                )
                log.info("Daily report generated for server %s (%s)", server.name, yesterday)
            except Exception:
                log.exception("Failed to generate daily report for server %s", server.name)


async def dmesg_collector() -> None:
    """Every 15 min: poll dmesg on each active server for kernel events."""
    from app.services.dmesg_collector import collect_dmesg
    await collect_dmesg()


async def fail2ban_retention() -> None:
    """Daily 04:30: delete fail2ban ban events older than 30 days."""
    import logging
    from app.database import AsyncSessionLocal
    from sqlalchemy import text
    log = logging.getLogger(__name__)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("DELETE FROM fail2ban_ban_events WHERE event_at < NOW() - INTERVAL '30 days'")
        )
        await db.commit()
        log.info("fail2ban retention: deleted %d old ban events", result.rowcount)


async def fail2ban_collector() -> None:
    """Every 5 min: poll fail2ban status on each active server."""
    from app.services.fail2ban_collector import collect_fail2ban
    await collect_fail2ban()


async def db_disk_monitor() -> None:
    """Every 6h: fire a db_disk_high alert when host disk exceeds 70%."""
    import logging
    import shutil
    from app.database import AsyncSessionLocal
    from app.services.alerting import fire_alert

    log = logging.getLogger(__name__)
    try:
        usage = shutil.disk_usage("/")
    except OSError:
        log.exception("db_disk_monitor: could not read disk usage, skipping")
        return
    pct = usage.used / usage.total * 100

    async with AsyncSessionLocal() as db:
        if pct >= 70.0:
            used_gb = usage.used / 1_073_741_824
            total_gb = usage.total / 1_073_741_824
            await fire_alert(
                db,
                type="db_disk_high",
                severity="warning",
                message=(
                    f"OpsPilot host disk at {pct:.1f}% "
                    f"({used_gb:.1f} GB used of {total_gb:.1f} GB). "
                    "Expand disk or apply log retention policy."
                ),
                server_id=None,
                cooldown_min=360,
            )
            log.warning("db_disk_monitor: disk at %.1f%% — alert fired", pct)
        else:
            log.debug("db_disk_monitor: disk at %.1f%% — OK", pct)
