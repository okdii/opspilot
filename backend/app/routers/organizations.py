from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AdminUser, CurrentUser
from app.models.organization import Organization
from app.models.server import Server
from app.models.other import Domain
from app.models.user import UserOrganization
from app.schemas.organization import OrgCreate, OrgOut, OrgStatsOut, OrgUpdate

router = APIRouter(prefix="/api/organizations", tags=["organizations"])


@router.get("", response_model=list[OrgOut])
async def list_orgs(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    if user.role == "admin":
        result = await db.execute(select(Organization).order_by(Organization.name))
        return result.scalars().all()
    else:
        result = await db.execute(
            select(Organization)
            .join(UserOrganization, UserOrganization.org_id == Organization.id)
            .where(UserOrganization.user_id == user.id)
            .order_by(Organization.name)
        )
        return result.scalars().all()


@router.post("", response_model=OrgOut, status_code=201)
async def create_org(body: OrgCreate, user: AdminUser, db: AsyncSession = Depends(get_db)):
    existing = await db.scalar(select(Organization).where(Organization.slug == body.slug))
    if existing:
        raise HTTPException(409, detail={"error": "slug_taken", "message": "This slug is already taken."})

    org = Organization(name=body.name, slug=body.slug, description=body.description)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


@router.get("/{org_id}", response_model=OrgOut)
async def get_org(org_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    org = await _get_accessible_org(org_id, user, db)
    return org


@router.patch("/{org_id}", response_model=OrgOut)
async def update_org(org_id: str, body: OrgUpdate, user: AdminUser, db: AsyncSession = Depends(get_db)):
    org = await db.scalar(select(Organization).where(Organization.id == org_id))
    if not org:
        raise HTTPException(404, detail={"error": "not_found", "message": "Organization not found."})

    if body.name is not None:
        org.name = body.name
    if body.description is not None:
        org.description = body.description

    await db.commit()
    await db.refresh(org)
    return org


@router.delete("/{org_id}", status_code=204)
async def delete_org(org_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)):
    org = await db.scalar(select(Organization).where(Organization.id == org_id))
    if not org:
        raise HTTPException(404, detail={"error": "not_found", "message": "Organization not found."})

    server_count = await db.scalar(
        select(func.count()).select_from(Server).where(Server.org_id == org_id, Server.is_active == True)
    ) or 0
    domain_count = await db.scalar(
        select(func.count()).select_from(Domain).where(Domain.org_id == org_id)
    ) or 0

    if server_count > 0 or domain_count > 0:
        raise HTTPException(409, detail={
            "error": "has_resources",
            "message": "Organization has active resources.",
            "servers": server_count,
            "domains": domain_count,
        })

    # Purge soft-deleted servers in this org (FK is RESTRICT)
    await db.execute(delete(Server).where(Server.org_id == org_id, Server.is_active == False))

    await db.delete(org)
    await db.commit()
    return None


@router.get("/{org_id}/stats", response_model=OrgStatsOut)
async def org_stats(org_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _get_accessible_org(org_id, user, db)

    server_count = await db.scalar(
        select(func.count()).select_from(Server).where(Server.org_id == org_id, Server.is_active == True)
    ) or 0
    domain_count = await db.scalar(
        select(func.count()).select_from(Domain).where(Domain.org_id == org_id)
    ) or 0
    member_count = await db.scalar(
        select(func.count()).select_from(UserOrganization).where(UserOrganization.org_id == org_id)
    ) or 0

    return OrgStatsOut(server_count=server_count, domain_count=domain_count, member_count=member_count)


async def _get_accessible_org(org_id: str, user, db: AsyncSession) -> Organization:
    org = await db.scalar(select(Organization).where(Organization.id == org_id))
    if not org:
        raise HTTPException(404, detail={"error": "not_found", "message": "Organization not found."})
    if user.role != "admin":
        membership = await db.scalar(
            select(UserOrganization).where(
                UserOrganization.user_id == user.id,
                UserOrganization.org_id == org_id,
            )
        )
        if not membership:
            raise HTTPException(403, detail={"error": "forbidden", "message": "Access denied."})
    return org
