from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt, encrypt
from app.database import get_db
from app.deps import AdminUser, CurrentUser
from app.models.organization import Organization
from app.models.other import Alert
from app.models.server import OnboardingLog, Server
from app.models.user import UserOrganization
from app.schemas.onboarding import OnboardingResponse, OnboardingStepOut
from app.schemas.server import ServerCreate, ServerOut, ServerUpdate
from app.services import onboarding as onboarding_service
from app.services.ssh import SSHAuthError, SSHConnectionError, SSHError, test_connection

router = APIRouter(tags=["servers"])

_ONLINE_THRESHOLD = timedelta(minutes=2)


def _compute_status(server: Server) -> str:
    if server.os_distro is None:
        return "pending"
    if server.last_seen_at is None:
        return "offline"
    age = datetime.now(timezone.utc) - server.last_seen_at.replace(tzinfo=timezone.utc)
    return "online" if age <= _ONLINE_THRESHOLD else "offline"


async def _active_alert_count(server_id: str, db: AsyncSession) -> int:
    count = await db.scalar(
        select(func.count()).select_from(Alert).where(
            Alert.server_id == server_id,
            Alert.state.in_(["firing", "acknowledged", "snoozed"]),
        )
    )
    return count or 0


async def _server_to_out(server: Server, db: AsyncSession) -> ServerOut:
    return ServerOut(
        id=str(server.id),
        org_id=str(server.org_id),
        name=server.name,
        host=server.host,
        ssh_port=server.ssh_port,
        ssh_user=server.ssh_user,
        ssh_auth_type=server.ssh_auth_type,
        os_distro=server.os_distro,
        kernel_version=server.kernel_version,
        tags=server.tags or [],
        is_active=server.is_active,
        status=_compute_status(server),
        last_seen_at=server.last_seen_at,
        active_alert_count=await _active_alert_count(str(server.id), db),
        created_at=server.created_at,
    )


async def _assert_org_access(org_id: str, user, db: AsyncSession) -> None:
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


@router.get("/api/organizations/{org_id}/servers")
async def list_servers(org_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_org_access(org_id, user, db)
    result = await db.execute(
        select(Server).where(Server.org_id == org_id, Server.is_active == True).order_by(Server.name)
    )
    servers = result.scalars().all()
    return [await _server_to_out(s, db) for s in servers]


@router.get("/api/servers")
async def list_all_servers(user: AdminUser, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Server).where(Server.is_active == True).order_by(Server.name))
    servers = result.scalars().all()
    return [await _server_to_out(s, db) for s in servers]


@router.post("/api/organizations/{org_id}/servers", status_code=201)
async def add_server(org_id: str, body: ServerCreate, user: AdminUser, db: AsyncSession = Depends(get_db)):
    await _assert_org_access(org_id, user, db)

    if body.ssh_auth_type == "key":
        if not body.ssh_key:
            raise HTTPException(422, detail={"error": "validation_error", "message": "SSH private key is required."})
        if not body.ssh_key.strip().startswith("-----BEGIN"):
            raise HTTPException(422, detail={"error": "validation_error", "message": "Enter a valid PEM private key."})
        key_enc = encrypt(body.ssh_key)
        pw_enc = None
    else:
        if not body.ssh_password:
            raise HTTPException(422, detail={"error": "validation_error", "message": "SSH password is required."})
        key_enc = None
        pw_enc = encrypt(body.ssh_password)

    server = Server(
        org_id=org_id,
        name=body.name,
        host=body.host,
        ssh_port=body.ssh_port,
        ssh_user=body.ssh_user,
        ssh_auth_type=body.ssh_auth_type,
        ssh_key_encrypted=key_enc,
        ssh_password_encrypted=pw_enc,
        tags=body.tags or [],
    )
    db.add(server)
    await db.commit()
    await db.refresh(server)

    # Schedule onboarding (spec 03 §4.1) — runs in the FastAPI event loop, doesn't block
    onboarding_service.schedule(str(server.id))

    return await _server_to_out(server, db)


@router.get("/api/servers/{server_id}")
async def get_server(server_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    server = await _get_accessible_server(server_id, user, db)
    return await _server_to_out(server, db)


@router.patch("/api/servers/{server_id}")
async def update_server(server_id: str, body: ServerUpdate, user: AdminUser, db: AsyncSession = Depends(get_db)):
    server = await db.scalar(select(Server).where(Server.id == server_id, Server.is_active == True))
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})

    creds_changed = False

    if body.name is not None:
        server.name = body.name
    if body.host is not None:
        server.host = body.host
    if body.ssh_port is not None:
        server.ssh_port = body.ssh_port
    if body.ssh_user is not None:
        server.ssh_user = body.ssh_user
    if body.ssh_auth_type is not None:
        server.ssh_auth_type = body.ssh_auth_type
    if body.ssh_key is not None:
        server.ssh_key_encrypted = encrypt(body.ssh_key)
        server.ssh_password_encrypted = None
        creds_changed = True
    if body.ssh_password is not None:
        server.ssh_password_encrypted = encrypt(body.ssh_password)
        server.ssh_key_encrypted = None
        creds_changed = True
    if body.tags is not None:
        server.tags = body.tags

    await db.commit()
    await db.refresh(server)

    # If creds changed, queue re-deploy (Phase 3)

    return await _server_to_out(server, db)


