"""Authorization helpers for WebSocket subscribe actions.

String IDs from the WS payload / JWT are compared directly against UUID columns,
matching the existing pattern in app/deps.py (asyncpg coerces them)."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.server import Server
from app.models.user import UserOrganization


async def can_access_org(user_role: str, user_id: str, org_id: str, db: AsyncSession) -> bool:
    """Admins see every org; members must have a UserOrganization membership."""
    if user_role == "admin":
        return True
    membership = await db.scalar(
        select(UserOrganization).where(
            UserOrganization.user_id == user_id,
            UserOrganization.org_id == org_id,
        )
    )
    return membership is not None


async def resolve_server_org(server_id: str, db: AsyncSession) -> str | None:
    """Return the org_id (str) of an active server, or None if not found."""
    org_id = await db.scalar(
        select(Server.org_id).where(Server.id == server_id, Server.is_active == True)
    )
    return str(org_id) if org_id else None
