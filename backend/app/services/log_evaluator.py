"""Log alert evaluator — the 60s APScheduler job (spec 10 §11.2).

Loads every enabled ``LogAlertRule`` and, for each, counts matching rows in the
recent ``server_logs`` window:

  * **General rules** match the user-defined ``pattern`` with **ILIKE**
    (case-insensitive) and the rule ``source`` with ``LIKE``.
  * **SSH brute-force** rules (``source = 'auth'``) are special-cased: rows are
    matched with a **case-sensitive** ``LIKE '%Failed password%'``, the source
    IP is extracted from the message text, and rows are grouped per IP — any IP
    whose count reaches the threshold fires one ``ssh_brute_force`` alert.

When a rule (or, for SSH, an IP group) reaches its threshold, the evaluator
fires via the shared :func:`app.services.alerting.fire_alert` (``commit=False`` —
the job batches every rule then commits once). Dedup, cooldown, and maintenance
suppression are all owned by ``fire_alert``. Below-threshold rules drive the
2-consecutive-clean auto-resolve via ``Alert.consecutive_clear_count``.

The coroutine is exposed for the coordinator to register as a 60s interval job:

    scheduler.add_job(
        log_alert_evaluator, "interval", seconds=60,
        id="log_alert_evaluator", replace_existing=True,
    )
"""
import logging

from sqlalchemy import select, text

from app.database import AsyncSessionLocal
from app.models.other import Alert, LogAlertRule
from app.services.alerting import OPEN_STATES, fire_alert, resolve_alert

logger = logging.getLogger(__name__)

# Hardcoded internal pattern for SSH brute-force detection — case-sensitive LIKE
# per spec §11.2. Rules whose source is 'auth' are routed through the per-IP path.
_SSH_SOURCE = "auth"
_SSH_PATTERN = "%Failed password%"


def _derive_type(rule: LogAlertRule) -> str:
    """Map a LogAlertRule to its spec §15 alert ``type`` key (governs dedup)."""
    source = (rule.source or "").lower()
    pat = (rule.pattern or "").lower()

    # ── Security detection (Part 1) — classify by pattern first ──────────
    if "profiles.import" in pat:
        return "jce_exploit_attempt"
    if "webshell_exec" in pat:
        return "webshell_command_exec"
    if "webroot_write" in pat:
        return "webshell_upload"
    if "ssh_key_change" in pat:
        return "ssh_key_modified"
    if "log_tamper" in pat:
        return "log_tampering"
    if "create user" in pat or "grant all" in pat:
        return "db_privilege_change"
    if "accepted publickey" in pat:
        return "new_ssh_login"
    if " 404 " in pat:
        return "probe_scan"
    if ".php" in pat and "200" in pat:
        return "webshell_execution"
    if "post" in pat and ".php" in pat:
        return "webshell_upload"

    # ── Existing classifications ─────────────────────────────────────────
    if source == _SSH_SOURCE:
        return "ssh_brute_force"
    if "php" in source or "fatal error" in pat:
        return "php_fatal"
    if "nginx" in source:
        return "nginx_5xx"
    if "slow" in source or "query_time" in pat:
        return "slow_query_spike"
    if "mariadb" in source or "mysql" in source:
        return "mariadb_error"
    return "log_match"