@router.delete("/api/servers/{server_id}", status_code=204)
async def delete_server(server_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)):
    server = await db.scalar(select(Server).where(Server.id == server_id, Server.is_active == True))
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})

    server.is_active = False
    # Resolve active alerts for this server
    active_alerts = await db.execute(
        select(Alert).where(Alert.server_id == server_id, Alert.state.in_(["firing", "acknowledged", "snoozed"]))
    )
    for alert in active_alerts.scalars().all():
        alert.state = "resolved"
        alert.resolved_at = datetime.now(timezone.utc)

    await db.commit()
    return None


@router.post("/api/servers/{server_id}/redeploy", status_code=202)
async def redeploy_agents(server_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)):
    server = await db.scalar(select(Server).where(Server.id == server_id, Server.is_active == True))
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})

    if not onboarding_service.schedule(str(server.id), redeploy_only=True):
        raise HTTPException(409, detail={"error": "in_progress", "message": "Onboarding already in progress for this server."})
    return {"ok": True, "message": "Re-deploy queued."}


@router.post("/api/servers/{server_id}/onboard", status_code=202)
async def start_onboarding(server_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)):
    """Start or retry onboarding (spec 03 §10)."""
    server = await db.scalar(select(Server).where(Server.id == server_id, Server.is_active == True))
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})

    if not onboarding_service.schedule(str(server.id), redeploy_only=False):
        raise HTTPException(409, detail={"error": "in_progress", "message": "Onboarding already in progress for this server."})
    return {"ok": True}


@router.get("/api/servers/{server_id}/onboarding", response_model=OnboardingResponse)
async def get_onboarding(server_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    server = await _get_accessible_server(server_id, user, db)

    result = await db.execute(
        select(OnboardingLog)
        .where(OnboardingLog.server_id == server.id)
        .order_by(OnboardingLog.created_at)
    )
    logs = list(result.scalars().all())
    if not logs:
        raise HTTPException(404, detail={"error": "no_onboarding", "message": "No onboarding has run for this server."})

    # Determine outcome
    failed = [l for l in logs if l.status == "failed"]
    running = [l for l in logs if l.status == "running"]
    last = logs[-1]
    if failed:
        outcome = "failed"
    elif running:
        outcome = "running"
    elif last.step_number == 10 and last.status in ("done", "skipped"):
        outcome = "success"
    else:
        outcome = "running"

    started_at = logs[0].started_at or logs[0].created_at
    completed_at = None if outcome == "running" else logs[-1].created_at

    return OnboardingResponse(
        server_id=server.id,
        started_at=started_at,
        completed_at=completed_at,
        outcome=outcome,
        steps=[OnboardingStepOut.model_validate(l) for l in logs],
    )


@router.post("/api/servers/{server_id}/ssh-test")
async def ssh_test(server_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)):
    """Verify SSH credentials and connectivity. Returns the remote `whoami` output."""
    server = await db.scalar(select(Server).where(Server.id == server_id, Server.is_active == True))
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})

    try:
        result = await test_connection(server)
    except SSHAuthError as e:
        raise HTTPException(400, detail={"error": "ssh_auth_failed", "message": str(e)})
    except SSHConnectionError as e:
        raise HTTPException(400, detail={"error": "ssh_connection_failed", "message": str(e)})
    except SSHError as e:
        raise HTTPException(500, detail={"error": "ssh_error", "message": str(e)})

    return {
        "ok": result.ok,
        "exit_code": result.exit_code,
        "stdout": result.stdout.strip(),
        "duration_ms": result.duration_ms,
    }


async def _get_accessible_server(server_id: str, user, db: AsyncSession) -> Server:
    server = await db.scalar(select(Server).where(Server.id == server_id, Server.is_active == True))
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})
    if user.role != "admin":
        membership = await db.scalar(
            select(UserOrganization).where(
                UserOrganization.user_id == user.id,
                UserOrganization.org_id == server.org_id,
            )
        )
        if not membership:
            raise HTTPException(403, detail={"error": "forbidden", "message": "Access denied."})
    return server


async def _assert_server_access(server_id: str, user, db: AsyncSession) -> Server:
    """Shared guard for server-detail routes (metrics, maintenance).
    Reuses the org-membership rule and returns the server row."""
    return await _get_accessible_server(server_id, user, db)
