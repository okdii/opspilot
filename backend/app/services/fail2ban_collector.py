"""fail2ban SSH poll — collect jail status and ban events every 5 min per active server.

Permission requirement: the SSH user must be in the fail2ban group on the target server:
    sudo usermod -aG fail2ban opspilot
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, text

from app.database import AsyncSessionLocal
from app.models.server import Server
from app.services.ssh import SSHSession

log = logging.getLogger(__name__)

# fail2ban-client status <jail> parsing
_CURRENTLY_BANNED_RE = re.compile(r"Currently banned:\s+(\d+)")
_TOTAL_BANNED_RE = re.compile(r"Total banned:\s+(\d+)")
_CURRENTLY_FAILED_RE = re.compile(r"Currently failed:\s+(\d+)")
_BANNED_IP_LIST_RE = re.compile(r"Banned IP list:\s*([^\n]*)")

# /var/log/fail2ban.log line format:
# 2026-06-12 07:23:45,678 fail2ban.actions [1234]: NOTICE  [sshd] Ban 103.107.60.45
_LOG_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ fail2ban\.actions.*?NOTICE\s+\[(.+?)\] (Ban|Unban) (\S+)$"
)


def _parse_jail_status(output: str) -> dict:
    currently_banned = int(m.group(1)) if (m := _CURRENTLY_BANNED_RE.search(output)) else 0
    total_banned = int(m.group(1)) if (m := _TOTAL_BANNED_RE.search(output)) else 0
    currently_failed = int(m.group(1)) if (m := _CURRENTLY_FAILED_RE.search(output)) else 0
    banned_ips: list[str] = []
    if m := _BANNED_IP_LIST_RE.search(output):
        raw = m.group(1).strip()
        banned_ips = [ip.strip() for ip in raw.split() if ip.strip()]
    return {
        "currently_banned": currently_banned,
        "total_banned": total_banned,
        "currently_failed": currently_failed,
        "banned_ips": banned_ips,
    }


def _parse_tz_offset(offset_str: str) -> timezone:
    """Parse `date +%z` output (e.g. '+0800', '-0530') into a timezone object."""
    try:
        s = offset_str.strip()
        sign = 1 if s[0] == "+" else -1
        hours, minutes = int(s[1:3]), int(s[3:5])
        return timezone(timedelta(hours=sign * hours, minutes=sign * minutes))
    except Exception:
        return timezone.utc


def _parse_fail2ban_log(output: str, server_tz: timezone = timezone.utc) -> list[dict]:
    events = []
    for line in output.splitlines():
        m = _LOG_LINE_RE.match(line.strip())
        if not m:
            continue
        try:
            ts = (
                datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                .replace(tzinfo=server_tz)
                .astimezone(timezone.utc)
            )
        except ValueError:
            continue
        events.append({
            "event_at": ts,
            "jail": m.group(2),
            "action": m.group(3).lower(),
            "ip": m.group(4),
        })
    return events


async def _geo_lookup_batch(ips: list[str]) -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        for ip in ips:
            try:
                r = await client.get(
                    f"http://ip-api.com/json/{ip}",
                    params={"fields": "status,country,countryCode,city,isp"},
                )
                if r.status_code == 200:
                    data = r.json()
                    if data.get("status") == "success":
                        async with AsyncSessionLocal() as db:
                            await db.execute(
                                text("""
                                    INSERT INTO ip_geodata (ip, country_code, country_name, city, isp, cached_at)
                                    VALUES (:ip, :cc, :cn, :city, :isp, NOW())
                                    ON CONFLICT (ip) DO NOTHING
                                """),
                                {
                                    "ip": ip,
                                    "cc": data.get("countryCode"),
                                    "cn": data.get("country"),
                                    "city": data.get("city"),
                                    "isp": data.get("isp"),
                                },
                            )
                            await db.commit()
            except Exception:
                log.warning("geo lookup failed for %s", ip)
            await asyncio.sleep(1.5)  # respect 45 req/min free tier


async def _collect_one(server: Server) -> None:
    try:
        async with SSHSession(server) as ssh:
            # Get jail list
            status_result = await ssh.run("fail2ban-client status 2>&1", timeout=10)
            if not status_result.ok:
                log.warning("fail2ban: status check failed on %s: %s", server.id, status_result.stderr)
                return
            jail_match = re.search(r"Jail list:\s*(.+)", status_result.stdout)
            if not jail_match:
                log.info("fail2ban: no jails on server %s", server.id)
                return
            jail_names = [j.strip() for j in jail_match.group(1).split(",") if j.strip()]
            # Fix 1 — reject any jail name with unsafe characters to prevent shell injection
            jail_names = [
                j for j in jail_names
                if re.fullmatch(r'[a-zA-Z0-9_-]+', j)
            ]

            # Per-jail status + config
            jail_data: dict[str, dict] = {}
            for jail in jail_names:
                r = await ssh.run(f"fail2ban-client status {jail} 2>&1", timeout=10)
                if not r.ok:
                    continue
                data = _parse_jail_status(r.stdout)
                # Fetch config values in one compound command
                cfg = await ssh.run(
                    f"fail2ban-client get {jail} bantime 2>/dev/null; "
                    f"fail2ban-client get {jail} findtime 2>/dev/null; "
                    f"fail2ban-client get {jail} maxretry 2>/dev/null",
                    timeout=10,
                )
                if cfg.ok:
                    lines = [ln.strip() for ln in cfg.stdout.splitlines() if ln.strip()]
                    def _int(s: str) -> int | None:
                        try:
                            return int(s)
                        except ValueError:
                            return None
                    data["bantime_seconds"] = _int(lines[0]) if len(lines) > 0 else None
                    data["findtime_seconds"] = _int(lines[1]) if len(lines) > 1 else None
                    data["maxretry"] = _int(lines[2]) if len(lines) > 2 else None
                else:
                    data["bantime_seconds"] = data["findtime_seconds"] = data["maxretry"] = None
                jail_data[jail] = data

            # Server local timezone (for correct log timestamp parsing)
            tz_result = await ssh.run("date +%z", timeout=5)
            server_tz = _parse_tz_offset(tz_result.stdout) if tz_result.ok else timezone.utc

            # Ban event log
            log_result = await ssh.run(
                "tail -n 5000 /var/log/fail2ban.log 2>/dev/null || true", timeout=15
            )
            log_events = _parse_fail2ban_log(log_result.stdout, server_tz) if log_result.ok else []
    except Exception as e:
        msg = str(e).lower()
        if "permission denied" in msg or "permission" in msg:
            log.warning(
                "fail2ban: permission denied on %s — run: sudo usermod -aG fail2ban opspilot",
                server.id,
            )
        else:
            log.exception("fail2ban: SSH failed for server %s", server.id)
        return

    now = datetime.now(timezone.utc)
    all_new_ips: set[str] = set()

    async with AsyncSessionLocal() as db:
        for jail, data in jail_data.items():
            # Upsert jail snapshot
            await db.execute(
                text("""
                    INSERT INTO fail2ban_jails
                        (server_id, jail_name, currently_banned, total_banned, currently_failed,
                         bantime_seconds, findtime_seconds, maxretry, checked_at)
                    VALUES (:sid, :jail, :cb, :tb, :cf, :bt, :ft, :mr, :now)
                    ON CONFLICT (server_id, jail_name) DO UPDATE SET
                        currently_banned = EXCLUDED.currently_banned,
                        total_banned     = EXCLUDED.total_banned,
                        currently_failed = EXCLUDED.currently_failed,
                        bantime_seconds  = EXCLUDED.bantime_seconds,
                        findtime_seconds = EXCLUDED.findtime_seconds,
                        maxretry         = EXCLUDED.maxretry,
                        checked_at       = EXCLUDED.checked_at
                """),
                {
                    "sid": str(server.id), "jail": jail,
                    "cb": data["currently_banned"], "tb": data["total_banned"],
                    "cf": data["currently_failed"],
                    "bt": data["bantime_seconds"], "ft": data["findtime_seconds"],
                    "mr": data["maxretry"], "now": now,
                },
            )
            await db.commit()

            # Replace banned IPs for this jail with live list — single transaction
            await db.execute(
                text("DELETE FROM fail2ban_banned_ips WHERE server_id = :sid AND jail = :jail"),
                {"sid": str(server.id), "jail": jail},
            )
            for ip in data["banned_ips"]:
                await db.execute(
                    text("""
                        INSERT INTO fail2ban_banned_ips (server_id, jail, ip, checked_at)
                        VALUES (:sid, :jail, :ip, :now)
                        ON CONFLICT (server_id, jail, ip) DO UPDATE SET checked_at = EXCLUDED.checked_at
                    """),
                    {"sid": str(server.id), "jail": jail, "ip": ip, "now": now},
                )
                all_new_ips.add(ip)
            await db.commit()  # single commit for the entire jail's banned IP set

        # Insert ban events (UNIQUE constraint silently skips duplicates)
        inserted = 0
        for event in log_events:
            try:
                await db.execute(
                    text("""
                        INSERT INTO fail2ban_ban_events (server_id, ip, jail, action, event_at)
                        VALUES (:sid, :ip, :jail, :action, :event_at)
                        ON CONFLICT (server_id, ip, jail, event_at, action) DO NOTHING
                    """),
                    {
                        "sid": str(server.id), "ip": event["ip"], "jail": event["jail"],
                        "action": event["action"], "event_at": event["event_at"],
                    },
                )
                inserted += 1
            except Exception as insert_err:
                log.warning("fail2ban: ban event insert failed: %s", insert_err)
        await db.commit()

    # Geo-lookup IPs not yet cached — done outside the main DB session
    if all_new_ips:
        async with AsyncSessionLocal() as db:
            rows = await db.execute(
                text("SELECT ip FROM ip_geodata WHERE ip = ANY(:ips)"),
                {"ips": list(all_new_ips)},
            )
            existing = {r[0] for r in rows.fetchall()}
        ips_to_lookup = list(all_new_ips - existing)
    else:
        ips_to_lookup = []

    if ips_to_lookup:
        await _geo_lookup_batch(ips_to_lookup)

    log.info(
        "fail2ban: server %s — %d jails, %d/%d events inserted",
        server.id, len(jail_data), inserted, len(log_events),
    )


async def collect_fail2ban() -> None:
    """Entry point called by APScheduler every 5 minutes."""
    async with AsyncSessionLocal() as db:
        servers = (
            await db.execute(select(Server).where(Server.is_active == True))
        ).scalars().all()

    for server in servers:
        try:
            await _collect_one(server)
        except Exception:
            log.exception("fail2ban: collection failed for server %s", server.id)
