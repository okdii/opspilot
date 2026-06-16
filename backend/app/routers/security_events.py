"""Security Events timeline — read-only view over fired security alerts (Part 1).

GET /api/servers/{server_id}/security/events
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
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


@router.get("/{server_id}/security/events")
async def security_events(
    server_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    await _check_access(server_id, user, db)

    rows = (
        await db.execute(
            select(Alert)
            .where(Alert.server_id == server_id, Alert.type.in_(SECURITY_TYPES))
            .order_by(Alert.sent_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
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
    ]
