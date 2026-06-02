"""
Server onboarding orchestrator — implements the 10-step flow from spec 03.

Steps:
  1. ssh_connect          (hard)   — open SSH + verify passwordless sudo
  2. detect_os            (hard)   — read /etc/os-release
  3. add_repos            (hard)   — InfluxData (Telegraf) + Fluent Bit
  4. install_telegraf     (hard)
  5. install_fluent_bit   (hard)
  6. configure_telegraf   (hard)   — render Jinja2 template, upload
  7. configure_fluent_bit (hard)
  8. enable_mariadb_slowlog (soft) — skipped if MariaDB not present
  9. start_services       (hard)   — systemctl enable --now
 10. verify_data_flow     (soft)   — poll server_metrics, 30s timeout

Each step:
  - writes a `running` OnboardingLog row + pushes WS step_update
  - executes
  - updates the row to done|failed|skipped + pushes WS step_update
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from uuid import UUID

import jinja2
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.other import DBCredential
from app.models.server import OnboardingLog, Server
from app.services.ssh import (
    SSHAuthError,
    SSHCommandError,
    SSHConnectionError,
    SSHError,
    SSHSession,
)
from app.ws.manager import ws_manager


TOTAL_STEPS = 10

_template_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(
        searchpath=str(__import__("pathlib").Path(__file__).parent / "templates")
    ),
    autoescape=False,
    keep_trailing_newline=True,
)


# ── OS info ──────────────────────────────────────────────────────────────────

@dataclass
class OSInfo:
    id: str               # "ubuntu" | "debian" | "rhel" | "centos" | "rocky" | "almalinux"
    version_id: str       # "22.04"
    pretty_name: str
    family: str           # "debian" | "rhel"
    kernel: str

    @property
    def package_manager(self) -> str:
        return "apt" if self.family == "debian" else "yum"


SUPPORTED = {
    "ubuntu": "debian",
    "debian": "debian",
    "rhel": "rhel",
    "centos": "rhel",
    "rocky": "rhel",
    "almalinux": "rhel",
}


def _parse_os_release(text_body: str, kernel: str) -> OSInfo | None:
    fields = {}
    for line in text_body.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            fields[k.strip()] = v.strip().strip('"')
    distro_id = fields.get("ID", "").lower()
    family = SUPPORTED.get(distro_id)
    if not family:
        return None
    return OSInfo(
        id=distro_id,
        version_id=fields.get("VERSION_ID", ""),
        pretty_name=fields.get("PRETTY_NAME", distro_id),
        family=family,
        kernel=kernel,
    )


# ── Logging + WS broadcasting ────────────────────────────────────────────────

async def _push(server_id: UUID, event: str, data: dict) -> None:
    await ws_manager.broadcast_onboarding(str(server_id), {"event": event, "data": data})


async def _start_step(
    db: AsyncSession,
    server_id: UUID,
    step: str,
    step_number: int,
) -> tuple[OnboardingLog, float]:
    started = datetime.now(timezone.utc)
    log = OnboardingLog(
        server_id=server_id,
        step=step,
        step_number=step_number,
        status="running",
        started_at=started,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    await _push(server_id, "step_update", {
        "step": step,
        "step_number": step_number,
        "total_steps": TOTAL_STEPS,
        "status": "running",
        "message": "",
        "duration_ms": None,
        "timestamp": started.isoformat(),
    })
    return log, perf_counter()


async def _finish_step(
    db: AsyncSession,
    log: OnboardingLog,
    t0: float,
    *,
    status: str,
    message: str = "",
    ssh_output: str | None = None,
) -> None:
    duration_ms = int((perf_counter() - t0) * 1000)
    log.status = status
    log.message = message
    log.ssh_output = ssh_output
    log.duration_ms = duration_ms
    await db.commit()
    await _push(log.server_id, "step_update", {
        "step": log.step,
        "step_number": log.step_number,
        "total_steps": TOTAL_STEPS,
        "status": status,
        "message": message,
        "duration_ms": duration_ms,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


# ── Step implementations ─────────────────────────────────────────────────────

async def _step_ssh_connect(db, server, ssh: SSHSession, log_step):
    log, t0 = await _start_step(db, server.id, "ssh_connect", 1)
    try:
        sudo_test = await ssh.run("sudo -n true", timeout=10)
        if not sudo_test.ok:
            msg = f"User '{server.ssh_user}' requires a password for sudo. Add NOPASSWD to sudoers."
            await _finish_step(db, log, t0, status="failed", message=msg, ssh_output=sudo_test.stderr)
            raise SSHError(msg)
        await _finish_step(db, log, t0, status="done", message="passwordless sudo verified")
    except SSHError:
        raise


async def _step_detect_os(db, server, ssh: SSHSession) -> OSInfo:
    log, t0 = await _start_step(db, server.id, "detect_os", 2)
    try:
        os_release = await ssh.run("cat /etc/os-release", raise_on_error=True)
        kernel = await ssh.run("uname -r", raise_on_error=True)
        os_info = _parse_os_release(os_release.stdout, kernel.stdout.strip())
        if os_info is None:
            msg = "Unsupported OS — only Ubuntu, Debian, and RHEL/CentOS are supported."
            await _finish_step(db, log, t0, status="failed", message=msg, ssh_output=os_release.stdout)
            raise SSHError(msg)
        await _finish_step(db, log, t0, status="done", message=os_info.pretty_name, ssh_output=os_release.stdout)
        return os_info
    except SSHCommandError as e:
        await _finish_step(db, log, t0, status="failed", message=str(e), ssh_output=e.result.stderr)
        raise SSHError(f"OS detection failed: {e}")


def _add_repos_script(os_info: OSInfo) -> str:
    if os_info.family == "debian":
        return r"""
