from datetime import datetime, timezone
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import decode_token
from app.database import get_db
from app.models.session import Session
from app.models.user import User


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    opspilot_jwt: Annotated[str | None, Cookie()] = None,
) -> User:
    if not opspilot_jwt:
        raise HTTPException(401, detail={"error": "not_authenticated", "message": "Authentication required."})

    try:
        payload = decode_token(opspilot_jwt)
    except JWTError:
        raise HTTPException(401, detail={"error": "invalid_token", "message": "Invalid or expired session."})

    jti = payload.get("jti")
    user_id = payload.get("sub")

    session = await db.scalar(select(Session).where(Session.jti == jti))
    if (
        not session
        or session.revoked
        or session.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc)
    ):
        raise HTTPException(401, detail={"error": "session_expired", "message": "Session expired or revoked."})

    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(401, detail={"error": "user_not_found", "message": "User not found."})

    request.state.current_session = session
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(403, detail={"error": "forbidden", "message": "Admin access required."})
    return user


AdminUser = Annotated[User, Depends(require_admin)]
