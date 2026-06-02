"""WebSocket connection manager with channel-based fanout."""
import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket


@dataclass
class Connection:
    websocket: WebSocket
    user_id: str
    user_role: str
    subscribed_orgs: set[str] = field(default_factory=set)
    subscribed_servers: set[str] = field(default_factory=set)
    subscribed_onboardings: set[str] = field(default_factory=set)
    rotation_sub: bool = False


class WSManager:
    def __init__(self) -> None:
        self._connections: list[Connection] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, user_id: str, user_role: str) -> Connection:
        conn = Connection(websocket=ws, user_id=user_id, user_role=user_role)
        async with self._lock:
            self._connections.append(conn)
        return conn

    async def disconnect(self, conn: Connection) -> None:
        async with self._lock:
            try:
                self._connections.remove(conn)
            except ValueError:
                pass

    async def broadcast_org(self, org_id: str, payload: dict) -> None:
        msg = json.dumps(payload)
        dead = []
        async with self._lock:
            targets = [c for c in self._connections if org_id in c.subscribed_orgs]
        for conn in targets:
            try:
                await conn.websocket.send_text(msg)
            except Exception:
                dead.append(conn)
        for conn in dead:
            await self.disconnect(conn)

    async def broadcast_server(self, server_id: str, payload: dict) -> None:
        msg = json.dumps(payload)
        dead = []
        async with self._lock:
            targets = [c for c in self._connections if server_id in c.subscribed_servers]
        for conn in targets:
            try:
                await conn.websocket.send_text(msg)
            except Exception:
                dead.append(conn)
        for conn in dead:
            await self.disconnect(conn)

    async def broadcast_onboarding(self, server_id: str, payload: dict) -> None:
        msg = json.dumps({"channel": f"onboarding:{server_id}", **payload})
        dead = []
        async with self._lock:
            targets = [c for c in self._connections if server_id in c.subscribed_onboardings]
        for conn in targets:
            try:
                await conn.websocket.send_text(msg)
            except Exception:
                dead.append(conn)
        for conn in dead:
            await self.disconnect(conn)

    async def broadcast_rotation(self, payload: dict) -> None:
        msg = json.dumps(payload)
        dead = []
        async with self._lock:
            targets = [c for c in self._connections if c.rotation_sub]
        for conn in targets:
            try:
                await conn.websocket.send_text(msg)
            except Exception:
                dead.append(conn)
        for conn in dead:
            await self.disconnect(conn)


ws_manager = WSManager()
