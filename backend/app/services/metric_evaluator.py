"""Metric alert evaluator — the 30s APScheduler job (spec 10 §11.1, §11.3).

Opens its own AsyncSession, loads every *enabled* ``AlertRule``, and for each
computes the rolling N-minute average of the mapped Telegraf metric over
``server_metrics``. When the average breaches ``threshold`` it fires through the
committed :func:`app.services.alerting.fire_alert` seam (dedup + cooldown +
maintenance suppression + email + WS live there). When the average is back at or
below threshold it increments the open alert's ``consecutive_clear_count`` and
auto-resolves at 2 consecutive clean ticks (key decision: resolve at 2).

DB / replication coverage (spec §11.3):
  * ``db_connections`` / ``db_replication_lag`` ride the same rolling-average
    ``server_metrics`` path as any other metric rule (rule.metric is the spec
    key; the map below resolves it to the stored Telegraf name).
  * ``db_replication_stopped`` is a special boolean rule: when the *latest*
    ``mariadb.replication_running`` sample reads 0 it fires immediately (no
    rolling average); when it reads 1 it clears via the same 2-tick path.

Maintenance: entering a window already suppresses open alerts (maintenance
router). On window *end* the suppressed alerts are resolved (send_email=False)
so the slate is clean, and this evaluator re-fires fresh on the next tick if the
condition still breaches (subject to cooldown). That un-suppress sweep lives
here so the metric path owns its own re-evaluation.

Wiring (coordinator adds to scheduler.py / main.py — NOT edited here):
    scheduler.add_job(
        metric_alert_evaluator, "interval", seconds=30,
        id="metric_alert_evaluator", replace_existing=True,
    )
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import and_, select, text

from app.database import AsyncSessionLocal
from app.models.other import Alert, AlertRule, MaintenanceWindow
from app.services.alerting import OPEN_STATES, fire_alert, resolve_alert

logger = logging.getLogger(__name__)

# Number of consecutive clean ticks before an open alert auto-resolves
# (key decision: consecutive_clear_count resolves at 2).
CLEAR_THRESHOLD = 2

# spec metric key -> stored Telegraf metric_name in server_metrics.
# Stored names verified against live ingestion (NOT the spec's cpu_usage_total).
RULE_METRIC: dict[str, str] = {
    "cpu": "cpu.usage_active",
    "ram": "mem.used_percent",
    "disk": "disk.used_percent",
    "disk_inode": "disk.inodes_used_percent",
    "db_connections": "mysql.threads_connected",
    "db_replication_lag": "mariadb.seconds_behind_master",
}

# Metric keys whose stored sample carries a per-filesystem `path` label; for
# these we evaluate the root filesystem only (spec defaults target '/').
ROOT_FS_METRICS = {"disk", "disk_inode"}

# Special boolean rule: latest sample of this metric == 0 means replication has
# stopped (fire immediately, no rolling average).
REPLICATION_METRIC = "db_replication_stopped"
REPLICATION_STORED = "mariadb.replication_running"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _rolling_avg(db, server_id, stored_metric: str, window_min: int, root_fs: bool):
    """Rolling average of a metric over the last ``window_min`` minutes.

    Returns float, or None when there are no samples in the window."""
    fs_clause = " AND labels->>'path' = '/' " if root_fs else ""
    stmt = text(
        f"""
        SELECT AVG(value) AS avg
        FROM server_metrics
        WHERE server_id = :sid
          AND metric_name = :m
          {fs_clause}
          AND time > now() - make_interval(mins => :win)
        """
    )
    row = (
        await db.execute(stmt, {"sid": str(server_id), "m": stored_metric, "win": int(window_min)})
    ).first()
    if row is None or row.avg is None:
        return None
    return float(row.avg)


async def _latest_value(db, server_id, stored_metric: str):
    """Latest single sample of a metric (within a short lookback). None if absent."""
    stmt = text(
        """
        SELECT value
        FROM server_metrics
        WHERE server_id = :sid
          AND metric_name = :m
          AND time > now() - interval '10 minutes'
        ORDER BY time DESC
        LIMIT 1
        """
    )
    row = (await db.execute(stmt, {"sid": str(server_id), "m": stored_metric})).first()
    if row is None or row.value is None:
        return None
    return float(row.value)


async def _open_alerts_for(db, alert_type: str, server_id):
    """Open (firing/acknowledged/snoozed/suppressed) alerts for (type, server_id)."""
    return (
        await db.execute(
            select(Alert).where(
                and_(
                    Alert.type == alert_type,
                    Alert.server_id == server_id,
                    Alert.state.in_(OPEN_STATES),
                )
            )
        )
    ).scalars().all()


async def _clear_or_resolve(db, alert_type: str, server_id):
    """A clean tick: bump consecutive_clear_count on each open alert; resolve at 2.

    Suppressed alerts (active maintenance) are left untouched — they are cleared
    by the maintenance-end sweep, not by a clean metric tick."""
    for alert in await _open_alerts_for(db, alert_type, server_id):
        if alert.state == "suppressed":
            continue
        alert.consecutive_clear_count = (alert.consecutive_clear_count or 0) + 1
        if alert.consecutive_clear_count >= CLEAR_THRESHOLD:
            await resolve_alert(db, alert, commit=False)
        else:
            await db.flush()


async def _reset_clears(db, alert_type: str, server_id):
    """A breaching tick: a still-open alert's clean streak is broken."""
    for alert in await _open_alerts_for(db, alert_type, server_id):
        if alert.state == "suppressed":
            continue
        if alert.consecutive_clear_count:
            alert.consecutive_clear_count = 0
            await db.flush()