set -e
sudo install -d -m 0755 /etc/apt/keyrings
# InfluxData (Telegraf)
curl -fsSL https://repos.influxdata.com/influxdata-archive.key | sudo gpg --batch --yes --dearmor -o /etc/apt/keyrings/influxdata-archive.gpg
echo "deb [signed-by=/etc/apt/keyrings/influxdata-archive.gpg] https://repos.influxdata.com/debian stable main" | sudo tee /etc/apt/sources.list.d/influxdata.list
# Fluent Bit
curl -fsSL https://packages.fluentbit.io/fluentbit.key | sudo gpg --batch --yes --dearmor -o /etc/apt/keyrings/fluentbit.gpg
. /etc/os-release
echo "deb [signed-by=/etc/apt/keyrings/fluentbit.gpg] https://packages.fluentbit.io/${ID}/${VERSION_CODENAME} ${VERSION_CODENAME} main" | sudo tee /etc/apt/sources.list.d/fluent-bit.list
sudo apt-get update -y
"""
    # RHEL family
    return r"""
set -e
sudo tee /etc/yum.repos.d/influxdata.repo >/dev/null <<EOF
[influxdata]
name=InfluxData Repository - Stable
baseurl=https://repos.influxdata.com/stable/\$basearch/main
enabled=1
gpgcheck=1
gpgkey=https://repos.influxdata.com/influxdata-archive.key
EOF
sudo tee /etc/yum.repos.d/fluent-bit.repo >/dev/null <<EOF
[fluent-bit]
name=Fluent Bit
baseurl=https://packages.fluentbit.io/centos/\$releasever/\$basearch/
enabled=1
gpgcheck=1
gpgkey=https://packages.fluentbit.io/fluentbit.key
EOF
"""


async def _step_add_repos(db, server, ssh: SSHSession, os_info: OSInfo):
    log, t0 = await _start_step(db, server.id, "add_repos", 3)
    script = _add_repos_script(os_info)
    try:
        r = await ssh.run(script, sudo=False, timeout=120)
        if not r.ok:
            msg = "Could not reach package repositories. Ensure outbound access to repos.influxdata.com and packages.fluentbit.io."
            await _finish_step(db, log, t0, status="failed", message=msg, ssh_output=r.stderr or r.stdout)
            raise SSHError(msg)
        await _finish_step(db, log, t0, status="done", ssh_output=r.stdout)
    except asyncio.TimeoutError:
        await _finish_step(db, log, t0, status="failed", message="timed out fetching repos")
        raise SSHError("add_repos timed out")


async def _step_install(db, server, ssh: SSHSession, os_info: OSInfo, package: str, step: str, n: int):
    log, t0 = await _start_step(db, server.id, step, n)
    if os_info.family == "debian":
        cmd = f"DEBIAN_FRONTEND=noninteractive apt-get install -y {package}"
    else:
        cmd = f"yum install -y {package}"
    r = await ssh.run(cmd, sudo=True, timeout=300)
    if not r.ok:
        await _finish_step(db, log, t0, status="failed", message=f"package install failed", ssh_output=r.stderr or r.stdout)
        raise SSHError(f"{package} install failed")
    await _finish_step(db, log, t0, status="done", ssh_output=r.stdout[-2000:])


async def _step_configure_telegraf(db, server, ssh: SSHSession, mysql_dsn: str | None):
    log, t0 = await _start_step(db, server.id, "configure_telegraf", 6)
    tmpl = _template_env.get_template("telegraf.conf.j2")
    conf = tmpl.render(
        server_id=str(server.id),
        server_name=server.name,
        ingest_url=settings.opspilot_base_url.rstrip("/") if settings.opspilot_base_url else "http://opspilot-backend:8000",
        ingestion_token=str(server.ingestion_token),
        mysql_dsn=mysql_dsn,
    )
    try:
        await ssh.upload(conf, "/etc/telegraf/telegraf.conf", mode=0o644, sudo=True)
        await _finish_step(db, log, t0, status="done", message="config written")
    except SSHError as e:
        await _finish_step(db, log, t0, status="failed", message=str(e))
        raise


def _log_paths(os_info: OSInfo) -> dict:
    if os_info.family == "debian":
        return {
            "syslog_path": "/var/log/syslog",
            "auth_log_path": "/var/log/auth.log",
            "mariadb_error_path": "/var/log/mysql/error.log",
            "mariadb_slow_path": "/var/log/mysql/slow.log",
        }
    return {
        "syslog_path": "/var/log/messages",
        "auth_log_path": "/var/log/secure",
        "mariadb_error_path": "/var/log/mariadb/mariadb.log",
        "mariadb_slow_path": "/var/log/mariadb/slow.log",
    }


async def _step_configure_fluent_bit(db, server, ssh: SSHSession, os_info: OSInfo):
    log, t0 = await _start_step(db, server.id, "configure_fluent_bit", 7)
    paths = _log_paths(os_info)
    # Parse host/port from base_url; default to in-cluster backend
    base = settings.opspilot_base_url.rstrip("/") if settings.opspilot_base_url else "http://opspilot-backend:8000"
    from urllib.parse import urlparse
    parsed = urlparse(base)
    ingest_host = parsed.hostname or "opspilot-backend"
    ingest_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    ingest_tls = "On" if parsed.scheme == "https" else "Off"

    tmpl = _template_env.get_template("fluent-bit.conf.j2")
    conf = tmpl.render(
        server_id=str(server.id),
        server_name=server.name,
        ingest_host=ingest_host,
        ingest_port=ingest_port,
        ingest_tls=ingest_tls,
        ingestion_token=str(server.ingestion_token),
        **paths,
    )
    try:
        await ssh.run("mkdir -p /etc/fluent-bit /var/lib/fluent-bit", sudo=True, raise_on_error=True)
        await ssh.upload(conf, "/etc/fluent-bit/fluent-bit.conf", mode=0o640, sudo=True)
        await _finish_step(db, log, t0, status="done", message="config written")
    except SSHError as e:
        await _finish_step(db, log, t0, status="failed", message=str(e))
        raise


async def _step_enable_mariadb_slowlog(db, server, ssh: SSHSession, os_info: OSInfo):
    log, t0 = await _start_step(db, server.id, "enable_mariadb_slowlog", 8)
    # Detect MariaDB or MySQL
    check = await ssh.run(
        "systemctl is-active mariadb 2>/dev/null || systemctl is-active mysqld 2>/dev/null || echo inactive",
        timeout=10,
    )
    if "active" not in check.stdout.lower() or "inactive" in check.stdout.lower():
        if check.stdout.strip() != "active":
            await _finish_step(db, log, t0, status="skipped", message="MariaDB/MySQL not detected")
            return

    conf_dir = "/etc/mysql/conf.d" if os_info.family == "debian" else "/etc/my.cnf.d"
    conf = "[mysqld]\nslow_query_log = 1\nslow_query_log_file = /var/log/mysql/slow.log\nlong_query_time = 1\n"
    try:
        await ssh.run(f"mkdir -p {conf_dir}", sudo=True, raise_on_error=True)
        await ssh.upload(conf, f"{conf_dir}/opspilot.cnf", mode=0o644, sudo=True)
        await ssh.run(
            "systemctl restart mariadb 2>/dev/null || systemctl restart mysqld",
            sudo=True, raise_on_error=True, timeout=60,
        )
        await _finish_step(db, log, t0, status="done", message="slow_query_log enabled")
    except SSHError as e:
        # Per spec: non-blocking warning
        await _finish_step(db, log, t0, status="skipped", message=f"could not enable: {e}")


async def _step_start_services(db, server, ssh: SSHSession):
    log, t0 = await _start_step(db, server.id, "start_services", 9)
    try:
        r = await ssh.run(
            "systemctl enable --now telegraf fluent-bit",
            sudo=True, timeout=30,
        )
        if not r.ok:
            await _finish_step(db, log, t0, status="failed", message="systemctl failed", ssh_output=r.stderr or r.stdout)
            raise SSHError("start_services failed")
        await _finish_step(db, log, t0, status="done", ssh_output=r.stdout)
    except SSHError:
        raise


async def _step_verify_data_flow(db, server) -> bool:
    log, t0 = await _start_step(db, server.id, "verify_data_flow", 10)
    deadline = perf_counter() + 30
    while perf_counter() < deadline:
        await asyncio.sleep(2)
        async with AsyncSessionLocal() as poll_db:
            row = await poll_db.execute(
                text("SELECT 1 FROM server_metrics WHERE server_id = :sid LIMIT 1"),
                {"sid": server.id},
            )
            if row.first():
                elapsed_sec = int(perf_counter() - t0)
                await _finish_step(db, log, t0, status="done", message=f"first metric in {elapsed_sec}s")
                return True
    # Soft failure
    await _finish_step(
        db, log, t0, status="skipped",
        message="no metrics received in 30s — server marked active anyway",
    )
    return False


# ── Orchestrator ─────────────────────────────────────────────────────────────

async def _build_mysql_dsn(db, server) -> str | None:
    cred = await db.scalar(select(DBCredential).where(DBCredential.server_id == server.id).limit(1))
    if not cred:
        return None
    from app.core.crypto import decrypt
    password = decrypt(cred.password_encrypted)
    return f"{cred.username}:{password}@tcp({cred.host}:{cred.port})/?tls=false"


async def run_onboarding(server_id: str, redeploy_only: bool = False) -> None:
    """
    Entry point. Called by the route handler (background task) — never blocks the request.

    redeploy_only: skips ssh_connect / detect_os / add_repos / installs; only re-renders
    configs and restarts services (per spec §2 "DB credentials saved" case).
    """
    # APScheduler passes string IDs
    sid = UUID(server_id) if isinstance(server_id, str) else server_id
    started_total = perf_counter()

    async with AsyncSessionLocal() as db:
        server = await db.scalar(select(Server).where(Server.id == sid, Server.is_active == True))
        if not server:
            return

        # Clear prior logs (retry semantics per spec §8.1)
        if not redeploy_only:
            await db.execute(delete(OnboardingLog).where(OnboardingLog.server_id == sid))
            await db.commit()

        try:
            async with SSHSession(server) as ssh:
                if not redeploy_only:
                    await _step_ssh_connect(db, server, ssh, "ssh_connect")
                    os_info = await _step_detect_os(db, server, ssh)
                    await _step_add_repos(db, server, ssh, os_info)
                    await _step_install(db, server, ssh, os_info, "telegraf", "install_telegraf", 4)
                    await _step_install(db, server, ssh, os_info, "fluent-bit", "install_fluent_bit", 5)
                else:
                    # Re-detect OS without writing a log row (we need OSInfo for templates)
                    os_release = await ssh.run("cat /etc/os-release", raise_on_error=True)
                    kernel = await ssh.run("uname -r", raise_on_error=True)
                    os_info = _parse_os_release(os_release.stdout, kernel.stdout.strip())
                    if not os_info:
                        raise SSHError("OS no longer detectable")

                mysql_dsn = await _build_mysql_dsn(db, server)

                await _step_configure_telegraf(db, server, ssh, mysql_dsn)
                await _step_configure_fluent_bit(db, server, ssh, os_info)
                await _step_enable_mariadb_slowlog(db, server, ssh, os_info)
                await _step_start_services(db, server, ssh)

                # Persist OS info on the server row
                server.os_distro = os_info.pretty_name
                server.kernel_version = os_info.kernel
                await db.commit()

                if not redeploy_only:
                    await _step_verify_data_flow(db, server)

            duration = int(perf_counter() - started_total)
            await _push(server.id, "onboarding_complete", {
                "server_id": str(server.id),
                "duration_sec": duration,
            })

        except SSHAuthError as e:
            await _push(server.id, "onboarding_failed", {
                "server_id": str(server.id),
                "step": "ssh_connect",
                "message": str(e),
            })
        except SSHConnectionError as e:
            await _push(server.id, "onboarding_failed", {
                "server_id": str(server.id),
                "step": "ssh_connect",
                "message": str(e),
            })
        except SSHError as e:
            await _push(server.id, "onboarding_failed", {
                "server_id": str(server.id),
                "step": "unknown",
                "message": str(e),
            })


# ── Job tracking (in-process; survives only until backend restart) ──────────
# Maps server_id -> asyncio.Task while onboarding is running.
# Used for 409 Conflict detection on /onboard endpoint.
_running_jobs: dict[str, asyncio.Task] = {}


def is_running(server_id: str) -> bool:
    task = _running_jobs.get(server_id)
    return task is not None and not task.done()


def schedule(server_id: str, redeploy_only: bool = False) -> bool:
    """Schedule onboarding in the current event loop. Returns False if already running."""
    if is_running(server_id):
        return False
    task = asyncio.create_task(run_onboarding(server_id, redeploy_only))
    _running_jobs[server_id] = task
    task.add_done_callback(lambda t: _running_jobs.pop(server_id, None))
    return True
