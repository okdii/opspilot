"""TimescaleDB retention policy management.

Maps a retention setting key to its hypertable and (re)applies the drop_after
policy. `alerts_retention_days` targets the relational `alert` table, whose
pruning is handled by the Phase 8 alert-history cleanup job — not a hypertable
policy — so it is intentionally a no-op here.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# setting key -> hypertable name (None = not a hypertable policy)
HYPERTABLES: dict[str, str | None] = {
    "metrics_retention_days": "server_metrics",
    "logs_retention_days": "server_logs",
    "service_checks_retention_days": "service_checks",
    "alerts_retention_days": None,
}


async def apply_retention(db: AsyncSession, key: str, days: int) -> None:
    table = HYPERTABLES.get(key)
    if table is None:
        return
    # Remove any existing policy, then add a fresh one. make_interval keeps the
    # day count a bound parameter (no string interpolation into the INTERVAL).
    await db.execute(
        text("SELECT remove_retention_policy(CAST(:t AS regclass), if_exists => true)"),
        {"t": table},
    )
    await db.execute(
        text("SELECT add_retention_policy(CAST(:t AS regclass), make_interval(days => :d))"),
        {"t": table, "d": days},
    )
    await db.commit()
