"""fail2ban monitoring API.

GET /api/servers/{server_id}/fail2ban/status
GET /api/servers/{server_id}/fail2ban/jails
GET /api/servers/{server_id}/fail2ban/banned-ips
GET /api/servers/{server_id}/fail2ban/events
GET /api/servers/{server_id}/fail2ban/top-countries
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import CurrentUser
from app.models.other import Settings
from app.services.cron_schedule import _resolve_tz

router = APIRouter(prefix="/api/servers", tags=["fail2ban"])


async def _check_access(server_id: str, user: CurrentUser, db: AsyncSession) -> None:
    from app.routers.servers import _assert_server_access
    await _assert_server_access(server_id, user, db)


@router.get("/{server_id}/fail2ban/status")
async def get_fail2ban_status(
    server_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _check_access(server_id, user, db)

    last_checked = await db.scalar(
        text("SELECT MAX(checked_at) FROM fail2ban_jails WHERE server_id = :sid"),
        {"sid": server_id},
    )
    currently_banned = await db.scalar(
        text("SELECT COALESCE(SUM(currently_banned), 0) FROM fail2ban_jails WHERE server_id = :sid"),
        {"sid": server_id},
    ) or 0
    jail_count = await db.scalar(
        text("SELECT COUNT(*) FROM fail2ban_jails WHERE server_id = :sid"),
        {"sid": server_id},
    ) or 0
    settings_row = await db.scalar(select(Settings).where(Settings.id == 1))
    tz = _resolve_tz(settings_row.timezone if settings_row else None)
    now_local = datetime.now(tz)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    bans_today = await db.scalar(
        text("""
            SELECT COUNT(*) FROM fail2ban_ban_events
            WHERE server_id = :sid AND action = 'ban' AND event_at >= :today
        """),
        {"sid": server_id, "today": today_start},
    ) or 0

    return {
        "running": last_checked is not None,
        "jail_count": int(jail_count),
        "currently_banned": int(currently_banned),
        "bans_today": int(bans_today),
        "last_checked": last_checked,
    }


@router.get("/{server_id}/fail2ban/jails")
async def get_fail2ban_jails(
    server_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _check_access(server_id, user, db)

    rows = await db.execute(
        text("""
            SELECT jail_name, currently_banned, total_banned, currently_failed,
                   bantime_seconds, findtime_seconds, maxretry, checked_at
            FROM fail2ban_jails WHERE server_id = :sid
            ORDER BY currently_banned DESC
        """),
        {"sid": server_id},
    )
    return [
        {
            "jail_name": r.jail_name,
            "currently_banned": r.currently_banned,
            "total_banned": r.total_banned,
            "currently_failed": r.currently_failed,
            "bantime_seconds": r.bantime_seconds,
            "findtime_seconds": r.findtime_seconds,
            "maxretry": r.maxretry,
            "checked_at": r.checked_at,
        }
        for r in rows.fetchall()
    ]


@router.get("/{server_id}/fail2ban/banned-ips")
async def get_fail2ban_banned_ips(
    server_id: str,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    await _check_access(server_id, user, db)

    offset = (page - 1) * per_page
    rows = await db.execute(
        text("""
            SELECT b.ip, b.jail, b.banned_since, b.checked_at,
                   g.country_code, g.country_name, g.isp
            FROM fail2ban_banned_ips b
            LEFT JOIN ip_geodata g ON g.ip = b.ip
            WHERE b.server_id = :sid
            ORDER BY b.checked_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"sid": server_id, "limit": per_page, "offset": offset},
    )
    total = await db.scalar(
        text("SELECT COUNT(*) FROM fail2ban_banned_ips WHERE server_id = :sid"),
        {"sid": server_id},
    ) or 0

    return {
        "total": int(total),
        "page": page,
        "per_page": per_page,
        "items": [
            {
                "ip": r.ip,
                "jail": r.jail,
                "banned_since": r.banned_since,
                "checked_at": r.checked_at,
                "country_code": r.country_code,
                "country_name": r.country_name,
                "isp": r.isp,
            }
            for r in rows.fetchall()
        ],
    }


@router.get("/{server_id}/fail2ban/events")
async def get_fail2ban_events(
    server_id: str,
    user: CurrentUser,
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
):
    await _check_access(server_id, user, db)

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = await db.execute(
        text("""
            SELECT date_trunc('hour', event_at) AS hour, COUNT(*) AS ban_count
            FROM fail2ban_ban_events
            WHERE server_id = :sid AND action = 'ban' AND event_at >= :since
            GROUP BY 1 ORDER BY 1
        """),
        {"sid": server_id, "since": since},
    )
    return [{"hour": r.hour, "ban_count": int(r.ban_count)} for r in rows.fetchall()]


@router.get("/{server_id}/fail2ban/top-countries")
async def get_fail2ban_top_countries(
    server_id: str,
    user: CurrentUser,
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
):
    await _check_access(server_id, user, db)

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = await db.execute(
        text("""
            SELECT g.country_code, g.country_name, COUNT(*) AS count
            FROM fail2ban_ban_events e
            LEFT JOIN ip_geodata g ON g.ip = e.ip
            WHERE e.server_id = :sid AND e.action = 'ban' AND e.event_at >= :since
            GROUP BY g.country_code, g.country_name
            ORDER BY count DESC
            LIMIT 15
        """),
        {"sid": server_id, "since": since},
    )
    return [
        {
            "country_code": r.country_code or "XX",
            "country_name": r.country_name or "Unknown",
            "count": int(r.count),
        }
        for r in rows.fetchall()
    ]
