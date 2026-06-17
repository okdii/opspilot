"""IP reputation enrichment (AbuseIPDB) + shared attacker-IP helpers.

Single source of truth for: (1) pulling the inline IPv4 out of an alert message
(shared with security_responder), (2) deciding whether an IP is publicly routable
(so we never ship private IPs to a third party), and (3) cache-first AbuseIPDB
enrichment backed by the ip_intel table.
"""
import ipaddress
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.models.other import IpIntel, Settings

logger = logging.getLogger(__name__)

_IPV4 = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")
_TTL = timedelta(days=7)
_ABUSEIPDB_URL = "https://api.abuseipdb.com/api/v2/check"


def extract_inline_ip(message: str | None) -> str | None:
    """First IPv4 literal in a message, or None. Shared by the responder and the
    attacker grouping so 'the IP in this alert' is defined in exactly one place."""
    if not message:
        return None
    m = _IPV4.search(message)
    return m.group(1) if m else None


def is_public_ip(ip: str) -> bool:
    """True only for globally-routable IPv4. Private/loopback/reserved are never
    sent to AbuseIPDB."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_reserved
                or addr.is_link_local or addr.is_multicast or addr.is_unspecified)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _settings(db: AsyncSession) -> Settings | None:
    return await db.scalar(select(Settings).where(Settings.id == 1))


async def enrich(db: AsyncSession, ip: str) -> IpIntel | None:
    """Cache-first AbuseIPDB lookup. Returns a fresh or cached IpIntel row, or None.
    Never raises into the request path; on any API error returns the stale row if any.
    Commits the session on a successful upsert (callers are read-only handlers that
    don't otherwise commit, so this is how the cache write is persisted)."""
    row = await db.get(IpIntel, ip)
    if row is not None:
        fetched = _aware(row.fetched_at)
        if fetched is not None and _now() - fetched < _TTL:
            return row

    s = await _settings(db)
    if (s is None or not s.abuseipdb_enabled
            or not s.abuseipdb_api_key_encrypted or not is_public_ip(ip)):
        return row  # serve stale cache if present, else None — no API call

    try:
        key = crypto.decrypt(s.abuseipdb_api_key_encrypted)
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                _ABUSEIPDB_URL,
                params={"ipAddress": ip, "maxAgeInDays": 90},
                headers={"Key": key, "Accept": "application/json"},
            )
        if resp.status_code != 200:
            logger.warning("AbuseIPDB %s for %s: %s", resp.status_code, ip, resp.text[:200])
            return row
        data = resp.json().get("data", {})
    except Exception:  # noqa: BLE001 — enrichment is best-effort, never breaks the page
        logger.warning("AbuseIPDB lookup failed for %s", ip, exc_info=True)
        return row

    values = {
        "ip": ip,
        "abuse_score": data.get("abuseConfidenceScore"),
        "country_code": data.get("countryCode"),
        "isp": data.get("isp"),
        "usage_type": data.get("usageType"),
        "total_reports": data.get("totalReports"),
        "last_reported_at": _parse_dt(data.get("lastReportedAt")),
        "raw": data,
        "fetched_at": _now(),
    }
    stmt = pg_insert(IpIntel).values(**values).on_conflict_do_update(
        index_elements=["ip"], set_={k: v for k, v in values.items() if k != "ip"})
    await db.execute(stmt)
    await db.commit()
    return await db.get(IpIntel, ip)


async def enrich_many(db: AsyncSession, ips: list[str]) -> dict[str, IpIntel]:
    """Enrich a bounded batch (one page, <=20). Sequential is fine at this size;
    the cache absorbs repeats. Returns {ip: IpIntel} for IPs that resolved."""
    out: dict[str, IpIntel] = {}
    for ip in ips:
        r = await enrich(db, ip)
        if r is not None:
            out[ip] = r
    return out
