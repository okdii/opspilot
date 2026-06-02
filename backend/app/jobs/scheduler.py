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
