"""SSH dmesg poll — collect kernel messages every 15 min per active server.

Runs dmesg -T -l warn,err,crit,alert,emerg on each server via SSH,
parses output, deduplicates against server_logs, and inserts new rows.
"""
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.database import AsyncSessionLocal
from app.models.server import Server
from app.services.ssh import SSHSession

log = logging.getLogger(__name__)

_DMESG_CMD = "dmesg -T -l warn,err,crit,alert,emerg 2>/dev/null || true"
# Matches: [Wed Jun 11 03:14:22 2026] message text
_LINE_RE = re.compile(r"^\[(\w{3} \w{3}\s+\d+ \d{2}:\d{2}:\d{2} \d{4})\]\s+(.+)$")

_SEVERITY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"Out of memory|oom_kill|Killed process", re.I), "crit"),
    (re.compile(r"I/O error|EXT4-fs error|EDAC|Machine check|Kernel panic|BUG:|Oops:", re.I), "err"),
    (re.compile(r"Link is Down|remount-ro|Critical temperature|thermal.*warning", re.I), "warn"),
]


def _classify_severity(message: str) -> str:
    for pattern, sev in _SEVERITY_PATTERNS:
        if pattern.search(message):
            return sev
    return "warn"


def _parse_dmesg(output: str) -> list[dict]:
    rows = []
    for line in output.splitlines():
        m = _LINE_RE.match(line.strip())
        if not m:
            continue
        try:
            # dmesg -T uses local time; assume UTC (most servers run UTC)
            ts = datetime.strptime(m.group(1).strip(), "%a %b %d %H:%M:%S %Y").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
        message = m.group(2).strip()
        rows.append(
            {"logged_at": ts, "severity": _classify_severity(message), "message": message}
        )
    return rows


async def _already_exists(db, server_id: str, logged_at: datetime, message: str) -> bool:
    result = await db.execute(
        text("""
            SELECT 1 FROM server_logs
            WHERE server_id = :sid
              AND source = 'kernel'
              AND time BETWEEN :lo AND :hi
              AND message = :msg
            LIMIT 1
        """),
        {
            "sid": server_id,
            "lo": logged_at - timedelta(seconds=2),
            "hi": logged_at + timedelta(seconds=2),
            "msg": message,
        },
    )
    return result.fetchone() is not None


async def _collect_one(server: Server) -> None:
    async with SSHSession(server) as ssh:
        result = await ssh.run(_DMESG_CMD, timeout=15)
    if not result.ok or not result.stdout.strip():
        return

    rows = _parse_dmesg(result.stdout)
    if not rows:
        return

    async with AsyncSessionLocal() as db:
        inserted = 0
        for row in rows:
            if await _already_exists(db, str(server.id), row["logged_at"], row["message"]):
                continue
            await db.execute(
                text("""
                    INSERT INTO server_logs (time, server_id, source, severity, message, raw)
                    VALUES (:time, :server_id, 'kernel', :severity, :message, 'null'::jsonb)
                """),
                {
                    "time": row["logged_at"],
                    "server_id": str(server.id),
                    "severity": row["severity"],
                    "message": row["message"],
                },
            )
            inserted += 1
        if inserted:
            await db.commit()
            log.info("dmesg: inserted %d kernel events for server %s", inserted, server.id)


async def collect_dmesg() -> None:
    """Entry point called by APScheduler every 15 minutes."""
    async with AsyncSessionLocal() as db:
        servers = (
            await db.execute(select(Server).where(Server.is_active == True))
        ).scalars().all()

    for server in servers:
        try:
            await _collect_one(server)
        except Exception:
            log.exception("dmesg collection failed for server %s", server.id)
