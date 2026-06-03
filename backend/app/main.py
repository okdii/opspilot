import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.core.rate_limit import limiter
from app.jobs.scheduler import maintenance_expiry, scheduler, session_cleanup, ticket_sweep
from app.routers.auth import invite_router, router as auth_router, ws_router
from app.routers.ingest import router as ingest_router
from app.routers.organizations import router as org_router
from app.routers.servers import router as server_router
from app.routers.dashboard import router as dashboard_router
from app.routers.metrics import router as metrics_router
from app.routers.maintenance import router as maintenance_router
from app.routers.settings import router as settings_router
from app.routers.sessions import router as sessions_router
from app.routers.team import router as team_router
from app.routers.setup import router as setup_router
from app.routers.logs import router as logs_router
from app.ws.live_bus import live_bus
from app.ws.authz import can_access_org, resolve_server_org
from app.ws.manager import ws_manager
from app.ws.tickets import ticket_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Register background jobs
    scheduler.add_job(session_cleanup, "cron", hour=3, minute=0, id="session_cleanup", replace_existing=True)
    scheduler.add_job(ticket_sweep, "interval", seconds=60, id="ticket_sweep", replace_existing=True)
    scheduler.add_job(maintenance_expiry, "interval", seconds=60, id="maintenance_expiry", replace_existing=True)
    scheduler.start()
    flush_task = asyncio.create_task(live_bus.flush_loop())
    yield
    flush_task.cancel()
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="OpsPilot API",
    docs_url="/api/docs" if settings.debug else None,
    redoc_url=None,
    lifespan=lifespan,
)

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS — allow same-origin + configured base_url
origins = ["http://localhost", "http://localhost:5173"]
if settings.opspilot_base_url:
    origins.append(settings.opspilot_base_url.rstrip("/"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response


# Routers
app.include_router(setup_router)
app.include_router(auth_router)
app.include_router(ws_router)
app.include_router(invite_router)
app.include_router(org_router)
app.include_router(server_router)
app.include_router(metrics_router)
app.include_router(maintenance_router)
app.include_router(dashboard_router)
app.include_router(ingest_router)
app.include_router(logs_router)
app.include_router(settings_router)
app.include_router(sessions_router)
app.include_router(team_router)


@app.get("/api/health")
async def health():
    return {"ok": True}


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, ticket: str | None = None):
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.user import User

    if not ticket:
        await ws.close(code=4001)
        return

    user_id = ticket_store.consume(ticket)
    if not user_id:
        await ws.close(code=4001)
        return

    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.id == user_id))
        if not user:
            await ws.close(code=4001)
            return
        user_role = user.role

    await ws.accept()
    conn = await ws_manager.connect(ws, user_id, user_role)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            action = msg.get("action")

            if action == "subscribe_org":
                org_id = msg.get("org_id")
                if org_id:
                    async with AsyncSessionLocal() as db:
                        allowed = await can_access_org(user_role, user_id, org_id, db)
                    if allowed:
                        conn.subscribed_orgs.add(org_id)
                    else:
                        await ws.send_text(json.dumps({"error": "forbidden", "channel": f"org:{org_id}"}))

            elif action == "unsubscribe_org":
                org_id = msg.get("org_id")
                if org_id:
                    conn.subscribed_orgs.discard(org_id)

            elif action == "subscribe":
                server_id = msg.get("server_id")
                if server_id:
                    async with AsyncSessionLocal() as db:
                        org_id = await resolve_server_org(server_id, db)
                        allowed = org_id is not None and await can_access_org(user_role, user_id, org_id, db)
                    if allowed:
                        conn.subscribed_servers.add(server_id)
                    else:
                        await ws.send_text(json.dumps({"error": "forbidden", "channel": f"server_metrics:{server_id}"}))

            elif action == "subscribe_onboarding":
                server_id = msg.get("server_id")
                if server_id:
                    conn.subscribed_onboardings.add(server_id)

            elif action == "unsubscribe_onboarding":
                server_id = msg.get("server_id")
                if server_id:
                    conn.subscribed_onboardings.discard(server_id)

            elif action == "subscribe_rotation":
                if user_role == "admin":
                    conn.rotation_sub = True
                else:
                    await ws.send_text(json.dumps({"event": "error", "code": "forbidden"}))

            elif action == "unsubscribe":
                server_id = msg.get("server_id")
                if server_id:
                    conn.subscribed_servers.discard(server_id)

            elif action == "subscribe_logs":
                server_id = msg.get("server_id")
                if server_id:
                    async with AsyncSessionLocal() as db:
                        org_id = await resolve_server_org(server_id, db)
                        allowed = org_id is not None and await can_access_org(user_role, user_id, org_id, db)
                    if allowed:
                        conn.subscribed_servers.add(server_id)
                    else:
                        await ws.send_text(json.dumps({"error": "forbidden", "channel": f"server_logs:{server_id}"}))

            elif action == "unsubscribe_logs":
                server_id = msg.get("server_id")
                if server_id:
                    conn.subscribed_servers.discard(server_id)

    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(conn)
