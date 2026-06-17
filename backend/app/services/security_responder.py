"""Security auto-responder (Part 2).

A 30s APScheduler job that consumes Part-1 fired security alerts and, per the
action plan + safety gates, either auto-executes Tier-1 remediation or queues a
Tier-2 action for human approval. One `security_actions` row per (alert, action)
is the idempotency key — already-handled alerts are skipped, making it
restart-safe and double-act-proof.

Also exposes `ttl_expiry()`: a 60s job that unblocks IPs whose block has aged
past the per-server `block_ttl_hours`.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.other import Alert, SecurityAction
from app.models.server import Server
from app.services import response_channel as rc
from app.services.alerting import OPEN_STATES

logger = logging.getLogger(__name__)

# type → confidence (derived here; Part 1 has no confidence field).
CONFIDENCE = {
    "webshell_command_exec": "high",
    "webshell_execution": "high",
    "webshell_upload": "high",
    "ssh_key_modified": "high",
    "db_privilege_change": "high",
    "log_tampering": "high",
    "jce_exploit_attempt": "high",
    "probe_scan": "medium",
}

# type → ordered list of (action_type, tier). Tier 1 = auto, Tier 2 = approval.
ACTION_PLAN = {
    "probe_scan":            [("block_ip", 1)],
    "webshell_upload":       [("quarantine_file", 1)],
    "webshell_execution":    [("quarantine_file", 1), ("block_ip", 1)],
    "webshell_command_exec": [("kill_pid", 1), ("block_ip", 1)],
    "jce_exploit_attempt":   [("block_ip", 1)],
    "ssh_key_modified":      [("revert_authorized_keys", 2)],
    "db_privilege_change":   [("disable_db_user", 2)],
}

# Circuit breaker: if more than N auto-actions execute on one server within the
# window, pause auto-response for that server and escalate (alert-only).
_BREAKER_MAX = 10
_BREAKER_WINDOW_MIN = 10

_IPV4 = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _global_kill_switch_on(db: AsyncSession) -> bool:
    """True when the org kill switch DISABLES auto-response (default off)."""
    row = (await db.execute(
        text("SELECT auto_response_enabled FROM app_settings WHERE id = 1")
    )).first()
    # auto_response_enabled True = master ON. Kill switch 'on' == master False.
    return not (row and row[0])


async def _recent_log_lines(db: AsyncSession, server_id, like: str,
                            since: datetime, limit: int = 50) -> list[str]:
    rows = (await db.execute(
        text(
            "SELECT message FROM server_logs "
            "WHERE server_id = :sid AND time >= :since AND message LIKE :like "
            "ORDER BY time DESC LIMIT :lim"
        ),
        {"sid": str(server_id), "since": since, "like": like, "lim": limit},
    )).all()
    return [r[0] for r in rows]


async def _extract_ip(db: AsyncSession, alert: Alert) -> str | None:
    # probe_scan/ssh messages carry the IP inline.
    m = _IPV4.search(alert.message or "")
    if m:
        return m.group(1)
    # Otherwise pull from recent access-log lines around the alert.
    since = (alert.sent_at or _now()) - timedelta(minutes=5)
    for line in await _recent_log_lines(db, alert.server_id, "%.php%", since):
        m = _IPV4.search(line)
        if m:
            return m.group(1)
    return None


async def _extract_file(db: AsyncSession, alert: Alert) -> str | None:
    since = (alert.sent_at or _now()) - timedelta(minutes=5)
    # Prefer auditd webroot_write (carries the absolute path under name="…").
    for line in await _recent_log_lines(db, alert.server_id, "%webroot_write%", since):
        m = re.search(r'name="?(/[^"\s]+\.php)', line)
        if m:
            return m.group(1)
    # Fall back to an access-log .php request path → map under default web root.
    for line in await _recent_log_lines(db, alert.server_id, "%.php%", since):
        m = re.search(r'"(?:GET|POST)\s+(/\S+\.php)', line)
        if m:
            return "/var/www/html" + m.group(1).split("?")[0]
    return None


async def _extract_pid(db: AsyncSession, alert: Alert) -> str | None:
    since = (alert.sent_at or _now()) - timedelta(minutes=5)
    for line in await _recent_log_lines(db, alert.server_id, "%webshell_exec%", since):
        m = re.search(r"\bpid=(\d+)", line)
        if m:
            return m.group(1)
    return None


async def _extract_db_user(db: AsyncSession, alert: Alert) -> str | None:
    since = (alert.sent_at or _now()) - timedelta(minutes=5)
    for like in ("%CREATE USER%", "%GRANT ALL%"):
        for line in await _recent_log_lines(db, alert.server_id, like, since):
            m = re.search(r"(?:CREATE USER|TO)\s+'([^']+)'", line, re.IGNORECASE)
            if m:
                return m.group(1)
    return None


async def _resolve_target(db: AsyncSession, alert: Alert, action_type: str,
                          server: Server) -> str | None:
    if action_type in ("block_ip",):
        return await _extract_ip(db, alert)
    if action_type == "quarantine_file":
        return await _extract_file(db, alert)
    if action_type == "kill_pid":
        return await _extract_pid(db, alert)
    if action_type == "revert_authorized_keys":
        return server.ssh_user or "root"
    if action_type == "disable_db_user":
        return await _extract_db_user(db, alert)
    return None


async def _already_handled(db: AsyncSession, alert_id) -> bool:
    row = (await db.execute(
        select(SecurityAction.id).where(SecurityAction.alert_id == alert_id).limit(1)
    )).first()
    return row is not None


async def _breaker_tripped(db: AsyncSession, server_id) -> bool:
    since = _now() - timedelta(minutes=_BREAKER_WINDOW_MIN)
    n = (await db.execute(
        text(
            "SELECT count(*) FROM security_actions "
            "WHERE server_id = :sid AND status = 'executed' AND executed_at >= :since"
        ),
        {"sid": str(server_id), "since": since},
    )).scalar_one()
    return n >= _BREAKER_MAX


async def _execute(server: Server, action_type: str, target: str) -> dict:
    if action_type == "block_ip":
        return await rc.block_ip(server, target)
    if action_type == "quarantine_file":
        return await rc.quarantine_file(server, target)
    if action_type == "kill_pid":
        return await rc.kill_pid(server, target)
    if action_type == "revert_authorized_keys":
        return await rc.revert_authorized_keys(server, target)
    if action_type == "disable_db_user":
        return await rc.disable_db_user(server, target)
    raise rc.ResponseError(f"unknown action {action_type}")


async def _handle_alert(db: AsyncSession, alert: Alert, server: Server) -> None:
    plan = ACTION_PLAN.get(alert.type)
    if not plan:
        return
    confidence = CONFIDENCE.get(alert.type)
    for action_type, tier in plan:
        target = await _resolve_target(db, alert, action_type, server)
        row = SecurityAction(
            server_id=server.id, alert_id=alert.id, action_type=action_type,
            target=target, tier=tier, confidence=confidence, actor="auto",
            status="pending_approval",
        )
        if target is None:
            row.status = "failed"
            row.detail = "could not extract a target from logs"
            db.add(row)
            continue
        if tier == 2:
            row.status = "pending_approval"
            row.detail = f"awaiting approval: {action_type} {target}"
            db.add(row)
            continue
        # Tier 1: gates already checked by caller; circuit breaker is per-server.
        if await _breaker_tripped(db, server.id):
            row.status = "failed"
            row.detail = "circuit breaker tripped — auto-response paused"
            db.add(row)
            continue
        try:
            reversal = await _execute(server, action_type, target)
            row.status = "executed"
            row.executed_at = _now()
            row.reversal = reversal
            row.detail = f"{action_type} {target}"
        except rc.ResponseError as e:
            row.status = "failed"
            row.detail = str(e)
        db.add(row)


async def security_responder() -> None:
    """30s tick: act on new fired security alerts for auto-response-enabled servers."""
    async with AsyncSessionLocal() as db:
        if await _global_kill_switch_on(db):
            return
        servers = {
            s.id: s for s in (await db.execute(
                select(Server).where(Server.auto_response_enabled.is_(True),
                                     Server.is_active.is_(True))
            )).scalars().all()
        }
        if not servers:
            return
        alerts = (await db.execute(
            select(Alert).where(
                Alert.type.in_(ACTION_PLAN.keys()),
                Alert.state.in_(OPEN_STATES),
                Alert.server_id.in_(servers.keys()),
            ).order_by(Alert.sent_at.asc())
        )).scalars().all()
        for alert in alerts:
            try:
                if await _already_handled(db, alert.id):
                    continue
                await _handle_alert(db, alert, servers[alert.server_id])
            except Exception:  # noqa: BLE001 — one bad alert must not abort the tick
                logger.warning("security_responder: alert %s failed", alert.id, exc_info=True)
        await db.commit()


async def ttl_expiry() -> None:
    """60s tick: unblock IPs whose block_ip action has aged past block_ttl_hours."""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(SecurityAction, Server)
            .join(Server, Server.id == SecurityAction.server_id)
            .where(SecurityAction.action_type == "block_ip",
                   SecurityAction.status == "executed")
        )).all()
        for action, server in rows:
            ttl = server.block_ttl_hours or 24
            if action.executed_at and _now() >= action.executed_at + timedelta(hours=ttl):
                try:
                    await rc.unblock_ip(server, action.reversal["ip"])
                    action.status = "expired"
                    action.reverted_at = _now()
                except Exception:  # noqa: BLE001
                    logger.warning("ttl_expiry: unblock failed for action %s", action.id, exc_info=True)
        await db.commit()