async def _unsuppress_ended_maintenance(db) -> None:
    """Resolve (silently) any suppressed alerts whose server has no active
    maintenance window. Entering a window suppressed them; on window end the
    slate is cleared so the next breaching tick re-fires a fresh alert."""
    suppressed = (
        await db.execute(select(Alert).where(Alert.state == "suppressed"))
    ).scalars().all()
    if not suppressed:
        return

    now = _now()
    # Cache active-window lookups per server.
    active_cache: dict[object, bool] = {}
    for alert in suppressed:
        sid = alert.server_id
        if sid is None:
            continue
        if sid not in active_cache:
            windows = (
                await db.execute(
                    select(MaintenanceWindow).where(MaintenanceWindow.server_id == sid)
                )
            ).scalars().all()
            is_active = False
            for w in windows:
                starts = w.starts_at
                ends = w.ends_at
                if starts is not None and starts.tzinfo is None:
                    starts = starts.replace(tzinfo=timezone.utc)
                if ends is not None and ends.tzinfo is None:
                    ends = ends.replace(tzinfo=timezone.utc)
                if starts is not None and starts <= now and (ends is None or ends > now):
                    is_active = True
                    break
            active_cache[sid] = is_active
        if not active_cache[sid]:
            # window ended — clear the slate; evaluators re-fire if still breaching.
            await resolve_alert(db, alert, send_email=False, commit=False)


async def _evaluate_replication(db, rule: AlertRule) -> None:
    """db_replication_stopped: latest sample == 0 → fire immediately; == 1 → clear."""
    latest = await _latest_value(db, rule.server_id, REPLICATION_STORED)
    if latest is None:
        return  # no replication telemetry on this server — nothing to evaluate
    if latest == 0:
        await _reset_clears(db, rule.metric, rule.server_id)
        fired = await fire_alert(
            db,
            type=rule.metric,
            severity="critical",
            message="MariaDB replication is not running (Slave_SQL/IO stopped).",
            server_id=rule.server_id,
            cooldown_min=rule.cooldown_min,
            email_meta={"condition": "replication_running", "value": 0, "threshold": 1},
            commit=False,
        )
        if fired is not None:
            rule.last_fired_at = _now()
    else:
        await _clear_or_resolve(db, rule.metric, rule.server_id)


async def _evaluate_rule(db, rule: AlertRule) -> None:
    """Evaluate one metric AlertRule against its rolling window."""
    if rule.metric == REPLICATION_METRIC:
        await _evaluate_replication(db, rule)
        return

    stored = RULE_METRIC.get(rule.metric)
    if stored is None:
        logger.debug("metric_evaluator: unmapped rule metric %r — skipping", rule.metric)
        return

    avg = await _rolling_avg(
        db,
        rule.server_id,
        stored,
        rule.rolling_window_min,
        root_fs=rule.metric in ROOT_FS_METRICS,
    )
    if avg is None:
        return  # no data in window — neither breach nor clear

    if avg > rule.threshold:
        await _reset_clears(db, rule.metric, rule.server_id)
        fired = await fire_alert(
            db,
            type=rule.metric,
            severity="critical",
            message=(
                f"{rule.metric} averaged {avg:.1f}% over {rule.rolling_window_min}m "
                f"— threshold {rule.threshold:g}%"
            ),
            server_id=rule.server_id,
            cooldown_min=rule.cooldown_min,
            email_meta={
                "condition": f"{rule.metric} > {rule.threshold:g}%",
                "value": round(avg, 1),
                "threshold": rule.threshold,
            },
            commit=False,
        )
        if fired is not None:
            rule.last_fired_at = _now()
    else:
        await _clear_or_resolve(db, rule.metric, rule.server_id)


async def metric_alert_evaluator() -> None:
    """APScheduler entry point (30s). Opens its own session, evaluates every
    enabled metric rule, and commits once."""
    async with AsyncSessionLocal() as db:
        try:
            await _unsuppress_ended_maintenance(db)

            rules = (
                await db.execute(select(AlertRule).where(AlertRule.enabled.is_(True)))
            ).scalars().all()
            for rule in rules:
                try:
                    await _evaluate_rule(db, rule)
                except Exception:  # noqa: BLE001 — one bad rule must not stall the rest
                    logger.exception(
                        "metric_evaluator: rule %s (%s) evaluation failed",
                        rule.id,
                        rule.metric,
                    )
            await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("metric_alert_evaluator tick failed")
            await db.rollback()
