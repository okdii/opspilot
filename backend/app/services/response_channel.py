"""Allow-listed remediation verbs (Security Auto-Response, Part 2).

The ONLY module permitted to run privileged commands on a monitored server.
Each public coroutine is a fixed verb with typed, validated arguments — there is
no path that interpolates a caller-supplied command string into the shell. Args
are validated (IP via ipaddress, path must resolve under a known web root, pid
must be a positive int) BEFORE any shell call.

All commands are routed through `ssh.run_action()` which calls
`sudo /usr/local/bin/opspilot-action <verb> [args]` DIRECTLY — not via
`sudo bash -c`. This means the sudoers entry on the target can be pinned to
that one script, so a stolen SSH key cannot run arbitrary root commands.

Every executing verb returns a `reversal` dict the ledger stores so the
matching undo verb can reverse it.
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

# MariaDB root defaults file on the server (project rule; never echoed to logs).
DB_CREDENTIALS_FILE = "/root/.mdsb-db-credentials"

# IP ranges that must never be blocked — blocking them would cause self-inflicted
# outages (loopback, private LANs, link-local). The wrapper script enforces the
# same check at the OS level as a second wall.
_FORBIDDEN_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


class ResponseError(Exception):
    """A verb failed validation or execution. Caller records status='failed'."""


def _validate_ip(ip: str) -> str:
    """Return canonical IP string or raise ResponseError. Rejects shell injection
    and private/loopback addresses that would cause self-inflicted outages."""
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError as e:
        raise ResponseError(f"invalid IP {ip!r}") from e
    for net in _FORBIDDEN_NETWORKS:
        if addr in net:
            raise ResponseError(
                f"refusing to block {ip!r}: private/loopback addresses must not be blocked "
                f"(would cause self-inflicted outage)"
            )
    return str(addr)


def _parse_ip(ip: str) -> str:
    """Format-only IP parse (no range check). Used for unblock where the IP
    was already validated at block time and may need to be reversed."""
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
    """Insert a DROP rule for `ip`. Reversible via unblock_ip; TTL-expired by
    the scheduler. Returns reversal data (the ip + iptables bin used)."""
    ip = _validate_ip(ip)  # raises for private/loopback ranges
    binary = _iptables_bin(ip)
    logger.info("block_ip server=%s ip=%s", server.id, ip)
    async with SSHSession(server) as ssh:
        r = await ssh.run_action("block_ip", ip, timeout=20)
    if not r.ok:
        raise ResponseError(f"block_ip failed: {r.stderr or r.stdout}")
    return {"verb": "block_ip", "ip": ip, "binary": binary}


async def unblock_ip(server: Server, ip: str) -> None:
    ip = _parse_ip(ip)  # format-only; range check not needed for reversal
    binary = _iptables_bin(ip)  # noqa: F841 — kept for symmetry / future logging
    logger.info("unblock_ip server=%s ip=%s", server.id, ip)
    async with SSHSession(server) as ssh:
        await ssh.run_action("unblock_ip", ip, timeout=20)


async def quarantine_file(server: Server, path: str) -> dict:
    """chmod 000 + move the file to QUARANTINE_DIR (never delete). Returns the
    original path + quarantine path so restore_file can reverse it."""
    path = _validate_path(path)
    logger.info("quarantine_file server=%s path=%s", server.id, path)
    async with SSHSession(server) as ssh:
        r = await ssh.run_action("quarantine_file", path, timeout=30)
    out = (r.stdout or "").strip()
    if not r.ok or out == "MISSING" or not out:
        raise ResponseError(f"quarantine failed for {path}: {r.stderr or out}")
    return {"verb": "quarantine_file", "original": path, "quarantined": out}


async def restore_file(server: Server, reversal: dict) -> None:
    original = _validate_path(reversal["original"])
    quarantined = reversal["quarantined"]
    if not quarantined.startswith(QUARANTINE_DIR + "/") or ".." in quarantined:
        raise ResponseError("bad quarantine path in reversal")
    logger.info("restore_file server=%s original=%s", server.id, original)
    async with SSHSession(server) as ssh:
        r = await ssh.run_action("restore_file", quarantined, original, timeout=30)
    if not r.ok:
        raise ResponseError(f"restore failed: {r.stderr or r.stdout}")


async def kill_pid(server: Server, pid) -> dict:
    """SIGKILL a pid. NOT reversible (no undo)."""
    p = _validate_pid(pid)
    logger.info("kill_pid server=%s pid=%s", server.id, p)
    async with SSHSession(server) as ssh:
        r = await ssh.run_action("kill_pid", str(p), timeout=15)
    if not r.ok:
        raise ResponseError(f"kill_pid failed: {r.stderr or r.stdout}")
    return {"verb": "kill_pid", "pid": p}


# ── Tier 2 verbs (human-approved) ──────────────────────────────────────────
async def revert_authorized_keys(server: Server, ssh_user: str) -> dict:
    """Back up authorized_keys, then remove ONLY the last-appended key line (the
    attacker's freshly-added key). Full backup stored for restore via undo.
    Refuses (SINGLE) rather than emptying a file that has <=1 key line."""
    user = ssh_user.strip()
    if not user.replace("-", "").replace("_", "").isalnum():
        raise ResponseError(f"invalid user {ssh_user!r}")
    logger.info("revert_authorized_keys server=%s user=%s", server.id, user)
    async with SSHSession(server) as ssh:
        r = await ssh.run_action("revert_authorized_keys", user, timeout=20)
    out = (r.stdout or "").strip()
    if not r.ok or out in ("MISSING", "SINGLE") or not out:
        raise ResponseError(
            f"revert_authorized_keys failed ({out or r.stderr}): {r.stderr or out}"
        )
    ak = "/root/.ssh/authorized_keys" if user == "root" else f"/home/{user}/.ssh/authorized_keys"
    return {"verb": "revert_authorized_keys", "path": ak, "backup_b64": out}


async def restore_authorized_keys(server: Server, reversal: dict) -> None:
    ak = reversal["path"]
    if not (ak.endswith("/.ssh/authorized_keys") and ak.startswith(("/root/", "/home/"))) or ".." in ak:
        raise ResponseError("bad authorized_keys path in reversal")
    user = "root" if ak.startswith("/root/") else ak.split("/")[2]
    b64 = reversal["backup_b64"]
    logger.info("restore_authorized_keys server=%s path=%s", server.id, ak)
    # b64 is passed via stdin to avoid hitting shell ARG_MAX on large key files.
    async with SSHSession(server) as ssh:
        r = await ssh.run_action("restore_authorized_keys", user, input_text=b64, timeout=20)
    if not r.ok:
        raise ResponseError(f"restore_authorized_keys failed: {r.stderr or r.stdout}")


async def disable_db_user(server: Server, db_user: str) -> dict:
    """ACCOUNT LOCK a MariaDB user (reversible via enable_db_user). Uses the
    server's root defaults file (/root/.mdsb-db-credentials per project rule)."""
    u = db_user.strip().strip("'\"`")
    if not u or not all(c.isalnum() or c in "_-." for c in u):
        raise ResponseError(f"invalid db user {db_user!r}")
    logger.info("disable_db_user server=%s db_user=%s", server.id, u)
    async with SSHSession(server) as ssh:
        r = await ssh.run_action("disable_db_user", u, timeout=20)
    if not r.ok:
        raise ResponseError(f"disable_db_user failed: {r.stderr or r.stdout}")
    return {"verb": "disable_db_user", "db_user": u}


async def enable_db_user(server: Server, reversal: dict) -> None:
    u = reversal["db_user"]
    if not u or not all(c.isalnum() or c in "_-." for c in u):
        raise ResponseError(f"invalid db_user in reversal: {u!r}")
    logger.info("enable_db_user server=%s db_user=%s", server.id, u)
    async with SSHSession(server) as ssh:
        r = await ssh.run_action("enable_db_user", u, timeout=20)
    if not r.ok:
        raise ResponseError(f"enable_db_user failed: {r.stderr or r.stdout}")
