"""Log-silence heartbeat (Part 1 dead-man's switch).

Fires ``log_ingestion_silent`` for any server that was actively shipping logs in
the last 24h but has sent nothing for > SILENCE_MINUTES. New servers with no
history are excluded. Auto-resolves via the shared clear/resolve path once logs
resume. Maintenance suppression is owned by fire_alert.
"""
import logging

from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.services.alerting import fire_alert
from app.services.log_evaluator import _clear_or_resolve, _reset_clear_count

logger = logging.getLogger(__name__)

SILENCE_MINUTES = 5
ALERT_TYPE = "log_ingestion_silent"


async def log_silence_evaluator() -> None:
    """One 60s tick: alert on servers whose log stream has gone silent."""
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT server_id, MAX(time) AS last_seen
                    FROM server_logs
                    WHERE time > now() - interval '24 hours'
                    GROUP BY server_id
                    """
                )
            )
        ).all()

        for server_id, last_seen in rows:
            try:
                silent = last_seen is not None and bool(
                    await db.scalar(
                        text("SELECT now() - :ts > make_interval(mins => :m)"),
                        {"ts": last_seen, "m": SILENCE_MINUTES},
                    )
                )
                if silent:
                    msg = (
                        f"No logs received for over {SILENCE_MINUTES} min from an "
                        f"active server — possible log tampering or agent stop."
                    )
                    await _reset_clear_count(db, ALERT_TYPE, str(server_id))
                    await fire_alert(
                        db,
                        type=ALERT_TYPE,
                        severity="critical",
                        message=msg,
                        server_id=str(server_id),
                        cooldown_min=30,
                        commit=False,
                    )
                else:
                    await _clear_or_resolve(db, ALERT_TYPE, str(server_id))
            except Exception:  # noqa: BLE001 — one bad server must not abort the tick
                logger.warning(
                    "log_silence_evaluator: server %s failed", server_id, exc_info=True
                )

        await db.commit()
