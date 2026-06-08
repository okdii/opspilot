
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import create_token
from app.core.security import hash_password
from app.database import get_db
from app.models.session import Session
from app.models.user import User
from app.schemas.auth import RegisterRequest

router = APIRouter(prefix="/api/setup", tags=["setup"])


async def _admin_exists(db: AsyncSession) -> bool:
    count = await db.scalar(select(func.count()).select_from(User).where(User.role == "admin"))
    return (count or 0) > 0


@router.get("/status")
async def setup_status(db: AsyncSession = Depends(get_db)):
    return {"setup_required": not await _admin_exists(db)}


@router.post("/register")
async def register(body: RegisterRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    if await _admin_exists(db):
        raise HTTPException(403, detail={"error": "setup_complete", "message": "Setup is already complete."})

    existing = await db.scalar(select(User).where(User.username == body.username))
    if existing:
        raise HTTPException(422, detail={"error": "username_taken", "message": "This username is already taken."})

    user = User(username=body.username, password_hash=hash_password(body.password), role="admin")
    db.add(user)
    await db.flush()

    token, jti, expires_at = create_token(str(user.id))
    session = Session(
        user_id=user.id,
        jti=jti,
        expires_at=expires_at,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(session)
    await db.commit()

    _set_auth_cookie(response, token, settings.debug)
    return {"ok": True}


def _set_auth_cookie(response: Response, token: str, debug: bool) -> None:
    response.set_cookie(
        key="opspilot_jwt",
        value=token,
        httponly=True,
        samesite="strict",
        max_age=86400,
        path="/",
        secure=not debug,
    )
