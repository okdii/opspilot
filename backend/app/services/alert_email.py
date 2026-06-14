"""Plain-text alert email formatting (spec 10 §12).

This module only *formats* fire/resolve subjects and bodies and delegates the
actual SMTP transport to ``app.services.email`` (reused, not reimplemented).
Bodies are text/plain — no HTML. Sends are best-effort: a missing or broken
SMTP config never stops an alert from being recorded or pushed.
"""
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.other import Alert, Settings
from app.services.email import parse_recipients, send_email_safe

logger = logging.getLogger(__name__)

# spec 10 §15
TYPE_DISPLAY: dict[str, str] = {
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
    "maintenance": "Maintenance Mode",
    "content_mismatch": "Content Check Failed",
    "malicious_content": "Malicious Content Detected",
}

_DIVIDER = "-" * 53


def display_name(alert_type: str) -> str:
    return TYPE_DISPLAY.get(alert_type, alert_type)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _fmt_ts(dt: datetime | None, tz: str = "UTC") -> str:
    dt = _aware(dt)
    if dt is None:
        return "—"
    try:
        zone = ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        zone = timezone.utc
        tz = "UTC"
    return dt.astimezone(zone).strftime(f"%Y-%m-%d %H:%M:%S {tz}")


def _fmt_duration(start: datetime | None, end: datetime | None) -> str:
    start, end = _aware(start), _aware(end)
    if start is None or end is None:
        return "—"
    total = int((end - start).total_seconds())
    if total < 0:
        total = 0
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
    return " ".join(parts)


def fire_subject(alert: Alert, server_name: str | None) -> str:
    subject_target = server_name or "OpsPilot"
    return f"[OpsPilot] {alert.severity.upper()}: {subject_target} — {display_name(alert.type)}"


def resolve_subject(alert: Alert, server_name: str | None) -> str:
    subject_target = server_name or "OpsPilot"
    return f"[OpsPilot] RESOLVED: {subject_target} — {display_name(alert.type)} returned to normal"


def format_fire_body(
    alert: Alert,
    *,
    server_name: str | None,
    base_url: str,
    email_meta: dict | None = None,
    tz: str = "UTC",
) -> str:
    base = base_url.rstrip("/")
    meta = email_meta or {}
    lines = [
        _DIVIDER,
        "OpsPilot Alert",
        _DIVIDER,
        "",
        f"Severity:   {alert.severity.upper()}",
        f"Server:     {server_name or '—'}",
    ]
    if meta.get("condition"):
        lines.append(f"Condition:  {meta['condition']}")
    if meta.get("value") is not None:
        lines.append(f"Value:      {meta['value']}")
    if meta.get("threshold") is not None:
        lines.append(f"Threshold:  {meta['threshold']}")
    lines.append(f"Fired at:   {_fmt_ts(alert.sent_at, tz)}")
    lines += [
        "",
        "Message:",
        alert.message,
        "",
    ]
    if alert.server_id:
        lines.append(f"View dashboard: {base}/servers/{alert.server_id}")
        lines.append("")
    lines += [
        _DIVIDER,
        "To manage this alert:",
        f"{base}/alerts",
        "",
        "To edit alert rules:",
        f"{base}/alerts/rules",
        "",
        "This email was sent by OpsPilot.",
        _DIVIDER,
    ]
    return "\n".join(lines) + "\n"


_RESOLVE_SUMMARY: dict[str, str] = {
    "service_down": "Good news — the service is back up and running normally.",
    "cpu": "CPU usage has returned to normal levels.",
    "ram": "RAM usage has returned to normal levels.",
    "disk": "Disk usage has returned to normal levels.",
    "disk_inode": "Disk inode usage has returned to normal levels.",
    "agent_offline": "The agent is back online and reporting normally.",
    "ssl_expiry": "The SSL certificate issue has been resolved.",
    "domain_expiry": "The domain registration issue has been resolved.",
    "cron_missing": "The cron job has been detected and is running normally.",
    "backup_missing": "The backup job has resumed running normally.",
    "backup_failure": "The backup job completed successfully.",
    "backup_size_drop": "Backup size has returned to expected levels.",
    "db_connections": "Database connection count has returned to normal.",
    "db_replication_lag": "Database replication lag has cleared.",
    "db_replication_stopped": "Database replication has resumed.",
    "db_deadlock": "No further deadlocks have been detected.",
    "php_fatal": "No further PHP fatal errors have been detected.",
    "nginx_5xx": "Nginx error rate has returned to normal.",
    "ssh_brute_force": "SSH brute force activity has subsided.",
    "mariadb_error": "No further MariaDB errors have been detected.",
    "slow_query_spike": "Slow query rate has returned to normal.",
    "content_mismatch": "Content check passed — expected keywords are present on the page again.",
    "malicious_content": "Page content is clean — no malicious keywords detected.",
}


def format_resolve_body(alert: Alert, *, server_name: str | None, tz: str = "UTC") -> str:
    summary = _RESOLVE_SUMMARY.get(alert.type, "The issue has been resolved and everything is back to normal.")
    lines = [
        _DIVIDER,
        "OpsPilot Alert — Resolved",
        _DIVIDER,
        "",
        summary,
        "",
        f"Severity:   {alert.severity.upper()} (resolved)",
        f"Server:     {server_name or '—'}",
        f"Resolved:   {_fmt_ts(alert.resolved_at, tz)}",
        f"Duration:   {_fmt_duration(alert.sent_at, alert.resolved_at)}",
        "",
        "Message:",
        alert.message,
        "",
        _DIVIDER,
        "This email was sent by OpsPilot.",
        _DIVIDER,
    ]
    return "\n".join(lines) + "\n"


async def send_alert_email(
    db: AsyncSession,
    alert: Alert,
    *,
    kind: str,
    server_name: str | None = None,
    email_meta: dict | None = None,
) -> bool:
    """Load Settings, build subject/body for ``kind`` ('fire'|'resolve') and send
    best-effort. Never raises into the caller."""
    try:
        s = await db.scalar(select(Settings).where(Settings.id == 1))
    except Exception:  # noqa: BLE001
        logger.warning("alert email skipped: could not load settings", exc_info=True)
        return False
    if s is None:
        logger.warning("alert email skipped: no settings row")
        return False

    if not s.smtp_enabled:
        return False

    recipients = parse_recipients(s.smtp_recipients)
    base_url = s.base_url or "http://localhost"

    tz = s.timezone or "UTC"
    if kind == "fire":
        subject = fire_subject(alert, server_name)
        body = format_fire_body(
            alert, server_name=server_name, base_url=base_url, email_meta=email_meta, tz=tz
        )
    else:
        subject = resolve_subject(alert, server_name)
        body = format_resolve_body(alert, server_name=server_name, tz=tz)

    return send_email_safe(s, subject, body, recipients)
