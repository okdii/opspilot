"""On-demand full process snapshot via SSH `top -bn2` (instantaneous CPU).
No storage. 5s per-server cache + single-flight lock prevent an SSH stampede."""
import asyncio
import time
from datetime import datetime, timezone

from app.models.server import Server
from app.services.ssh import SSHSession

_CACHE_TTL = 5.0
_cache: dict[str, tuple[float, dict]] = {}
_locks: dict[str, asyncio.Lock] = {}
_TOP_CMD = "top -bn2 -d0.3 -w512"


def _parse_last_iteration(stdout: str) -> list[dict]:
    procs: list[dict] = []
    lines = stdout.splitlines()
    last_header = -1
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("PID"):
            last_header = i
    if last_header < 0:
        return procs
    for ln in lines[last_header + 1:]:
        parts = ln.split(None, 11)  # COMMAND may contain spaces → keep last field whole
        if len(parts) < 12 or not parts[0].isdigit():
            continue
        try:
            procs.append({
                "pid": int(parts[0]), "user": parts[1],
                "cpu_pct": float(parts[8].replace(",", ".")),
                "mem_pct": float(parts[9].replace(",", ".")),
                "name": parts[11].strip(),
            })
        except (ValueError, IndexError):
            continue
    return procs


async def _collect(server: Server) -> dict:
    async with SSHSession(server) as ssh:
        res = await ssh.run(_TOP_CMD, timeout=10)
    procs = _parse_last_iteration(res.stdout)
    procs.sort(key=lambda p: p["cpu_pct"], reverse=True)
    return {
        "reachable": True,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "processes": procs,
        "top_cpu": procs[:10],
        "top_mem": sorted(procs, key=lambda p: p["mem_pct"], reverse=True)[:10],
    }


async def get_snapshot(server: Server) -> dict:
    sid = str(server.id)
    cached = _cache.get(sid)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL:
        return cached[1]
    lock = _locks.setdefault(sid, asyncio.Lock())
    async with lock:
        cached = _cache.get(sid)
        if cached and time.monotonic() - cached[0] < _CACHE_TTL:
            return cached[1]
        try:
            payload = await _collect(server)
        except Exception:
            payload = {"reachable": False, "collected_at": None,
                       "processes": [], "top_cpu": [], "top_mem": []}
        _cache[sid] = (time.monotonic(), payload)
        return payload