async def _general_count(db, rule: LogAlertRule) -> int:
    """ILIKE count of matching rows in the rule's recent window."""
    row = await db.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM server_logs
            WHERE server_id = :sid
              AND source LIKE :source
              AND message ILIKE :pattern
              AND time > now() - make_interval(secs => :win)
            """
        ),
        {
            "sid": str(rule.server_id),
            "source": rule.source,
            "pattern": rule.pattern,
            "win": rule.window_sec,
        },
    )
    return int(row.scalar_one() or 0)


async def _ssh_bruteforce_offenders(db, rule: LogAlertRule) -> list[tuple[str, int]]:
    """Return [(source_ip, count), …] for IPs at/over threshold in the window.

    The live ``server_logs`` table has no parsed ``source_ip`` column, so the IP
    is extracted from the message text with a Postgres regex (sshd logs the
    offender as ``... from <IP> port ...``). Matching uses a case-sensitive
    ``LIKE '%Failed password%'`` per spec §11.2.
    """
    rows = await db.execute(
        text(
            r"""
            SELECT
              (regexp_match(
                 message,
                 'from ([0-9]{1,3}(?:\.[0-9]{1,3}){3}|[0-9a-fA-F:]+)'
               ))[1] AS source_ip,
              COUNT(*) AS cnt
            FROM server_logs
            WHERE server_id = :sid
              AND source = :source
              AND message LIKE :pattern
              AND time > now() - make_interval(secs => :win)
            GROUP BY source_ip
            HAVING COUNT(*) >= :threshold
            """
        ),
        {
            "sid": str(rule.server_id),
            "source": _SSH_SOURCE,
            "pattern": _SSH_PATTERN,
            "win": rule.window_sec,
            "threshold": rule.threshold,
        },
    )
    return [(r.source_ip, int(r.cnt)) for r in rows if r.source_ip]


async def _clear_or_resolve(db, alert_type: str, server_id) -> None:
    """Tick the auto-resolve counter for any open alert of this (type, server).

    Increments ``consecutive_clear_count``; at >= 2 consecutive clean ticks the
    alert resolves (spec §11.2 step 4). Snoozed/suppressed alerts are left alone
    so maintenance / snooze semantics are preserved.
    """
    open_alerts = (
        await db.execute(
            select(Alert).where(
                Alert.type == alert_type,
                Alert.server_id == server_id,
                Alert.state.in_(("firing", "acknowledged")),
            )
        )
    ).scalars().all()
    for alert in open_alerts:
        alert.consecutive_clear_count = (alert.consecutive_clear_count or 0) + 1
        if alert.consecutive_clear_count >= 2:
            await resolve_alert(db, alert, commit=False)


async def _reset_clear_count(db, alert_type: str, server_id) -> None:
    """A breach this tick — reset the clean-streak on any open alert."""
    open_alerts = (
        await db.execute(
            select(Alert).where(
                Alert.type == alert_type,
                Alert.server_id == server_id,
                Alert.state.in_(OPEN_STATES),
            )
        )
    ).scalars().all()
    for alert in open_alerts:
        alert.consecutive_clear_count = 0


async def log_alert_evaluator() -> None:
    """Evaluate every enabled LogAlertRule once (60s tick)."""
    async with AsyncSessionLocal() as db:
        rules = (
            await db.execute(select(LogAlertRule).where(LogAlertRule.enabled.is_(True)))
        ).scalars().all()

        for rule in rules:
            alert_type = _derive_type(rule)
            try:
                if rule.source == _SSH_SOURCE:
                    offenders = await _ssh_bruteforce_offenders(db, rule)
                    if offenders:
                        await _reset_clear_count(db, alert_type, rule.server_id)
                        # One alert per (type, server): the most prolific IP wins
                        # the message; dedup keeps it to a single open alert.
                        ip, cnt = max(offenders, key=lambda o: o[1])
                        msg = (
                            f"SSH brute-force: {cnt} failed password attempts from "
                            f"{ip} in the last {rule.window_sec}s "
                            f"(threshold {rule.threshold})"
                        )
                        fired = await fire_alert(
                            db,
                            type=alert_type,
                            severity=rule.severity,
                            message=msg,
                            server_id=rule.server_id,
                            cooldown_min=rule.cooldown_min,
                            commit=False,
                        )
                        if fired is not None:
                            rule.last_fired_at = fired.sent_at
                    else:
                        await _clear_or_resolve(db, alert_type, rule.server_id)
                    continue

                count = await _general_count(db, rule)
                if count >= rule.threshold:
                    await _reset_clear_count(db, alert_type, rule.server_id)
                    msg = (
                        f"{count} log line(s) matched '{rule.pattern}' on "
                        f"{rule.source} in the last {rule.window_sec}s "
                        f"(threshold {rule.threshold})"
                    )
                    fired = await fire_alert(
                        db,
                        type=alert_type,
                        severity=rule.severity,
                        message=msg,
                        server_id=rule.server_id,
                        cooldown_min=rule.cooldown_min,
                        commit=False,
                    )
                    if fired is not None:
                        rule.last_fired_at = fired.sent_at
                else:
                    await _clear_or_resolve(db, alert_type, rule.server_id)
            except Exception:  # noqa: BLE001 — one bad rule must not abort the tick
                logger.warning(
                    "log_alert_evaluator: rule %s failed", rule.id, exc_info=True
                )

        await db.commit()
