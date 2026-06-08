from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import create_token
from app.core.rate_limit import limiter
from app.core.security import hash_password, verify_password
from app.database import get_db
from app.deps import CurrentUser
from app.models.session import Session
from app.models.user import User, UserOrganization
from app.models.organization import Organization
from app.routers.setup import _set_auth_cookie
from app.schemas.auth import (
    ChangePasswordRequest,
    InviteAcceptRequest,
    LoginRequest,
    MeResponse,
    OrgOut,
)
from app.ws.tickets import ticket_store
from app.models.invite import Invite

router = APIRouter(prefix="/api/auth", tags=["auth"])
invite_router = APIRouter(prefix="/api/invite", tags=["invite"])
ws_router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/login")
@limiter.limit("10/15minutes")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    user = await db.scalar(select(User).where(User.username == body.username))
    # Constant-time: always verify even when user not found to prevent timing attacks
    dummy_hash = "$2b$12$invalid.hash.that.never.matches.anything.at.all.padding"
    stored = user.password_hash if user else dummy_hash
    valid = verify_password(body.password, stored)

    if not user or not valid:
        raise HTTPException(401, detail={"error": "invalid_credentials", "message": "Invalid username or password."})

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


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    session = getattr(request.state, "current_session", None)
    if session:
        session.revoked = True
        await db.commit()

    response.delete_cookie("opspilot_jwt", path="/", samesite="strict")
    return None


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    if user.role == "admin":
        orgs_q = await db.execute(select(Organization))
        orgs = orgs_q.scalars().all()
        org_list = [OrgOut(id=str(o.id), name=o.name, slug=o.slug, my_role="admin") for o in orgs]
    else:
        memberships_q = await db.execute(
            select(UserOrganization, Organization)
            .join(Organization, UserOrganization.org_id == Organization.id)
            .where(UserOrganization.user_id == user.id)
        )
        org_list = [
            OrgOut(id=str(org.id), name=org.name, slug=org.slug, my_role=mem.role)
            for mem, org in memberships_q.all()
        ]

    return MeResponse(id=str(user.id), username=user.username, role=user.role, created_at=user.created_at, orgs=org_list)


@ws_router.get("/ws-ticket")
async def ws_ticket(user: CurrentUser):
    ticket = ticket_store.issue(str(user.id))
    return {"ticket": ticket}


@router.patch("/password", status_code=204)
async def change_password(body: ChangePasswordRequest, request: Request, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(401, detail={"error": "wrong_password", "message": "Current password is incorrect."})

    user.password_hash = hash_password(body.new_password)
    # Security best practice: revoke every other session after a password change.
    current_jti = str(request.state.current_session.jti)
    await db.execute(
        update(Session)
        .where(Session.user_id == user.id, Session.jti != current_jti)
        .values(revoked=True)
    )
    await db.commit()
    return None


# ── Invite endpoints ──────────────────────────────────────────────────────────

@invite_router.get("/{token}")
async def get_invite(token: str, db: AsyncSession = Depends(get_db)):
    invite = await db.scalar(select(Invite).where(Invite.token == token))
    if not invite:
        raise HTTPException(404, detail={"error": "not_found", "message": "This invite link is invalid."})
    if invite.accepted_at is not None:
        raise HTTPException(409, detail={"error": "already_accepted", "message": "This invite has already been used. Please log in."})
    if invite.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(410, detail={"error": "expired", "message": "This invite link has expired. Ask your admin to resend it."})
    return {"email": invite.email, "role": invite.role}


@invite_router.post("/{token}/accept")
async def accept_invite(
    token: str,
    body: InviteAcceptRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    invite = await db.scalar(select(Invite).where(Invite.token == token))
    if not invite:
        raise HTTPException(404, detail={"error": "not_found", "message": "This invite link is invalid."})
    if invite.accepted_at is not None:
        raise HTTPException(409, detail={"error": "already_accepted", "message": "This invite has already been used. Please log in."})
    if invite.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(410, detail={"error": "expired", "message": "This invite link has expired."})

    existing = await db.scalar(select(User).where(User.username == body.username))
    if existing:
        raise HTTPException(422, detail={"error": "username_taken", "message": "This username is already taken."})

    user = User(username=body.username, password_hash=hash_password(body.password), role="member")
    db.add(user)
    await db.flush()

    membership = UserOrganization(user_id=user.id, org_id=invite.org_id, role=invite.role)
    db.add(membership)

    invite.accepted_at = datetime.now(timezone.utc)

    jwt_token, jti, expires_at = create_token(str(user.id))
    session = Session(
        user_id=user.id,
        jti=jti,
        expires_at=expires_at,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(session)
    await db.commit()

    _set_auth_cookie(response, jwt_token, settings.debug)
    return {"ok": True}
