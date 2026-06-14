"""
Metric and log ingestion — receives data from Telegraf and Fluent Bit agents.

Metrics arrive as InfluxDB Line Protocol (Telegraf's default Line Protocol output).
Logs arrive as JSON arrays (Fluent Bit's HTTP output, json format).

Each line of Line Protocol creates one or more rows in server_metrics — one row
per numeric field — keeping the normalized (time, server_id, metric_name, value,
labels) shape that the rest of the system queries.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Iterator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Log intelligence parsers ───────────────────────────────────────────────────
# Enrich raw JSONB with structured fields so intelligence card queries work.

_NGINX_ACCESS_RE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[[^\]]+\] '
    r'"(?P<method>\S+) (?P<url>\S+) [^"]*" '
    r'(?P<status>\d{3}) (?P<bytes>\d+|-)'
)
_MARIADB_QT_RE = re.compile(r'#\s*Query_time:\s*([\d.]+)')
_AUTH_IP_RE = re.compile(r'(?:from |rhost=)(\d{1,3}(?:\.\d{1,3}){3})')
_NGINX_ERR_SEV_RE = re.compile(r'\[(emerg|alert|crit|error|warn|notice|info|debug)\]', re.I)
_SYSLOG_ERROR_RE = re.compile(r'\b(error|fail(?:ed|ure)|segfault|oom-killer|panic|kernel bug)\b', re.I)
_SYSLOG_WARN_RE = re.compile(r'\b(warn(?:ing)?)\b', re.I)

_NGINX_SEV = {
    "emerg": "fatal", "alert": "fatal", "crit": "fatal",
    "error": "error", "warn": "warn", "notice": "info",
    "info": "info", "debug": "debug",
}
_AUTH_FAIL_WORDS = ("failed password", "authentication failure", "invalid user", "connection closed by invalid")


def _enrich_log(source: str, rec: dict, message: str) -> tuple[dict, str]:
    """Parse source-specific fields into rec; return (enriched_rec, severity)."""
    severity = "info"

    if source == "nginx_access":
        m = _NGINX_ACCESS_RE.match(message)
        if m:
            rec["ip"] = m.group("ip")
            rec["method"] = m.group("method")
            rec["url"] = m.group("url")
            rec["status_code"] = m.group("status")
            rec["bytes"] = m.group("bytes")
        # access logs carry no severity

    elif source == "nginx_error":
        m = _NGINX_ERR_SEV_RE.search(message)
        severity = _NGINX_SEV.get(m.group(1).lower(), "error") if m else "error"

    elif source == "mariadb_slow":
        m = _MARIADB_QT_RE.search(message)
        if m:
            rec["query_time"] = m.group(1)

    elif source == "auth":
        m = _AUTH_IP_RE.search(message)
        if m:
            rec["source_ip"] = m.group(1)
        lower = message.lower()
        if any(kw in lower for kw in _AUTH_FAIL_WORDS):
            severity = "warn"

    elif source == "syslog":
        if _SYSLOG_ERROR_RE.search(message):
            severity = "error"
        elif _SYSLOG_WARN_RE.search(message):
            severity = "warn"

    return rec, severity


# ── InfluxDB Line Protocol parser ─────────────────────────────────────────────
#
# Format: measurement[,tag=value[,tag=value]] field=value[,field=value] [ns_timestamp]
# Per spec, we trust agents (they're authenticated by ingestion_token).

def _parse_value(raw: str):
    """Parse a Line Protocol field value into Python."""
    if raw.endswith("i") and raw[:-1].lstrip("-").isdigit():
        return int(raw[:-1])
    if raw in ("t", "T", "true", "True", "TRUE"):
        return True
    if raw in ("f", "F", "false", "False", "FALSE"):
        return False
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    try:
        return float(raw)
    except ValueError:
        return raw  # fallback string


def _split_csv_unescaped(s: str) -> list[str]:
    """Split on unescaped commas (Line Protocol uses \\, to escape)."""
    parts: list[str] = []
    cur: list[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            cur.append(s[i:i + 2])
            i += 2
            continue
        if c == ",":
            parts.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    if cur:
        parts.append("".join(cur))
    return parts


def parse_line_protocol(text_body: str) -> Iterator[dict]:
    """Yield parsed records: {measurement, tags, fields, time}."""
    for raw in text_body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        # Three sections separated by unescaped spaces: tags, fields, [timestamp]
        # Naive split — Telegraf doesn't put spaces in tag/field keys for system metrics.
        parts = line.split(" ")
        if len(parts) < 2:
            continue

        # Parts may be split incorrectly if fields contained spaces. For Telegraf system
        # metrics this is safe. Production-grade parsers handle quoted spaces; we don't.
        if len(parts) == 2:
            mt_part, field_part = parts
            ts_part = None
        else:
            mt_part = parts[0]
            field_part = parts[1]
            ts_part = parts[2]

        mt_tokens = _split_csv_unescaped(mt_part)
        measurement = mt_tokens[0]
        tags = {}
        for t in mt_tokens[1:]:
            k, _, v = t.partition("=")
            if k:
                tags[k] = v

        fields = {}
        for f in _split_csv_unescaped(field_part):
            k, _, v = f.partition("=")
            if k:
                fields[k] = _parse_value(v)

        if ts_part:
            try:
                ts = datetime.fromtimestamp(int(ts_part) / 1e9, tz=timezone.utc)
            except ValueError:
                ts = datetime.now(timezone.utc)
        else:
            ts = datetime.now(timezone.utc)

        yield {"measurement": measurement, "tags": tags, "fields": fields, "time": ts}


# ── Writers ───────────────────────────────────────────────────────────────────

async def write_metrics(server_id: UUID, org_id, line_protocol_body: str, db: AsyncSession) -> int:
    """
    Parse Line Protocol and INSERT one row per numeric field to server_metrics.
    After persisting, publish the same rows to the in-process live bus for WS
    fan-out (additive — must never break ingestion).

    Returns the number of rows inserted.
    """
    rows: list[dict] = []
    push_rows: list[dict] = []
    import json
    for rec in parse_line_protocol(line_protocol_body):
        labels_json = json.dumps(rec["tags"]) if rec["tags"] else None
        for fname, fval in rec["fields"].items():
            if isinstance(fval, bool):
                num = 1.0 if fval else 0.0
            elif isinstance(fval, (int, float)):
                num = float(fval)
            else:
                continue  # skip strings
            metric_name = f"{rec['measurement']}.{fname}"
            rows.append({
                "time": rec["time"],
                "server_id": server_id,
                "metric_name": metric_name,
                "value": num,
                "labels": labels_json,
            })
            push_rows.append({
                "metric_name": metric_name,
                "value": num,
                "labels": rec["tags"] or {},
                "time": rec["time"].isoformat(),
            })

    if not rows:
        return 0

    await db.execute(
        text("""
            INSERT INTO server_metrics (time, server_id, metric_name, value, labels)
            VALUES (:time, :server_id, :metric_name, :value, CAST(:labels AS JSONB))
        """),
        rows,
    )
    await db.commit()

    # Live fan-out — additive; a failure here must not affect ingestion.
    try:
        from app.ws.live_bus import live_bus
        await live_bus.publish(str(server_id), str(org_id), push_rows)
    except Exception:
        logger.exception("live_bus publish failed for server %s", server_id)

    return len(rows)


async def write_logs(server_id: UUID, records: list[dict], db: AsyncSession, org_id=None) -> int:
    """
    Insert log records from Fluent Bit (JSON array, one record per line).

    Each record is expected to have at least `log` (message). Extra fields are
    stored in the `raw` JSONB column.

    After persisting, publish each entry to the live bus on channel
    server_logs:{server_id} for Log Viewer live-tail (spec 05 §8). The publish is
    additive and best-effort — a failure here must never break ingestion.
    """
    if not records:
        return 0

    import json
    rows = []
    push_rows = []
    for rec in records:
        ts_raw = rec.get("time") or rec.get("date") or rec.get("@timestamp")
        try:
            if isinstance(ts_raw, str):
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            elif isinstance(ts_raw, (int, float)):
                ts = datetime.fromtimestamp(float(ts_raw), tz=timezone.utc)
            else:
                ts = datetime.now(timezone.utc)
        except Exception:
            ts = datetime.now(timezone.utc)

        source = rec.get("source") or rec.get("tag") or "unknown"
        message = rec.get("log") or rec.get("message") or ""

        source_s = str(source)[:80]
        message_s = str(message)
        rec, derived_severity = _enrich_log(source_s, rec, message_s)
        # Honour an explicit severity from the agent if it differs from the default
        agent_sev = rec.get("severity") or rec.get("level") or ""
        severity_s = (str(agent_sev)[:20] if agent_sev and agent_sev != "info" else derived_severity)
        rows.append({
            "time": ts,
            "server_id": server_id,
            "source": source_s,
            "severity": severity_s,
            "message": message_s,
            "raw": json.dumps(rec),
        })
        push_rows.append({
            "time": ts.isoformat(),
            "server_id": str(server_id),
            "server_name": None,
            "source": source_s,
            "severity": None if source_s == "nginx_access" else (severity_s or None),
            "message": message_s,
            "fields": rec,
        })

    await db.execute(
        text("""
            INSERT INTO server_logs (time, server_id, source, severity, message, raw)
            VALUES (:time, :server_id, :source, :severity, :message, CAST(:raw AS JSONB))
        """),
        rows,
    )
    await db.commit()

    # Live fan-out — additive; a failure here must not affect ingestion.
    try:
        from app.ws.manager import ws_manager
        org = str(org_id) if org_id is not None else ""
        for entry in push_rows:
            await ws_manager.broadcast_logs(
                str(server_id), org,
                {"channel": f"server_logs:{server_id}", "event": "log_entry", "data": entry},
            )
    except Exception:
        logger.exception("live log publish failed for server %s", server_id)

    return len(rows)
