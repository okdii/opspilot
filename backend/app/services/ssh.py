"""
SSH executor — the single channel for everything OpsPilot does on a remote server.

Used by:
  - Phase 1: server onboarding (install Telegraf + Fluent Bit, write configs)
  - Phase 1: agent re-deploy
  - Phase 12+: arbitrary remote actions (run command, push config, restart service)

Design:
  - asyncssh-based — non-blocking, plays nice with FastAPI's event loop
  - Credentials decrypted from the Server row on demand, never logged or returned
  - Session-scoped: one connection serves many commands (cheap re-use during onboarding)
  - Structured SSHResult — no string parsing required by callers
"""

import asyncio
import shlex
from dataclasses import dataclass
from time import perf_counter
from typing import Self

import asyncssh

from app.core.crypto import decrypt
from app.models.server import Server


CONNECT_TIMEOUT_SEC = 15
DEFAULT_CMD_TIMEOUT_SEC = 30


@dataclass(frozen=True)
class SSHResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class SSHError(Exception):
    """Base class for all SSH executor failures."""


class SSHConnectionError(SSHError):
    """Network reach / handshake failure (timeout, refused, unreachable)."""


class SSHAuthError(SSHError):
    """Credentials rejected by the remote server."""


class SSHTimeoutError(SSHError):
    """Command did not complete within the requested timeout."""


class SSHCommandError(SSHError):
    """Non-zero exit when raise_on_error=True was requested."""

    def __init__(self, result: SSHResult, command: str) -> None:
        self.result = result
        self.command = command
        # Truncate stderr in the exception message — full stderr available on .result
        stderr_preview = (result.stderr or "").strip().splitlines()
        snippet = stderr_preview[-1] if stderr_preview else ""
        super().__init__(f"exit {result.exit_code}: {command} — {snippet}")


def _connect_options(server: Server) -> dict:
    """Build asyncssh.connect kwargs from a Server row."""
    opts: dict = {
        "host": server.host,
        "port": server.ssh_port,
        "username": server.ssh_user,
        # TOFU mode — we don't pin host keys in v1. To add later: store known_hosts
        # per server row and switch to strict mode here.
        "known_hosts": None,
    }
    if server.ssh_auth_type == "key":
        if not server.ssh_key_encrypted:
            raise SSHAuthError("Server has auth_type=key but no key stored")
        key_pem = decrypt(server.ssh_key_encrypted)
        opts["client_keys"] = [asyncssh.import_private_key(key_pem)]
    elif server.ssh_auth_type == "password":
        if not server.ssh_password_encrypted:
            raise SSHAuthError("Server has auth_type=password but no password stored")
        opts["password"] = decrypt(server.ssh_password_encrypted)
    else:
        raise SSHAuthError(f"Unknown ssh_auth_type: {server.ssh_auth_type}")
    return opts


