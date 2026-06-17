"""Security Auto-Response actions API (Part 2).

GET  /api/servers/{server_id}/security/actions          list ledger (history + pending)
POST /api/servers/{server_id}/security/actions/{id}/approve   execute a Tier-2 pending action (admin)
POST /api/servers/{server_id}/security/actions/{id}/reject    dismiss a pending action (admin)
POST /api/servers/{server_id}/security/actions/{id}/undo      reverse an executed action (admin)
GET  /api/servers/{server_id}/security/auto-response          per-server settings
PUT  /api/servers/{server_id}/security/auto-response          update per-server settings (admin)
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AdminUser, CurrentUser
from app.models.other import Alert, SecurityAction
from app.models.server import Server
from app.routers.security_events import SECURITY_TYPES
from app.services import response_channel as rc
from app.services import security_responder as responder

router = APIRouter(prefix="/api/servers", tags=["security"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _access(server_id: str, user, db: AsyncSession) -> Server:
    from app.routers.servers import _assert_server_access
    return await _assert_server_access(server_id, user, db)


def _row(a: SecurityAction) -> dict:
    return {
        "id": a.id, "alert_id": str(a.alert_id) if a.alert_id else None,
        "action_type": a.action_type, "target": a.target, "tier": a.tier,
        "status": a.status, "actor": a.actor, "confidence": a.confidence,
        "detail": a.detail, "created_at": a.created_at, "executed_at": a.executed_at,
        "reverted_at": a.reverted_at,
        "reversible": a.action_type not in ("kill_pid",),
    }


@router.get("/{server_id}/security/actions")
async def list_actions(
    server_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
):
    await _access(server_id, user, db)
    base = select(SecurityAction).where(SecurityAction.server_id == server_id)
    if status:
        base = base.where(SecurityAction.status == status)
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    rows = (await db.execute(
        base.order_by(SecurityAction.created_at.desc()).limit(limit).offset(offset)
    )).scalars().all()
    return {"items": [_row(a) for a in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/{server_id}/security/summary")
async def security_summary(server_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Aggregate counts for the Threat Status bar. Computed server-side so the
    chips stay accurate independent of the paginated events/actions pages."""
    await _access(server_id, user, db)
    active_events = (await db.execute(
        select(func.count()).select_from(Alert).where(
            Alert.server_id == server_id,
            Alert.type.in_(SECURITY_TYPES),
            Alert.state != "resolved",
        )
    )).scalar_one()
    pending_approvals = (await db.execute(
        select(func.count()).select_from(SecurityAction).where(
            SecurityAction.server_id == server_id,
            SecurityAction.status == "pending_approval",
        )
    )).scalar_one()
    blocked_ips = (await db.execute(
        select(func.count(func.distinct(SecurityAction.target))).where(
            SecurityAction.server_id == server_id,
            SecurityAction.action_type == "block_ip",
            SecurityAction.status == "executed",
        )
    )).scalar_one()
    return {
        "active_events": active_events,
        "pending_approvals": pending_approvals,
        "blocked_ips": blocked_ips,
    }


async def _get_action(server_id: str, action_id: int, db: AsyncSession) -> SecurityAction:
    # FOR UPDATE locks the row until this request's transaction commits, so two
    # concurrent approve/undo calls on the same action serialize: the second
    # blocks here, then re-reads the post-commit status and fails its state-
    # transition guard — preventing a privileged verb from running twice.
    a = (await db.execute(
        select(SecurityAction).where(
            SecurityAction.id == action_id, SecurityAction.server_id == server_id)
        .with_for_update()
    )).scalar_one_or_none()
    if a is None:
        raise HTTPException(404, detail={"error": "not_found", "message": "Action not found."})
    return a


@router.post("/{server_id}/security/actions/{action_id}/approve")
async def approve(server_id: str, action_id: int, user: AdminUser, db: AsyncSession = Depends(get_db)):
    server = await _access(server_id, user, db)
    a = await _get_action(server_id, action_id, db)
    if a.status != "pending_approval":
        raise HTTPException(409, detail={"error": "conflict", "message": "Action is not pending."})
    a.actor = user.username
    try:
        reversal = await responder._execute(server, a.action_type, a.target)
        a.status, a.executed_at, a.reversal = "executed", _now(), reversal
        a.detail = f"approved+{a.action_type} {a.target}"
    except rc.ResponseError as e:
        a.status, a.detail = "failed", str(e)
    await db.commit()
    return _row(a)


@router.post("/{server_id}/security/actions/{action_id}/reject")
async def reject(server_id: str, action_id: int, user: AdminUser, db: AsyncSession = Depends(get_db)):
    await _access(server_id, user, db)
    a = await _get_action(server_id, action_id, db)
    if a.status != "pending_approval":
        raise HTTPException(409, detail={"error": "conflict", "message": "Action is not pending."})
    a.status, a.actor, a.detail = "rejected", user.username, "rejected by admin"
    await db.commit()
    return _row(a)


@router.post("/{server_id}/security/actions/{action_id}/undo")
async def undo(server_id: str, action_id: int, user: AdminUser, db: AsyncSession = Depends(get_db)):
    server = await _access(server_id, user, db)
    a = await _get_action(server_id, action_id, db)
    if a.status != "executed":
        raise HTTPException(409, detail={"error": "conflict", "message": "Only executed actions can be undone."})
    if a.action_type not in ("block_ip", "quarantine_file", "revert_authorized_keys", "disable_db_user"):
        raise HTTPException(400, detail={"error": "not_reversible",
                                         "message": f"{a.action_type} cannot be undone."})
    if not a.reversal:
        raise HTTPException(409, detail={"error": "no_reversal", "message": "No reversal data recorded for this action."})
    try:
        if a.action_type == "block_ip":
            await rc.unblock_ip(server, a.reversal["ip"])
        elif a.action_type == "quarantine_file":
            await rc.restore_file(server, a.reversal)
        elif a.action_type == "revert_authorized_keys":
            await rc.restore_authorized_keys(server, a.reversal)
        elif a.action_type == "disable_db_user":
            await rc.enable_db_user(server, a.reversal)
    except rc.ResponseError as e:
        raise HTTPException(502, detail={"error": "undo_failed", "message": str(e)})
    a.status, a.reverted_at, a.actor = "reverted", _now(), user.username
    await db.commit()
    return _row(a)


class AutoResponseSettings(BaseModel):
    auto_response_enabled: bool
    block_ttl_hours: int


@router.get("/{server_id}/security/auto-response")
async def get_settings(server_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    server = await _access(server_id, user, db)
    return {"auto_response_enabled": server.auto_response_enabled,
            "block_ttl_hours": server.block_ttl_hours}


@router.put("/{server_id}/security/auto-response")
async def put_settings(server_id: str, body: AutoResponseSettings,
                       user: AdminUser, db: AsyncSession = Depends(get_db)):
    server = await _access(server_id, user, db)
    if not (1 <= body.block_ttl_hours <= 720):
        raise HTTPException(422, detail={"error": "invalid", "message": "block_ttl_hours must be 1–720."})
    server.auto_response_enabled = body.auto_response_enabled
    server.block_ttl_hours = body.block_ttl_hours
    await db.commit()
    return {"auto_response_enabled": server.auto_response_enabled,
            "block_ttl_hours": server.block_ttl_hours}
