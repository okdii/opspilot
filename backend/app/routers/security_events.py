"""Security Events timeline — read-only view over fired security alerts (Part 1).

GET /api/servers/{server_id}/security/events
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import CurrentUser
from app.models.other import Alert

router = APIRouter(prefix="/api/servers", tags=["security"])


async def _check_access(server_id: str, user: CurrentUser, db: AsyncSession) -> None:
    from app.routers.servers import _assert_server_access
    await _assert_server_access(server_id, user, db)


SECURITY_TYPES = [
    "jce_exploit_attempt", "webshell_upload", "webshell_execution",
    "webshell_command_exec", "probe_scan", "new_ssh_login",
    "ssh_key_modified", "db_privilege_change", "log_tampering",
    "log_ingestion_silent",
]

STAGE = {
    "probe_scan": "Recon",
    "jce_exploit_attempt": "Exploit",
    "webshell_upload": "Upload",
    "webshell_execution": "Execute",
    "webshell_command_exec": "Execute",
    "new_ssh_login": "Persist",
    "ssh_key_modified": "Persist",
    "db_privilege_change": "Persist",
    "log_tampering": "Cover-tracks",
    "log_ingestion_silent": "Cover-tracks",
}

# Kill-chain order for the pipeline view (attacker progression left → right).
STAGE_ORDER = ["Recon", "Exploit", "Upload", "Execute", "Persist", "Cover-tracks"]

# Reverse map stage → alert types, so the feed can be filtered by stage. Stage is
# derived from type (not stored), so a stage filter expands to its member types.
STAGE_TYPES: dict[str, list[str]] = {}
for _type, _stage in STAGE.items():
    STAGE_TYPES.setdefault(_stage, []).append(_type)

# Worst-severity ranking when collapsing a stage's events to one tint.
_SEV_RANK = {"critical": 2, "warning": 1}


@router.get("/{server_id}/security/events")
async def security_events(
    server_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    stage: str | None = Query(None),
):
    await _check_access(server_id, user, db)

    base = select(Alert).where(
        Alert.server_id == server_id, Alert.type.in_(SECURITY_TYPES)
    )
    if stage and stage in STAGE_TYPES:
        base = base.where(Alert.type.in_(STAGE_TYPES[stage]))
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            base.order_by(Alert.sent_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": str(a.id),
                "type": a.type,
                "stage": STAGE.get(a.type, "—"),
                "severity": a.severity,
                "message": a.message,
                "state": a.state,
                "at": a.sent_at,
            }
            for a in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{server_id}/security/stages")
async def security_stages(
    server_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Per kill-chain-stage breakdown for the pipeline view: event count + worst
    severity per stage, in attack-progression order. Aggregated over all events
    (GROUP BY), so the pipeline stays accurate independent of the feed's page."""
    await _check_access(server_id, user, db)

    rows = (
        await db.execute(
            select(Alert.type, Alert.severity, func.count())
            .where(Alert.server_id == server_id, Alert.type.in_(SECURITY_TYPES))
            .group_by(Alert.type, Alert.severity)
        )
    ).all()

    agg = {s: {"stage": s, "count": 0, "severity": None} for s in STAGE_ORDER}
    for type_, severity, count in rows:
        s = STAGE.get(type_)
        if s is None:
            continue
        bucket = agg[s]
        bucket["count"] += count
        if bucket["severity"] is None or _SEV_RANK.get(severity, 0) > _SEV_RANK.get(bucket["severity"], 0):
            bucket["severity"] = severity

    return [agg[s] for s in STAGE_ORDER]
