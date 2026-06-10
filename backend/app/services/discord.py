"""Best-effort Discord webhook notification for alert fire/resolve events."""
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.other import Alert, Settings

logger = logging.getLogger(__name__)

_TYPE_DISPLAY: dict[str, str] = {
    "cpu": "CPU Usage High",
    "ram": "RAM Usage High",
    "disk": "Disk Usage High",
    "disk_inode": "Disk Inode Usage High",
    "agent_offline": "Agent Offline",
    "service_down": "Service Down",
    "ssl_expiry": "SSL Certificate Expiring",
    "domain_expiry": "Domain Registration Expiring",
    "job_missing": "Job Missing",
    "job_failure": "Job Failed",
    "job_size_drop": "Backup Size Anomaly",
    "db_connections": "MariaDB Connections High",
    "db_replication_lag": "MariaDB Replication Lag",
    "db_replication_stopped": "MariaDB Replication Stopped",
    "db_deadlock": "MariaDB Deadlock Detected",
    "php_fatal": "PHP Fatal Error",
    "nginx_5xx": "Nginx 5xx Spike",
    "ssh_brute_force": "SSH Brute Force Attempt",
    "mariadb_error": "MariaDB Error",
    "slow_query_spike": "Slow Query Spike",
}

_COLOR_FIRE = 0xE74C3C
_COLOR_RESOLVE = 0x2ECC71


def _display_name(alert_type: str) -> str:
    return _TYPE_DISPLAY.get(alert_type, alert_type.replace("_", " ").title())


def _fmt_ts(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    aware = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    return aware.strftime("%Y-%m-%d %H:%M UTC")


def _build_payload(alert: Alert, *, kind: str, server_name: str | None) -> dict:
    type_label = _display_name(alert.type)
    footer_text = f"{server_name} · " if server_name else ""
    ts = alert.sent_at if kind == "fire" else alert.resolved_at

    if kind == "fire":
        title = f"🔴 {type_label}"
        color = _COLOR_FIRE
    else:
        title = f"✅ {type_label} — Resolved"
        color = _COLOR_RESOLVE

    return {
        "embeds": [
            {
                "title": title,
                "description": alert.message,
                "color": color,
                "footer": {"text": f"{footer_text}{_fmt_ts(ts)}"},
            }
        ]
    }


async def send_discord_alert(
    db: AsyncSession,
    alert: Alert,
    *,
    kind: str,
    server_name: str | None = None,
) -> None:
    """Post a Discord embed for a fire or resolve event. Never raises."""
    try:
        s = await db.scalar(select(Settings).where(Settings.id == 1))
    except Exception:  # noqa: BLE001
        logger.warning("discord alert skipped: could not load settings", exc_info=True)
        return

    if s is None or not s.discord_enabled or not s.discord_webhook_url:
        return

    payload = _build_payload(alert, kind=kind, server_name=server_name)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(s.discord_webhook_url, json=payload)
            if resp.status_code not in (200, 204):
                logger.warning(
                    "discord webhook returned %s: %s",
                    resp.status_code,
                    resp.text[:200],
                )
    except Exception:  # noqa: BLE001
        logger.warning("discord alert send failed", exc_info=True)
