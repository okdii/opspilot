"""
Ingestion endpoints — Telegraf and Fluent Bit push here.

Auth: Bearer <ingestion_token>  (one per server, stored on Server.ingestion_token)
"""
import gzip
import hmac
import json
import zlib
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.server import Server
from app.services.ingestion import write_logs, write_metrics

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


async def _read_decoded_body(request: Request) -> bytes:
    """Read the raw request body, transparently decompressing when the agent
    set Content-Encoding. Telegraf (outputs.http content_encoding="gzip") and
    Fluent Bit both send gzip; without this the parser sees compressed bytes
    and silently writes zero rows."""
    raw = await request.body()
    encoding = request.headers.get("content-encoding", "").lower()
    if "gzip" in encoding or "x-gzip" in encoding:
        return gzip.decompress(raw)
    if "deflate" in encoding:
        return zlib.decompress(raw)
    return raw


async def _authenticated_server(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> Server:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, detail={"error": "missing_token", "message": "Bearer token required."})
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(401, detail={"error": "missing_token", "message": "Bearer token required."})

    # Constant-time scan to avoid timing-based token enumeration.
    # For 50 servers this is trivial; revisit if we ever scale beyond ~5k.
    result = await db.execute(select(Server).where(Server.is_active == True))
    for server in result.scalars().all():
        if hmac.compare_digest(token, str(server.ingestion_token)):
            return server
    raise HTTPException(401, detail={"error": "invalid_token", "message": "Invalid ingestion token."})


@router.post("/metrics")
async def ingest_metrics(
    request: Request,
    server: Annotated[Server, Depends(_authenticated_server)],
    db: AsyncSession = Depends(get_db),
):
    body = (await _read_decoded_body(request)).decode("utf-8", errors="replace")
    count = await write_metrics(server.id, body, db)

    # Update last_seen_at — this also flips server status from offline → online
    server.last_seen_at = datetime.now(timezone.utc)
    await db.commit()

    return {"ok": True, "rows": count}


@router.post("/logs")
async def ingest_logs(
    request: Request,
    server: Annotated[Server, Depends(_authenticated_server)],
    db: AsyncSession = Depends(get_db),
):
    try:
        payload = json.loads(await _read_decoded_body(request))
    except (json.JSONDecodeError, OSError, zlib.error):
        raise HTTPException(400, detail={"error": "bad_json", "message": "Body must be JSON."})

    records = payload if isinstance(payload, list) else [payload]
    count = await write_logs(server.id, records, db)
    return {"ok": True, "rows": count}
