"""Single source of truth mapping spec-04 metric concepts to real Telegraf
metric names (verified against live ingestion 2026-06-02). Endpoints, rate
logic, and the frontend's requested names all resolve through here."""

# Telegraf metrics that are cumulative monotonic counters -> must be served as
# per-second rates (delta / dt), never raw.
COUNTER_METRICS: set[str] = {
    "diskio.read_bytes", "diskio.write_bytes", "diskio.reads", "diskio.writes",
    "net.bytes_recv", "net.bytes_sent", "net.packets_recv", "net.packets_sent",
    "net.err_in", "net.err_out", "net.drop_in", "net.drop_out",
}

# Filesystem types to exclude from disk queries (pseudo / virtual filesystems).
REAL_FS_DENYLIST: set[str] = {
    "tmpfs", "devtmpfs", "efivarfs", "squashfs", "overlay", "proc", "sysfs",
    "cgroup", "cgroup2", "devpts", "mqueue", "debugfs", "tracefs", "ramfs",
    "fusectl", "configfs", "pstore", "bpf", "autofs", "binfmt_misc", "hugetlbfs",
}

# range -> (source_table, value_column, time_column, resolution_label)
RANGE_SOURCE: dict[str, tuple[str, str, str, str]] = {
    "1h":  ("server_metrics",        "value",     "time",   "10s"),
    "6h":  ("server_metrics",        "value",     "time",   "10s"),
    "24h": ("server_metrics_hourly", "avg_value", "bucket", "1h"),
    "7d":  ("server_metrics_daily",  "avg_value", "bucket", "24h"),
    "30d": ("server_metrics_daily",  "avg_value", "bucket", "24h"),
}

# range -> lookback interval for the WHERE clause
RANGE_INTERVAL: dict[str, str] = {
    "1h": "1 hour", "6h": "6 hours", "24h": "24 hours", "7d": "7 days", "30d": "30 days",
}

# The continuous-aggregate views (24h/7d/30d sources) roll up only by
# (server_id, metric_name) and carry no `labels` column. Raw server_metrics does.
HAS_LABELS: dict[str, bool] = {
    "server_metrics": True,
    "server_metrics_hourly": False,
    "server_metrics_daily": False,
}


def is_counter(metric_name: str) -> bool:
    return metric_name in COUNTER_METRICS


def fs_denylist_sql_array() -> list[str]:
    return sorted(REAL_FS_DENYLIST)


def to_rate(points: list[dict]) -> list[dict]:
    """Convert a cumulative-counter series into per-second rates.
    points: [{"time": iso_or_dt, "value": float}, ...] sorted ascending by time.
    Returns one fewer point (first has no predecessor). Negative deltas
    (counter reset) are dropped."""
    out: list[dict] = []
    for prev, cur in zip(points, points[1:]):
        dt = (cur["_t"] - prev["_t"]).total_seconds()
        if dt <= 0:
            continue
        delta = cur["value"] - prev["value"]
        if delta < 0:            # counter reset / reboot
            continue
        out.append({"time": cur["time"], "value": round(delta / dt, 4)})
    return out
