"""Server maintenance windows (spec 04 §3.1)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AdminUser, CurrentUser
from app.models.other import MaintenanceWindow
from app.routers.servers import _assert_server_access

router = APIRouter(prefix="/api/servers", tags=["maintenance"])


class MaintenanceIn(BaseModel):
    reason: str | None = None
    ends_at: datetime | None = None


def _active_window(db_rows):
    now = datetime.now(timezone.utc)
    for w in db_rows:
        starts = w.starts_at.replace(tzinfo=timezone.utc) if w.starts_at.tzinfo is None else w.starts_at
        ends = None
        if w.ends_at is not None:
            ends = w.ends_at.replace(tzinfo=timezone.utc) if w.ends_at.tzinfo is None else w.ends_at
        if starts <= now and (ends is None or ends > now):
            return w
    return None


@router.get("/{server_id}/maintenance")
async def get_maintenance(server_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_server_access(server_id, user, db)
    rows = (await db.execute(
        select(MaintenanceWindow).where(MaintenanceWindow.server_id == server_id)
    )).scalars().all()
    w = _active_window(rows)
    if not w:
        return {"active": False}
    return {
        "active": True,
        "reason": w.note,
        "starts_at": w.starts_at.isoformat(),
        "ends_at": w.ends_at.isoformat() if w.ends_at else None,
    }


@router.post("/{server_id}/maintenance", status_code=201)
async def start_maintenance(
    server_id: str, body: MaintenanceIn, user: AdminUser, db: AsyncSession = Depends(get_db)
):
    await _assert_server_access(server_id, user, db)
    w = MaintenanceWindow(
        server_id=server_id,
        starts_at=datetime.now(timezone.utc),
        ends_at=body.ends_at,
        note=body.reason,
        created_by=user.id,
    )
    db.add(w)
    # Suppress this server's active alerts (no email for this transition). Spec 10 §16.
    await db.execute(text("""
        UPDATE alert SET state='suppressed'
        WHERE server_id = :sid AND state IN ('firing','acknowledged','snoozed')
    """), {"sid": server_id})
    await db.commit()
    return {"active": True}


@router.delete("/{server_id}/maintenance", status_code=204)
async def end_maintenance(server_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)):
    await _assert_server_access(server_id, user, db)
    rows = (await db.execute(
        select(MaintenanceWindow).where(MaintenanceWindow.server_id == server_id)
    )).scalars().all()
    w = _active_window(rows)
    if w:
        w.ends_at = datetime.now(timezone.utc)
        await db.commit()
    return None
