"""Cron-expression helpers (spec 09 §9.3).

We compute next-expected fire times using APScheduler's bundled CronTrigger
parser (``CronTrigger.from_crontab``) so no extra dependency (e.g. croniter) is
required — APScheduler is already a project dependency.
"""
from datetime import datetime, timedelta, timezone

from apscheduler.triggers.cron import CronTrigger


def is_valid_cron(expr: str) -> bool:
    """True if ``expr`` is a parseable 5-field crontab string."""
    if not expr or len(expr.split()) != 5:
        return False
    try:
        CronTrigger.from_crontab(expr, timezone=timezone.utc)
        return True
    except (ValueError, KeyError):
        return False


def next_fire_after(expr: str, base: datetime) -> datetime | None:
    """Next scheduled fire time strictly after ``base``.

    ``get_next_fire_time`` is inclusive of the supplied instant, so we nudge the
    base forward by 1 second to always return the *next* window. Returns None if
    the expression is invalid or has no future fire time.
    """
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    try:
        trigger = CronTrigger.from_crontab(expr, timezone=timezone.utc)
    except (ValueError, KeyError):
        return None
    nxt = trigger.get_next_fire_time(None, base + timedelta(seconds=1))
    return nxt
