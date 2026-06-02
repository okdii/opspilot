import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AdminUser
from app.models.invite import Invite
from app.models.organization import Organization
from app.models.other import Settings
from app.models.user import User, UserOrganization
from app.schemas.settings import InviteCreate, OrgAssignmentCreate
from app.services.email import send_email

router = APIRouter(prefix="/api", tags=["team"])

VALID_ROLES = {"operator", "viewer"}


def _invite_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=48)


async def _org_name(db: AsyncSession, org_id) -> str | None:
    return await db.scalar(select(Organization.name).where(Organization.id == org_id))


@router.get("/team")
async def get_team(_: AdminUser, db: AsyncSession = Depends(get_db)):
    users = (await db.scalars(select(User).order_by(User.created_at))).all()
    members = []
    for u in users:
        assigns = (await db.scalars(select(UserOrganization).where(UserOrganization.user_id == u.id))).all()
        members.append({
            "id": str(u.id),
            "username": u.username,
            "role": u.role,
            "created_at": u.created_at,
            "org_assignments": [
                {"org_id": str(a.org_id), "org_name": await _org_name(db, a.org_id), "role": a.role}
                for a in assigns
            ],
        })
    invites = (await db.scalars(select(Invite).where(Invite.accepted_at.is_(None)))).all()
    pending = [{
        "id": str(i.id),
        "email": i.email,
        "org_id": str(i.org_id),
        "org_name": await _org_name(db, i.org_id),
        "role": i.role,
        "expires_at": i.expires_at,
    } for i in invites]
    return {"members": members, "pending_invites": pending}


@router.post("/invites")
async def create_invite(body: InviteCreate, admin: AdminUser, db: AsyncSession = Depends(get_db)):
    if body.role not in VALID_ROLES:
        raise HTTPException(422, detail={"error": "invalid_role", "message": "Role must be operator or viewer."})
    if "@" not in body.email:
        raise HTTPException(422, detail={"error": "invalid_email", "message": "Enter a valid email address."})
    if await db.scalar(select(User).where(User.username == body.email)):
        raise HTTPException(409, detail={"error": "already_member", "message": "This email is already a member."})
    if await db.scalar(select(Invite).where(Invite.email == body.email, Invite.accepted_at.is_(None))):
        raise HTTPException(409, detail={"error": "already_pending", "message": "An invite is already pending for this email."})

    invite = Invite(
        email=body.email,
        org_id=uuid.UUID(body.org_id),
        role=body.role,
        token=uuid.uuid4(),
        invited_by=admin.id,
        expires_at=_invite_expiry(),
    )
    db.add(invite)
    await db.commit()
    await _send_invite_email(db, invite)
    return {"ok": True, "invite_id": str(invite.id)}


@router.post("/invites/{invite_id}/resend")
async def resend_invite(invite_id: str, _: AdminUser, db: AsyncSession = Depends(get_db)):
    invite = await db.scalar(select(Invite).where(Invite.id == invite_id))
    if not invite or invite.accepted_at is not None:
        raise HTTPException(404, detail={"error": "not_found", "message": "Invite not found."})
    invite.token = uuid.uuid4()
    invite.expires_at = _invite_expiry()
    await db.commit()
    await _send_invite_email(db, invite)
    return {"ok": True}


@router.delete("/invites/{invite_id}", status_code=204)
async def revoke_invite(invite_id: str, _: AdminUser, db: AsyncSession = Depends(get_db)):
    invite = await db.scalar(select(Invite).where(Invite.id == invite_id))
    if invite:
        await db.delete(invite)
        await db.commit()


@router.post("/users/{user_id}/org-assignments")
async def add_org_assignment(user_id: str, body: OrgAssignmentCreate, _: AdminUser, db: AsyncSession = Depends(get_db)):
    if body.role not in VALID_ROLES:
        raise HTTPException(422, detail={"error": "invalid_role", "message": "Role must be operator or viewer."})
    exists = await db.scalar(select(UserOrganization).where(
        UserOrganization.user_id == user_id, UserOrganization.org_id == body.org_id))
    if exists:
        raise HTTPException(409, detail={"error": "already_assigned", "message": "User is already in this organisation."})
    db.add(UserOrganization(user_id=uuid.UUID(user_id), org_id=uuid.UUID(body.org_id), role=body.role))
    await db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}/org-assignments/{org_id}", status_code=204)
async def remove_org_assignment(user_id: str, org_id: str, _: AdminUser, db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(UserOrganization).where(
        UserOrganization.user_id == user_id, UserOrganization.org_id == org_id))
    if row:
        await db.delete(row)
        await db.commit()


@router.delete("/users/{user_id}", status_code=204)
async def remove_member(user_id: str, _: AdminUser, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        return
    if user.role == "admin":
        raise HTTPException(400, detail={"error": "cannot_remove_admin", "message": "Admins cannot be removed."})

    # Sole-operator guard: block if this user is the only operator of any org.
    assigns = (await db.scalars(select(UserOrganization).where(
        UserOrganization.user_id == user_id, UserOrganization.role == "operator"))).all()
    sole = []
    for a in assigns:
        others = await db.scalar(select(func.count()).select_from(UserOrganization).where(
            UserOrganization.org_id == a.org_id,
            UserOrganization.role == "operator",
            UserOrganization.user_id != user.id,
        ))
        if not others:
            sole.append({"org_id": str(a.org_id), "org_name": await _org_name(db, a.org_id)})
    if sole:
        raise HTTPException(409, detail={
            "error": "sole_operator",
            "orgs": sole,
            "message": f"This user is the only Operator for {len(sole)} organisation(s). Assign another Operator before removing.",
        })

    await db.delete(user)  # UserOrganization + Session rows cascade
    await db.commit()


async def _send_invite_email(db: AsyncSession, invite: Invite) -> None:
    s = await db.scalar(select(Settings).where(Settings.id == 1))
    if not s or not s.smtp_host:
        return  # email disabled; invite still valid via its link
    base = (s.base_url or "").rstrip("/")
    link = f"{base}/invite/{invite.token}"
    org_name = await _org_name(db, invite.org_id)
    body = (
        f"You have been invited to OpsPilot ({s.instance_name}) for {org_name} as {invite.role}.\n\n"
        f"Accept your invite:\n{link}\n\n"
        "This link expires in 48 hours.\n"
    )
    try:
        send_email(s, f"[OpsPilot] You're invited to {s.instance_name}", body, [invite.email])
    except Exception:
        pass  # invite persists even if email send fails; admin can resend
