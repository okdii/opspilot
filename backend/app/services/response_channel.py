"""Allow-listed remediation verbs (Security Auto-Response, Part 2).

The ONLY module permitted to run privileged commands on a monitored server.
Each public coroutine is a fixed verb with typed, validated arguments — there is
no path that interpolates a caller-supplied command string into the shell. Args
are validated (IP via ipaddress, path must resolve under a known web root, pid
must be a positive int) BEFORE any shell call. Every executing verb returns a
`reversal` dict the ledger stores so the matching undo verb can reverse it.
"""
from __future__ import annotations

import ipaddress
import logging
import shlex

from app.models.server import Server
from app.services.ssh import SSHSession

logger = logging.getLogger(__name__)

# Quarantine dir on the server (chmod-000 + moved files live here, never deleted).
QUARANTINE_DIR = "/var/opspilot-quarantine"

# Web roots a quarantine target must resolve under. Mirrors Part 1 detection dirs.
_WEB_ROOTS = ("/var/www", "/usr/share/nginx", "/srv/www", "/home")


class ResponseError(Exception):
    """A verb failed validation or execution. Caller records status='failed'."""


def _validate_ip(ip: str) -> str:
    """Return the canonical IP string, or raise ResponseError. Rejects anything
    that is not a single valid IPv4/IPv6 address (blocks shell injection)."""
    try:
        return str(ipaddress.ip_address(ip.strip()))
    except ValueError as e:
        raise ResponseError(f"invalid IP {ip!r}") from e


def _validate_pid(pid) -> int:
    try:
        p = int(str(pid).strip())
    except (TypeError, ValueError) as e:
        raise ResponseError(f"invalid pid {pid!r}") from e
    if p <= 1:
        raise ResponseError(f"refusing pid {p} (<=1)")
    return p


def _validate_path(path: str) -> str:
    """Path must be absolute, contain no '..', and sit under a known web root."""
    p = (path or "").strip()
    if not p.startswith("/") or ".." in p:
        raise ResponseError(f"unsafe path {path!r}")
    if not any(p.startswith(root + "/") for root in _WEB_ROOTS):
        raise ResponseError(f"path {path!r} not under a web root")
    return p


def _iptables_bin(ip: str) -> str:
    return "ip6tables" if ipaddress.ip_address(ip).version == 6 else "iptables"


# ── Tier 1 verbs ────────────────────────────────────────────────────────────
async def block_ip(server: Server, ip: str) -> dict:
    """Insert a DROP rule for `ip`. Reversible via unblock_ip; TTL-expired by the
    scheduler. Returns reversal data (the ip + iptables bin used)."""
    ip = _validate_ip(ip)
    binary = _iptables_bin(ip)
    cmd = f"{binary} -C INPUT -s {ip} -j DROP 2>/dev/null || {binary} -I INPUT -s {ip} -j DROP"
    async with SSHSession(server) as ssh:
        r = await ssh.run(cmd, sudo=True, timeout=20)
    if not r.ok:
        raise ResponseError(f"block_ip failed: {r.stderr or r.stdout}")
    return {"verb": "block_ip", "ip": ip, "binary": binary}


async def unblock_ip(server: Server, ip: str) -> None:
    ip = _validate_ip(ip)
    binary = _iptables_bin(ip)
    cmd = f"{binary} -D INPUT -s {ip} -j DROP 2>/dev/null || true"
    async with SSHSession(server) as ssh:
        await ssh.run(cmd, sudo=True, timeout=20)


async def quarantine_file(server: Server, path: str) -> dict:
    """chmod 000 + move the file to QUARANTINE_DIR (never delete). Returns the
    original path + quarantine path so restore_file can reverse it."""
    path = _validate_path(path)
    q = path  # mkdir + move with a timestamped name, recording the dest
    cmd = (
        f"set -e; mkdir -p {QUARANTINE_DIR}; "
        f"if [ -e {shlex.quote(path)} ]; then "
        f"  dest={QUARANTINE_DIR}/$(date +%s)_$(basename {shlex.quote(path)}); "
        f"  chmod 000 {shlex.quote(path)}; "
        f"  mv {shlex.quote(path)} \"$dest\"; "
        f"  echo \"$dest\"; "
        f"else echo MISSING; fi"
    )
    async with SSHSession(server) as ssh:
        r = await ssh.run(cmd, sudo=True, timeout=30)
    out = (r.stdout or "").strip()
    if not r.ok or out == "MISSING" or not out:
        raise ResponseError(f"quarantine failed for {path}: {r.stderr or out}")
    return {"verb": "quarantine_file", "original": path, "quarantined": out}