class SSHSession:
    """
    Reusable SSH session for a single server.

    Usage:
        async with SSHSession(server) as s:
            r1 = await s.run("uname -r")
            r2 = await s.run("systemctl restart telegraf", sudo=True, raise_on_error=True)
            await s.upload("contents...", "/etc/telegraf/telegraf.conf", sudo=True)

    All commands share the same TCP connection — cheaper than re-handshaking per command.
    """

    def __init__(self, server: Server) -> None:
        self.server = server
        self._conn: asyncssh.SSHClientConnection | None = None

    async def __aenter__(self) -> Self:
        try:
            self._conn = await asyncio.wait_for(
                asyncssh.connect(**_connect_options(self.server)),
                timeout=CONNECT_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError as e:
            raise SSHConnectionError(
                f"Connection timed out after {CONNECT_TIMEOUT_SEC}s: "
                f"{self.server.host}:{self.server.ssh_port}"
            ) from e
        except asyncssh.PermissionDenied as e:
            raise SSHAuthError(
                f"Authentication failed for {self.server.ssh_user}@{self.server.host}"
            ) from e
        except (OSError, asyncssh.Error) as e:
            raise SSHConnectionError(f"Could not connect to {self.server.host}: {e}") from e
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._conn is not None:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None

    async def run(
        self,
        command: str,
        *,
        timeout: int = DEFAULT_CMD_TIMEOUT_SEC,
        sudo: bool = False,
        raise_on_error: bool = False,
    ) -> SSHResult:
        """
        Execute `command` and return its result.

        sudo=True wraps with `sudo -n` (non-interactive — requires NOPASSWD).
        raise_on_error=True raises SSHCommandError on non-zero exit.
        """
        if self._conn is None:
            raise SSHError("Session not opened — use 'async with SSHSession(...)'")

        # sudo -n bash -c '...' so the entire command (including pipes/&& chains)
        # runs as root, not just the first token.
        full = f"sudo -n bash -c {shlex.quote(command)}" if sudo else command
        start = perf_counter()
        try:
            result = await asyncio.wait_for(self._conn.run(full, check=False), timeout=timeout)
        except asyncio.TimeoutError as e:
            raise SSHTimeoutError(f"Command timed out after {timeout}s: {command}") from e

        ssh_result = SSHResult(
            exit_code=result.exit_status if result.exit_status is not None else -1,
            stdout=result.stdout if isinstance(result.stdout, str) else "",
            stderr=result.stderr if isinstance(result.stderr, str) else "",
            duration_ms=int((perf_counter() - start) * 1000),
        )
        if raise_on_error and not ssh_result.ok:
            raise SSHCommandError(ssh_result, command)
        return ssh_result

    async def run_action(
        self,
        verb: str,
        *args: str,
        input_text: str | None = None,
        timeout: int = DEFAULT_CMD_TIMEOUT_SEC,
    ) -> SSHResult:
        """Call sudo /usr/local/bin/opspilot-action <verb> [args] directly.

        Unlike run(sudo=True) which wraps everything in `sudo bash -c '...'`,
        this pins the sudoers entry to a single allow-listed script. A stolen
        SSH key can only call defined verbs, not arbitrary root commands.

        input_text is piped to stdin — used by restore_authorized_keys to pass
        the base64 backup without hitting shell ARG_MAX limits.
        """
        if self._conn is None:
            raise SSHError("Session not opened — use 'async with SSHSession(...)'")
        parts = ["sudo", "-n", "/usr/local/bin/opspilot-action", shlex.quote(verb)]
        parts += [shlex.quote(a) for a in args]
        cmd = " ".join(parts)
        start = perf_counter()
        try:
            result = await asyncio.wait_for(
                self._conn.run(cmd, check=False, input=input_text),
                timeout=timeout,
            )
        except asyncio.TimeoutError as e:
            raise SSHTimeoutError(f"run_action timed out after {timeout}s: {verb}") from e
        return SSHResult(
            exit_code=result.exit_status if result.exit_status is not None else -1,
            stdout=result.stdout if isinstance(result.stdout, str) else "",
            stderr=result.stderr if isinstance(result.stderr, str) else "",
            duration_ms=int((perf_counter() - start) * 1000),
        )

    async def upload(
        self,
        content: str,
        remote_path: str,
        *,
        mode: int = 0o644,
        owner: str | None = None,
        sudo: bool = False,
    ) -> None:
        """
        Upload `content` to `remote_path`.

        For paths the SSH user can write directly: writes via SFTP, then chmods.
        For paths needing root: stages in /tmp, then moves with sudo.
        """
        if self._conn is None:
            raise SSHError("Session not opened")

        # Stage to a tmp file the user can write to
        import secrets
        token = secrets.token_hex(8)
        staging = f"/tmp/.opspilot_{token}"

        async with self._conn.start_sftp_client() as sftp:
            async with sftp.open(staging, "w") as f:
                await f.write(content)

        # Move into place (sudo if needed) and set permissions
        cmd_parts = [f"mv {staging} {remote_path}", f"chmod {mode:o} {remote_path}"]
        if owner:
            cmd_parts.append(f"chown {owner} {remote_path}")
        cmd = " && ".join(cmd_parts)
        await self.run(cmd, sudo=sudo, raise_on_error=True)


# ── One-shot convenience functions ────────────────────────────────────────────

async def execute(server: Server, command: str, **kwargs) -> SSHResult:
    """Run a single command and disconnect. Use SSHSession for multiple commands."""
    async with SSHSession(server) as s:
        return await s.run(command, **kwargs)


async def test_connection(server: Server) -> SSHResult:
    """Smoke-test SSH access. Runs `whoami` — useful pre-onboarding."""
    return await execute(server, "whoami", timeout=10)
