"""Server-detail historical metric reads (spec 04 §5)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import CurrentUser
from app.routers.servers import _assert_server_access
from app.services.metric_catalog import (
    HAS_LABELS, RANGE_INTERVAL, RANGE_SOURCE, REAL_FS_DENYLIST, is_counter, to_rate,
)

router = APIRouter(prefix="/api/servers", tags=["metrics"])


def _parse_label_filter(lf: str | None) -> tuple[str, str] | None:
    if not lf or "=" not in lf:
        return None
    k, v = lf.split("=", 1)
    return k.strip(), v.strip()


@router.get("/{server_id}/metrics")
async def get_metrics(
    server_id: str,
    user: CurrentUser,
    range: str = Query(...),
    metrics: str = Query(...),
    label_filter: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    await _assert_server_access(server_id, user, db)
    if range not in RANGE_SOURCE:
        raise HTTPException(400, f"invalid range: {range}")
    source, valcol, timecol, resolution = RANGE_SOURCE[range]
    interval = RANGE_INTERVAL[range]
    has_labels = HAS_LABELS[source]
    names = [m.strip() for m in metrics.split(",") if m.strip()]
    if not names:
        raise HTTPException(400, "no metrics requested")

    lf = _parse_label_filter(label_filter)
    where_label = ""
    where_fs = ""
    params: dict = {"sid": server_id, "names": names}

    if has_labels:
        labels_col = "labels"
        if lf:
            where_label = " AND labels->>:lkey = :lval "
            params["lkey"], params["lval"] = lf
        # Always exclude pseudo-filesystems for disk.* metrics.
        if any(n.startswith("disk.") for n in names):
            where_fs = " AND (labels->>'fstype' IS NULL OR labels->>'fstype' <> ALL(:denyfs)) "
            params["denyfs"] = sorted(REAL_FS_DENYLIST)
    else:
        # Continuous aggregates roll up by (server_id, metric_name); no labels.
        labels_col = "NULL::jsonb"

    stmt = text(f"""
        SELECT metric_name, {labels_col} AS labels, {timecol} AS t, {valcol} AS v
        FROM {source}
        WHERE server_id = :sid
          AND metric_name IN :names
          AND {timecol} >= now() - INTERVAL '{interval}'
          {where_label}
          {where_fs}
        ORDER BY metric_name, {labels_col}, {timecol} ASC
    """).bindparams(bindparam("names", expanding=True))

    rows = (await db.execute(stmt, params)).all()

    # group into series keyed by (metric_name, sorted labels)
    grouped: dict[tuple, dict] = {}
    for mname, labels, t, v in rows:
        labels = labels or {}
        key = (mname, tuple(sorted(labels.items())))
        g = grouped.setdefault(key, {"metric_name": mname, "labels": labels, "_pts": []})
        g["_pts"].append({"time": t.isoformat(), "value": float(v) if v is not None else None, "_t": t})

    series = []
    for g in grouped.values():
        pts = g["_pts"]
        if is_counter(g["metric_name"]):
            pts = to_rate([p for p in pts if p["value"] is not None])
        else:
            pts = [{"time": p["time"], "value": p["value"]} for p in pts]
        series.append({"metric_name": g["metric_name"], "labels": g["labels"], "data": pts})

    return {"range": range, "resolution": resolution, "series": series}


@router.get("/{server_id}/metrics/latest")
async def get_latest(server_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_server_access(server_id, user, db)
    rows = (await db.execute(text("""
        SELECT DISTINCT ON (metric_name, labels)
               metric_name, labels, value, time
        FROM server_metrics
        WHERE server_id = :sid
          AND time >= now() - INTERVAL '10 minutes'
        ORDER BY metric_name, labels, time DESC
    """), {"sid": server_id})).all()

    out: dict = {}
    for mname, labels, value, t in rows:
        labels = labels or {}
        entry = {"value": float(value) if value is not None else None,
                 "labels": labels, "time": t.isoformat()}
        if labels and any(k in labels for k in ("path", "interface", "name", "cpu")):
            out.setdefault(mname, [])
            if isinstance(out[mname], list):
                out[mname].append(entry)
        else:
            out[mname] = {"value": entry["value"], "time": entry["time"]}
    return out


@router.get("/{server_id}/processes", status_code=501)
async def get_processes(server_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_server_access(server_id, user, db)
    raise HTTPException(
        status_code=501,
        detail={"blocked": "agent-config", "detail": "top_processes not collected by Telegraf"},
    )