async def restore_file(server: Server, reversal: dict) -> None:
    original = _validate_path(reversal["original"])
    quarantined = reversal["quarantined"]
    if not quarantined.startswith(QUARANTINE_DIR + "/") or ".." in quarantined:
        raise ResponseError("bad quarantine path in reversal")
    cmd = (
        f"set -e; mv {shlex.quote(quarantined)} {shlex.quote(original)}; "
        f"chmod 644 {shlex.quote(original)}"
    )
    async with SSHSession(server) as ssh:
        r = await ssh.run(cmd, sudo=True, timeout=30)
    if not r.ok:
        raise ResponseError(f"restore failed: {r.stderr or r.stdout}")


async def kill_pid(server: Server, pid) -> dict:
    """SIGKILL a pid. NOT reversible (no undo)."""
    p = _validate_pid(pid)
    async with SSHSession(server) as ssh:
        r = await ssh.run(f"kill -9 {p}", sudo=True, timeout=15)
    if not r.ok:
        raise ResponseError(f"kill_pid failed: {r.stderr or r.stdout}")
    return {"verb": "kill_pid", "pid": p}


# ── Tier 2 verbs (human-approved) ──────────────────────────────────────────
async def revert_authorized_keys(server: Server, ssh_user: str) -> dict:
    """Back up authorized_keys, then remove ONLY the last-appended key line (the
    attacker's freshly-added key). Full backup stored for restore via undo."""
    user = ssh_user.strip()
    if not user.replace("-", "").replace("_", "").isalnum():
        raise ResponseError(f"invalid user {ssh_user!r}")
    home = "/root" if user == "root" else f"/home/{user}"
    ak = f"{home}/.ssh/authorized_keys"
    cmd = (
        f"set -e; f={shlex.quote(ak)}; "
        f"if [ ! -f \"$f\" ]; then echo MISSING; exit 0; fi; "
        f"backup=$(base64 -w0 \"$f\"); "          # capture full file
        f"head -n -1 \"$f\" > \"$f.opspilot\" || true; "  # drop last line
        f"mv \"$f.opspilot\" \"$f\"; "
        f"echo \"$backup\""
    )
    async with SSHSession(server) as ssh:
        r = await ssh.run(cmd, sudo=True, timeout=20)
    out = (r.stdout or "").strip()
    if not r.ok or out == "MISSING" or not out:
        raise ResponseError(f"revert_authorized_keys failed: {r.stderr or out}")
    return {"verb": "revert_authorized_keys", "path": ak, "backup_b64": out}


async def restore_authorized_keys(server: Server, reversal: dict) -> None:
    ak = reversal["path"]
    if "/.ssh/authorized_keys" not in ak or ".." in ak:
        raise ResponseError("bad authorized_keys path in reversal")
    b64 = reversal["backup_b64"]
    cmd = f"echo {shlex.quote(b64)} | base64 -d > {shlex.quote(ak)}; chmod 600 {shlex.quote(ak)}"
    async with SSHSession(server) as ssh:
        r = await ssh.run(cmd, sudo=True, timeout=20)
    if not r.ok:
        raise ResponseError(f"restore_authorized_keys failed: {r.stderr or r.stdout}")


async def disable_db_user(server: Server, db_user: str) -> dict:
    """ACCOUNT LOCK a MariaDB user (reversible via enable_db_user). Uses the
    server's root defaults file (/root/.mdsb-db-credentials per project rule)."""
    u = db_user.strip().strip("'\"`")
    if not u or not all(c.isalnum() or c in "_-." for c in u):
        raise ResponseError(f"invalid db user {db_user!r}")
    sql = f"ALTER USER '{u}'@'%' ACCOUNT LOCK;"
    cmd = f"mysql --defaults-extra-file=/root/.mdsb-db-credentials -e {shlex.quote(sql)}"
    async with SSHSession(server) as ssh:
        r = await ssh.run(cmd, sudo=True, timeout=20)
    if not r.ok:
        raise ResponseError(f"disable_db_user failed: {r.stderr or r.stdout}")
    return {"verb": "disable_db_user", "db_user": u}


async def enable_db_user(server: Server, reversal: dict) -> None:
    u = reversal["db_user"]
    sql = f"ALTER USER '{u}'@'%' ACCOUNT UNLOCK;"
    cmd = f"mysql --defaults-extra-file=/root/.mdsb-db-credentials -e {shlex.quote(sql)}"
    async with SSHSession(server) as ssh:
        r = await ssh.run(cmd, sudo=True, timeout=20)
    if not r.ok:
        raise ResponseError(f"enable_db_user failed: {r.stderr or r.stdout}")
