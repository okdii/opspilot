"""
Metric and log ingestion — receives data from Telegraf and Fluent Bit agents.

Metrics arrive as InfluxDB Line Protocol (Telegraf's default Line Protocol output).
Logs arrive as JSON arrays (Fluent Bit's HTTP output, json format).

Each line of Line Protocol creates one or more rows in server_metrics — one row
per numeric field — keeping the normalized (time, server_id, metric_name, value,
labels) shape that the rest of the system queries.
"""

from datetime import datetime, timezone
from typing import Iterator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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

async def write_metrics(server_id: UUID, line_protocol_body: str, db: AsyncSession) -> int:
    """
    Parse Line Protocol and INSERT one row per numeric field to server_metrics.

    Returns the number of rows inserted.
    """
    rows: list[dict] = []
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
            rows.append({
                "time": rec["time"],
                "server_id": server_id,
                "metric_name": f"{rec['measurement']}.{fname}",
                "value": num,
                "labels": labels_json,
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
    return len(rows)


async def write_logs(server_id: UUID, records: list[dict], db: AsyncSession) -> int:
    """
    Insert log records from Fluent Bit (JSON array, one record per line).

    Each record is expected to have at least `log` (message). Extra fields are
    stored in the `raw` JSONB column.
    """
    if not records:
        return 0

    import json
    rows = []
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
        severity = rec.get("severity") or rec.get("level") or "info"
        message = rec.get("log") or rec.get("message") or ""

        rows.append({
            "time": ts,
            "server_id": server_id,
            "source": str(source)[:80],
            "severity": str(severity)[:20],
            "message": str(message),
            "raw": json.dumps(rec),
        })

    await db.execute(
        text("""
            INSERT INTO server_logs (time, server_id, source, severity, message, raw)
            VALUES (:time, :server_id, :source, :severity, :message, CAST(:raw AS JSONB))
        """),
        rows,
    )
    await db.commit()
    return len(rows)
