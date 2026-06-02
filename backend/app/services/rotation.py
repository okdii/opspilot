"""opspilot_writer database password rotation.

Rotates the opspilot_writer PostgreSQL password, persists it (encrypted) to the
Settings row, then re-deploys agent configs to every active server and restarts
the agents. Progress is tracked in-memory and exposed via short polling
(GET /api/settings/rotation/{id}); a Phase 2 swap to WebSocket fan-out would
touch only the transport, not this logic.

Architecture note: in the current HTTP-ingest design agents authenticate to the
backend with a per-server bearer token, not this PostgreSQL credential. Rotation
still re-deploys/restarts agents per spec §8 so the operation is observable and
the credential stays in sync for any future direct-write path.
"""
import asyncio
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select, text

from app.core import crypto
from app.database import AsyncSessionLocal, engine
from app.models.other import Settings
from app.models.server import Server
from app.services import onboarding as onboarding_service


@dataclass
class ServerProgress:
    server_id: str
    server_name: str
    status: str = "pending"  # pending | deploying | ok | error
    message: str = "Waiting"


@dataclass
class Rotation:
    rotation_id: str
    servers: dict[str, ServerProgress] = field(default_factory=dict)

    @property
    def done(self) -> bool:
        return all(s.status in ("ok", "error") for s in self.servers.values())


_rotations: dict[str, Rotation] = {}


def get(rotation_id: str) -> Rotation | None:
    return _rotations.get(rotation_id)


async def start(new_password: str) -> tuple[str, int]:
    rotation_id = str(uuid.uuid4())

    async with AsyncSessionLocal() as db:
        active = (await db.scalars(select(Server).where(Server.is_active == True))).all()  # noqa: E712
        rotation = Rotation(
            rotation_id=rotation_id,
            servers={str(s.id): ServerProgress(str(s.id), s.name) for s in active},
        )
        _rotations[rotation_id] = rotation

        # 1) ALTER USER on PostgreSQL. DDL can't bind the password literal, so we
        # escape single quotes (the schema already forbids spaces and enforces len>=16).
        escaped = new_password.replace("'", "''")
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(text(f"ALTER USER opspilot_writer PASSWORD '{escaped}'"))

        # 2) Persist the rotated password (encrypted) to Settings.
        s = await db.scalar(select(Settings).where(Settings.id == 1))
        if s is None:
            s = Settings(id=1)
            db.add(s)
        s.writer_password_encrypted = crypto.encrypt(new_password)
        await db.commit()

    asyncio.create_task(_run(rotation_id))
    return rotation_id, len(rotation.servers)


async def _run(rotation_id: str) -> None:
    rotation = _rotations[rotation_id]
    for server_id in list(rotation.servers.keys()):
        await _redeploy_one(rotation, server_id)


async def _redeploy_one(rotation: Rotation, server_id: str) -> None:
    prog = rotation.servers[server_id]
    prog.status, prog.message = "deploying", "Re-deploying..."
    try:
        ok = onboarding_service.schedule(server_id, redeploy_only=True)
        if not ok:
            prog.status, prog.message = "error", "A deploy is already running for this server."
            return
        await _await_redeploy(server_id)
        prog.status, prog.message = "ok", "Updated successfully"
    except Exception as e:  # noqa: BLE001 - surface any failure to the progress panel
        prog.status, prog.message = "error", str(e)


async def _await_redeploy(server_id: str, timeout: float = 120.0) -> None:
    """Wait until the scheduled onboarding job for this server finishes."""
    elapsed = 0.0
    # give schedule() a moment to register the running task
    await asyncio.sleep(0.5)
    while elapsed < timeout:
        if not onboarding_service.is_running(server_id):
            return
        await asyncio.sleep(2.0)
        elapsed += 2.0
    raise TimeoutError("Re-deploy timed out.")


async def retry(rotation_id: str, server_id: str) -> None:
    rotation = _rotations.get(rotation_id)
    if rotation and server_id in rotation.servers:
        await _redeploy_one(rotation, server_id)
