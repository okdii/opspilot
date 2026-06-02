"""In-process live fan-out bus for metric pushes.

write_metrics() publishes parsed push-rows here; a single background task
(flush_loop, started in the app lifespan) flushes each server's buffer every
500ms and fans the batch out over WebSocket. This module is the single seam to
swap for PostgreSQL LISTEN/NOTIFY if the backend is ever scaled to multiple
worker processes (see PRD §5.4.8)."""
import asyncio
import logging

from app.ws.manager import ws_manager

logger = logging.getLogger(__name__)

FLUSH_INTERVAL_SECONDS = 0.5


class LiveBus:
    def __init__(self) -> None:
        self._buffer: dict[str, list[dict]] = {}
        self._server_org: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def publish(self, server_id: str, org_id: str, rows: list[dict]) -> None:
        """Buffer push-rows for a server. Cheap; safe to call from the ingest path."""
        if not rows:
            return
        async with self._lock:
            self._server_org[server_id] = org_id
            self._buffer.setdefault(server_id, []).extend(rows)

    async def _drain(self) -> dict[str, list[dict]]:
        async with self._lock:
            batch = self._buffer
            self._buffer = {}
            return batch

    async def flush_once(self) -> None:
        batch = await self._drain()
        for server_id, rows in batch.items():
            if not rows:
                continue
            org_id = self._server_org.get(server_id, "")
            payload = {"channel": f"server_metrics:{server_id}", "rows": rows}
            await ws_manager.broadcast_metrics(server_id, org_id, payload)

    async def flush_loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
            try:
                await self.flush_once()
            except Exception:
                logger.exception("live_bus flush failed")


live_bus = LiveBus()
