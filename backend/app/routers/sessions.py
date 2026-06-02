from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AdminUser
from app.models.session import Session
from app.schemas.settings import SessionResponse

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionResponse])
async def list_sessions(user: AdminUser, request: Request, db: AsyncSession = Depends(get_db)):
    current_jti = str(request.state.current_session.jti)
    now = datetime.now(timezone.utc)
    rows = (
        await db.scalars(
            select(Session).where(Session.user_id == user.id, Session.revoked == False)  # noqa: E712
        )
    ).all()
    rows = [r for r in rows if r.expires_at.replace(tzinfo=timezone.utc) > now]
    return [
        SessionResponse(
            jti=str(r.jti),
            is_current=(str(r.jti) == current_jti),
            ip_address=r.ip_address,
            user_agent=r.user_agent,
            issued_at=r.issued_at,
            expires_at=r.expires_at,
        )
        for r in rows
    ]


@router.patch("/{jti}/revoke", status_code=204)
async def revoke_session(jti: str, user: AdminUser, request: Request, db: AsyncSession = Depends(get_db)):
    if jti == str(request.state.current_session.jti):
        raise HTTPException(
            400,
            detail={"error": "cannot_revoke_current", "message": "Cannot revoke the current session."},
        )
    await db.execute(
        update(Session).where(Session.jti == jti, Session.user_id == user.id).values(revoked=True)
    )
    await db.commit()


@router.post("/revoke-others", status_code=204)
async def revoke_others(user: AdminUser, request: Request, db: AsyncSession = Depends(get_db)):
    current_jti = str(request.state.current_session.jti)
    await db.execute(
        update(Session).where(Session.user_id == user.id, Session.jti != current_jti).values(revoked=True)
    )
    await db.commit()
