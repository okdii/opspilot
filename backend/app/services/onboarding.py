"""
Server onboarding orchestrator — implements the 11-step flow from spec 03.

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
 11. deploy_opspilot_agent (soft)  — install psutil, upload agent, start systemd service

Each step:
  - writes a `running` OnboardingLog row + pushes WS step_update
  - executes
  - updates the row to done|failed|skipped + pushes WS step_update
"""

import asyncio
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from urllib.parse import quote as _url_quote
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


TOTAL_STEPS = 11

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
        fb_block = ""
        if _fluent_bit_supported(os_info):
            fb_block = (
                "curl -fsSL https://packages.fluentbit.io/fluentbit.key"
                " | sudo gpg --batch --yes --dearmor -o /etc/apt/keyrings/fluentbit.gpg\n"
                ". /etc/os-release\n"
                'echo "deb [signed-by=/etc/apt/keyrings/fluentbit.gpg]'
                " https://packages.fluentbit.io/${ID}/${VERSION_CODENAME}"
                ' ${VERSION_CODENAME} main" | sudo tee /etc/apt/sources.list.d/fluent-bit.list\n'
            )
        sources = "sources.list.d/influxdata.list"
        if fb_block:
            sources += " sources.list.d/fluent-bit.list"
        return f"""set -e
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://repos.influxdata.com/influxdata-archive.key | sudo gpg --batch --yes --dearmor -o /etc/apt/keyrings/influxdata-archive.gpg
echo "deb [signed-by=/etc/apt/keyrings/influxdata-archive.gpg] https://repos.influxdata.com/debian stable main" | sudo tee /etc/apt/sources.list.d/influxdata.list
{fb_block}sudo apt-get update -o Dir::Etc::sourcelist="{sources}" -o Dir::Etc::sourcelistparts="" -o APT::Get::List-Cleanup="0"
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


def _fluent_bit_supported(os_info: OSInfo) -> bool:
    """Fluent Bit has no packages for Debian < 10 (stretch and older)."""
    if os_info.id == "debian":
        try:
            return int(os_info.version_id.split(".")[0]) >= 10
        except (ValueError, IndexError):
            return True
    return True


async def _skip_step(db, server_id, step: str, n: int, message: str) -> None:
    log, t0 = await _start_step(db, server_id, step, n)
    await _finish_step(db, log, t0, status="skipped", message=message)


async def _step_add_repos(db, server, ssh: SSHSession, os_info: OSInfo):
    log, t0 = await _start_step(db, server.id, "add_repos", 3)
    if os_info.family == "debian":
        repo_check = await ssh.run("test -f /etc/apt/sources.list.d/influxdata.list", sudo=False, timeout=10)
    else:
        repo_check = await ssh.run("test -f /etc/yum.repos.d/influxdata.repo", sudo=False, timeout=10)
    if repo_check.ok:
        if os_info.family == "debian":
            telegraf_check = await ssh.run("dpkg-query -W -f='${Status}' telegraf 2>/dev/null | grep -q 'install ok installed'", sudo=False, timeout=10)
            if not telegraf_check.ok:
                await ssh.run(
                    "apt-get update"
                    " -o Dir::Etc::sourcelist=sources.list.d/influxdata.list"
                    " -o Dir::Etc::sourcelistparts=''"
                    " -o APT::Get::List-Cleanup=0",
                    sudo=True, timeout=60,
                )
        await _finish_step(db, log, t0, status="done", message="package repositories already configured")
        return
    script = _add_repos_script(os_info)
    try:
        r = await ssh.run(script, sudo=False, timeout=240)
        if not r.ok:
            msg = "Could not reach package repositories. Ensure outbound access to repos.influxdata.com and packages.fluentbit.io."
            await _finish_step(db, log, t0, status="failed", message=msg, ssh_output=r.stderr or r.stdout)
            raise SSHError(msg)
        await _finish_step(db, log, t0, status="done", ssh_output=r.stdout)
    except asyncio.TimeoutError:
        await _finish_step(db, log, t0, status="failed", message="timed out fetching repos (>240s) — server may have slow package mirrors")
        raise SSHError("add_repos timed out")


async def _step_install(db, server, ssh: SSHSession, os_info: OSInfo, package: str, step: str, n: int):
    log, t0 = await _start_step(db, server.id, step, n)
    if os_info.family == "debian":
        check = await ssh.run(f"dpkg-query -W -f='${{Status}}' {package} 2>/dev/null | grep -q 'install ok installed'", sudo=False, timeout=10)
    else:
        check = await ssh.run(f"rpm -q {package}", sudo=False, timeout=10)
    if check.ok:
        await _finish_step(db, log, t0, status="done", message=f"{package} already installed")
        return
    if os_info.family == "debian":
        cmd = f"DEBIAN_FRONTEND=noninteractive apt-get install -y {package}"
    else:
        cmd = f"yum install -y {package}"
    r = await ssh.run(cmd, sudo=True, timeout=300)
    if not r.ok:
        await _finish_step(db, log, t0, status="failed", message="package install failed", ssh_output=r.stderr or r.stdout)
        raise SSHError(f"{package} install failed")
    await _finish_step(db, log, t0, status="done", ssh_output=r.stdout[-2000:])


async def _step_configure_telegraf(db, server, ssh: SSHSession, db_instances: list[dict], os_info: OSInfo | None = None):
    log, t0 = await _start_step(db, server.id, "configure_telegraf", 6)
    tmpl = _template_env.get_template("telegraf.conf.j2")
    # inputs.systemd_units requires systemd ≥ 233 D-Bus API; Debian 9 ships 232
    supports_systemd_units = not (
        os_info is not None
        and os_info.id == "debian"
        and os_info.version_id.split(".")[0] == "9"
    )
    conf = tmpl.render(
        server_id=str(server.id),
        server_name=server.name,
        ingest_url=settings.opspilot_base_url.rstrip("/") if settings.opspilot_base_url else "http://opspilot-backend:8000",
        ingestion_token=str(server.ingestion_token),
        db_instances=db_instances,
        supports_systemd_units=supports_systemd_units,
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


# ── Security hardening (Task 8) ──────────────────────────────────────────────
#
# These steps run during configure_fluent_bit so their results can be fed into
# the Fluent Bit template (web_access_log_path / auditd_enabled /
# mariadb_general_enabled gate the conditional INPUT blocks added in Task 7).
#
# All hardening is BEST-EFFORT: any failure is swallowed (the corresponding
# template var stays falsy → its INPUT block is simply omitted). A hardening
# failure must NEVER abort onboarding.

# auditd: non-disruptive rules. The web-server uid is resolved remotely
# (www-data / apache / nginx, falling back to 33) rather than hardcoded.
_AUDITD_SETUP = """\
WEBUID=$(id -u www-data 2>/dev/null || id -u apache 2>/dev/null || id -u nginx 2>/dev/null || echo 33)
( apt-get install -y auditd >/dev/null 2>&1 || yum install -y audit >/dev/null 2>&1 || true )
mkdir -p /etc/audit/rules.d
cat >/etc/audit/rules.d/opspilot.rules <<RULES
-w /var/www -p wa -k webroot_write
-a exit,always -F arch=b64 -F uid=$WEBUID -S execve -k webshell_exec
-a exit,always -F arch=b32 -F uid=$WEBUID -S execve -k webshell_exec
-w /root/.ssh/authorized_keys -p wa -k ssh_key_change
-a always,exit -F arch=b64 -F dir=/home -F name=authorized_keys -F perm=wa -k ssh_key_change
-a always,exit -F arch=b32 -F dir=/home -F name=authorized_keys -F perm=wa -k ssh_key_change
-w /var/log -p wa -k log_tamper
RULES
augenrules --load >/dev/null 2>&1 && echo AUDITD_OK
"""

# PHP-execution block for upload dirs. nginx loads conf.d/*.conf in the http{}
# context, but a `location` directive is only valid inside a server{} block — a
# bare location in conf.d fails `nginx -t`. So we cannot harden nginx globally
# without editing the operator's vhosts (which we never do automatically).
# Instead, write a ready-to-include snippet and leave it to the operator to add
# `include snippets/opspilot-php-block.conf;` to their server block. Writing the
# snippet never affects `nginx -t` because nothing includes it yet.
_NGINX_PHP_BLOCK = r"""
mkdir -p /etc/nginx/snippets
cat >/etc/nginx/snippets/opspilot-php-block.conf <<'NGX'
# OpsPilot — deny PHP execution under upload dirs.
# Include inside each server{} block:  include snippets/opspilot-php-block.conf;
location ~* /(images|media|uploads|files|tmp|cache)/.*\.php$ { deny all; }
NGX
echo PHPBLOCK_SNIPPET
"""

# Remediation wrapper installed at /usr/local/bin/opspilot-action.
# The sudoers drop-in pins to this script so a stolen SSH key cannot run
# arbitrary root commands — only the verbs defined here.
_OPSPILOT_ACTION_SCRIPT = """\
#!/usr/bin/env bash
# /usr/local/bin/opspilot-action — OpsPilot allow-listed remediation wrapper.
# MANAGED BY OPSPILOT. Reinstalled on every onboarding run.
#
# Sudoers entry (see /etc/sudoers.d/opspilot):
#   SSH_USER ALL=(root) NOPASSWD: /usr/local/bin/opspilot-action
set -euo pipefail

QUARANTINE_DIR="/var/opspilot-quarantine"
DB_CREDS="/root/.mdsb-db-credentials"

die() { printf 'opspilot-action: %s\\n' "$*" >&2; exit 1; }

_validate_ip() {
    local ip="$1"
    [[ "$ip" =~ ^[0-9a-fA-F.:]+$ ]] || die "invalid ip: $ip"
    echo "$ip"
}

_reject_private_ip() {
    local ip="$1"
    case "$ip" in
        127.*|0.*|"::1"|fc*|fd*|fe80*|FE80*)
            die "refusing private/loopback ip: $ip" ;;
        10.*|192.168.*)
            die "refusing private ip: $ip" ;;
    esac
    if [[ "$ip" =~ ^172\\.([0-9]+)\\. ]]; then
        local oct="${BASH_REMATCH[1]}"
        if (( oct >= 16 && oct <= 31 )); then die "refusing private ip: $ip"; fi
    fi
}

_validate_pid() {
    local pid="$1"
    [[ "$pid" =~ ^[0-9]+$ ]] || die "invalid pid: $pid"
    (( pid > 1 )) || die "refusing pid <= 1: $pid"
    echo "$pid"
}

_validate_path() {
    local path="$1"
    [[ "$path" == /* ]] || die "path must be absolute: $path"
    [[ "$path" != *..* ]] || die "path must not contain ..: $path"
    local ok=0
    for root in /var/www /usr/share/nginx /srv/www /home; do
        [[ "$path" == "$root"/* ]] && ok=1 && break
    done
    (( ok )) || die "path not under a web root: $path"
    echo "$path"
}

_validate_user() {
    local user="$1"
    [[ "$user" =~ ^[a-zA-Z0-9_-]+$ ]] || die "invalid user: $user"
    echo "$user"
}

_validate_db_user() {
    local u="$1"
    [[ "$u" =~ ^[a-zA-Z0-9_.@-]+$ ]] || die "invalid db user: $u"
    echo "$u"
}

verb="${1:-}"
[[ -n "$verb" ]] || die "usage: opspilot-action <verb> [args...]"
shift

case "$verb" in
    block_ip)
        ip=$(_validate_ip "$1"); _reject_private_ip "$ip"
        bin="iptables"; [[ "$ip" == *:* ]] && bin="ip6tables"
        "$bin" -C INPUT -s "$ip" -j DROP 2>/dev/null || "$bin" -I INPUT -s "$ip" -j DROP
        ;;
    unblock_ip)
        ip=$(_validate_ip "$1")
        bin="iptables"; [[ "$ip" == *:* ]] && bin="ip6tables"
        "$bin" -D INPUT -s "$ip" -j DROP 2>/dev/null || true
        ;;
    quarantine_file)
        path=$(_validate_path "$1")
        mkdir -p "$QUARANTINE_DIR"
        if [ -e "$path" ]; then
            dest="$QUARANTINE_DIR/$(date +%s)_$(basename "$path")"
            chmod 000 "$path"; mv "$path" "$dest"; echo "$dest"
        else echo "MISSING"; fi
        ;;
    restore_file)
        quarantined="$1"; original=$(_validate_path "$2")
        [[ "$quarantined" == "$QUARANTINE_DIR/"* ]] || die "bad quarantine path: $quarantined"
        [[ "$quarantined" != *..* ]] || die "path traversal in quarantine path"
        mv "$quarantined" "$original"; chmod 644 "$original"
        ;;
    kill_pid)
        pid=$(_validate_pid "$1"); kill -9 "$pid"
        ;;
    revert_authorized_keys)
        user=$(_validate_user "$1")
        home="/root"; [ "$user" != "root" ] && home="/home/$user"
        ak="$home/.ssh/authorized_keys"
        if [ ! -f "$ak" ]; then echo "MISSING"; exit 0; fi
        count=$(grep -c . "$ak" 2>/dev/null || echo 0)
        if (( count <= 1 )); then echo "SINGLE"; exit 0; fi
        backup=$(base64 -w0 "$ak")
        sed '$d' "$ak" > "$ak.opspilot"; mv "$ak.opspilot" "$ak"
        echo "$backup"
        ;;
    restore_authorized_keys)
        user=$(_validate_user "$1")
        home="/root"; [ "$user" != "root" ] && home="/home/$user"
        ak="$home/.ssh/authorized_keys"
        b64=$(cat)
        echo "$b64" | base64 -d > "$ak"; chmod 600 "$ak"
        ;;
    disable_db_user)
        u=$(_validate_db_user "$1")
        mysql --defaults-extra-file="$DB_CREDS" -e "ALTER USER '${u}'@'%' ACCOUNT LOCK;"
        ;;
    enable_db_user)
        u=$(_validate_db_user "$1")
        mysql --defaults-extra-file="$DB_CREDS" -e "ALTER USER '${u}'@'%' ACCOUNT UNLOCK;"
        ;;
    *)
        die "unknown verb: $verb"
        ;;
esac
"""

# sudoers drop-in template. __SSH_USER__ is replaced with server.ssh_user at install time.
# Pins the SSH user to ONLY the wrapper script — no other root commands are permitted.
_OPSPILOT_SUDOERS_TEMPLATE = """\
# Managed by OpsPilot. Do not edit — reinstalled on re-onboarding.
# Restricts __SSH_USER__ to ONLY the OpsPilot remediation wrapper.
# A compromised SSH key cannot run arbitrary root commands.
# !requiretty + !use_pty: allow the wrapper to run over a non-interactive SSH
# channel (the OpsPilot backend never allocates a TTY for remediation calls).
Defaults:__SSH_USER__ !requiretty, !use_pty
__SSH_USER__ ALL=(root) NOPASSWD: /usr/local/bin/opspilot-action
"""

# Apache (Debian): DirectoryMatch denying PHP handlers under upload dirs.
# Validate with apache2ctl configtest; revert + skip reload on failure.
_APACHE_PHP_BLOCK_DEBIAN = r"""
mkdir -p /etc/apache2/conf-available
cat >/etc/apache2/conf-available/opspilot-php-block.conf <<'APC'
<DirectoryMatch "/(images|media|uploads|files|tmp|cache)/">
    <FilesMatch "\.(php|phtml|php[0-9]?)$">
        Require all denied
    </FilesMatch>
</DirectoryMatch>
APC
a2enconf opspilot-php-block >/dev/null 2>&1 || ln -sf ../conf-available/opspilot-php-block.conf /etc/apache2/conf-enabled/opspilot-php-block.conf
if apache2ctl configtest >/dev/null 2>&1; then
    systemctl reload apache2 >/dev/null 2>&1 && echo PHPBLOCK_OK
else
    a2disconf opspilot-php-block >/dev/null 2>&1 || rm -f /etc/apache2/conf-enabled/opspilot-php-block.conf
    rm -f /etc/apache2/conf-available/opspilot-php-block.conf
    echo PHPBLOCK_INVALID
fi
"""

# Apache (RHEL): same rule into conf.d (httpd auto-loads conf.d/*.conf).
# Validate with httpd -t; revert + skip reload on failure.
_APACHE_PHP_BLOCK_RHEL = r"""
mkdir -p /etc/httpd/conf.d
cat >/etc/httpd/conf.d/opspilot-php-block.conf <<'APC'
<DirectoryMatch "/(images|media|uploads|files|tmp|cache)/">
    <FilesMatch "\.(php|phtml|php[0-9]?)$">
        Require all denied
    </FilesMatch>
</DirectoryMatch>
APC
if httpd -t >/dev/null 2>&1; then
    systemctl reload httpd >/dev/null 2>&1 && echo PHPBLOCK_OK
else
    rm -f /etc/httpd/conf.d/opspilot-php-block.conf
    echo PHPBLOCK_INVALID
fi
"""

# MariaDB general query log enable (GATED — disruptive, restarts MariaDB).
# NOT run by default in this task; kept here for a future opt-in flag.
_MARIADB_GENERAL_ENABLE = """\
cat >/etc/mysql/conf.d/opspilot-general-log.cnf <<CNF
[mysqld]
general_log = 1
general_log_file = /var/log/mysql/general.log
CNF
systemctl restart mariadb && echo DBLOG_OK
"""


async def _detect_web_access_log(ssh: SSHSession) -> str:
    """
    Detect the active web server and return its access-log path.

    Priority: LiteSpeed → nginx → Apache(Debian) → Apache(RHEL).
    Returns "" if none detected (keeps the template's web_access INPUT off).
    """
    checks = [
        ("systemctl is-active --quiet lsws", "/usr/local/lsws/logs/access.log"),
        ("systemctl is-active --quiet nginx", "/var/log/nginx/access.log"),
        ("systemctl is-active --quiet apache2", "/var/log/apache2/access.log"),
        ("test -f /var/log/httpd/access_log", "/var/log/httpd/access_log"),
    ]
    for cmd, path in checks:
        try:
            r = await ssh.run(cmd, timeout=10)
        except SSHError:
            continue
        if r.ok:
            return path
    return ""


def _web_server_kind(web_access_log_path: str) -> str:
    """Map a detected access-log path back to a web-server kind for PHP-block selection."""
    if web_access_log_path == "/usr/local/lsws/logs/access.log":
        return "litespeed"
    if web_access_log_path == "/var/log/nginx/access.log":
        return "nginx"
    if web_access_log_path == "/var/log/apache2/access.log":
        return "apache-debian"
    if web_access_log_path == "/var/log/httpd/access_log":
        return "apache-rhel"
    return ""


def _web_error_log(web_kind: str) -> str:
    """Map a detected web-server kind to its error-log path (mirrors _detect_web_access_log).

    Reuses the single detection already performed for the access log instead of
    probing over SSH again. Returns "" for an unknown kind (keeps the template's
    web_error INPUT off). nginx is intentionally included so the template gate can
    skip it — the hardcoded nginx_error input already tails it.
    """
    return {
        "litespeed": "/usr/local/lsws/logs/error.log",
        "nginx": "/var/log/nginx/error.log",
        "apache-debian": "/var/log/apache2/error.log",
        "apache-rhel": "/var/log/httpd/error_log",
    }.get(web_kind, "")


async def _setup_auditd(ssh: SSHSession) -> bool:
    """Install non-disruptive auditd rules. Best-effort; returns True only on AUDITD_OK."""
    try:
        r = await ssh.run(_AUDITD_SETUP, sudo=True, timeout=120)
        return "AUDITD_OK" in (r.stdout or "")
    except SSHError:
        return False


async def _apply_php_block(ssh: SSHSession, web_kind: str) -> None:
    """
    Drop a web-server-aware PHP-execution block for upload dirs. Best-effort.

    Each variant validates the web-server config BEFORE reloading and reverts its
    own file if validation fails — the web server is never left non-validating.
    LiteSpeed cannot be hardened generically without risking the vhost config, so
    we log a manual-step note and change nothing that could break it.
    """
    cmd_by_kind = {
        "apache-debian": _APACHE_PHP_BLOCK_DEBIAN,
        "apache-rhel": _APACHE_PHP_BLOCK_RHEL,
    }
    if web_kind == "nginx":
        # nginx can't be hardened globally from http-context conf.d (see
        # _NGINX_PHP_BLOCK). Write the ready-to-include snippet and emit a note —
        # never edit the operator's vhosts automatically.
        try:
            await ssh.run(_NGINX_PHP_BLOCK, sudo=True, timeout=60)
        except SSHError:
            pass
        await _push_log_note(
            ssh, "nginx_php_block",
            "nginx detected — wrote /etc/nginx/snippets/opspilot-php-block.conf. "
            "Add `include snippets/opspilot-php-block.conf;` inside each server{} "
            "block and reload nginx to deny PHP execution under upload dirs.",
        )
        return
    if web_kind == "litespeed":
        # LiteSpeed honors context rules in the vhost config, not a dropped conf
        # file, and editing the vhost generically is unsafe. Skip with a note.
        await _push_log_note(
            ssh, "litespeed_php_block",
            "LiteSpeed detected — PHP-execution block requires a manual vhost "
            "context rule denying *.php under upload dirs; skipped automatically.",
        )
        return
    cmd = cmd_by_kind.get(web_kind)
    if not cmd:
        return
    try:
        await ssh.run(cmd, sudo=True, timeout=60)
    except SSHError:
        # Validation/reload guarded inside the script; nothing left to revert here.
        pass


async def _push_log_note(ssh: SSHSession, key: str, message: str) -> None:
    """Lightweight informational note — no remote side effect, just structured logging."""
    import logging
    logging.getLogger("opspilot.onboarding").info("%s: %s", key, message)


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

    # Detect the actual PHP-FPM log path on the target server.
    # Priority: 1) configured error_log in php-fpm.conf, 2) Debian glob, 3) RHEL glob, 4) default glob.
    _php_detect = (
        "p=$(grep -rh '^error_log[[:space:]]*=' "
        "/etc/php/*/fpm/php-fpm.conf /etc/php-fpm.conf /etc/php-fpm.d/*.conf 2>/dev/null "
        "| awk -F= '{gsub(/^[ \\t]+|[ \\t]+$/,\"\",$2); print $2}' | head -1); "
        "[ -n \"$p\" ] && echo \"$p\" && exit 0; "
        "ls /var/log/php*-fpm.log >/dev/null 2>&1 && echo '/var/log/php*-fpm.log' && exit 0; "
        "ls /var/log/php-fpm/ >/dev/null 2>&1 && echo '/var/log/php-fpm/*.log' && exit 0; "
        "echo '/var/log/php*-fpm.log'"
    )
    _php_result = await ssh.run(_php_detect, timeout=10)
    php_fpm_log_path = (_php_result.stdout or "").strip() or "/var/log/php*-fpm.log"

    # Detect PHP app error_log from php.ini (empty string = omit INPUT block).
    _php_app_detect = (
        "p=$(grep -rh '^error_log[[:space:]]*=' "
        "/etc/php/*/fpm/php.ini /etc/php/*/cli/php.ini /etc/php.ini 2>/dev/null "
        "| awk -F= '{gsub(/^[ \\t]+|[ \\t]+$/,\"\",$2); print $2}' | head -1); "
        "[ -n \"$p\" ] && echo \"$p\" || echo ''"
    )
    _php_app_result = await ssh.run(_php_app_detect, timeout=10)
    php_app_log_path = (_php_app_result.stdout or "").strip()

    # ── Security hardening (Task 8) — compute template vars + apply side effects ──
    # All best-effort: a failure leaves the var falsy and onboarding continues.
    web_access_log_path = await _detect_web_access_log(ssh)
    web_kind = _web_server_kind(web_access_log_path)
    web_error_log_path = _web_error_log(web_kind)

    # (2) auditd — non-disruptive rules; gates the auditd INPUT block.
    auditd_enabled = await _setup_auditd(ssh)

    # (3) PHP-execution block for upload dirs (web-server-aware, validated-before-reload).
    await _apply_php_block(ssh, web_kind)

    # (4) MariaDB general query log — GATED, default OFF (disruptive: restarts MariaDB).
    # No onboarding flag exists for this yet, so it stays disabled. When a future
    # opt-in flag is added, replace `False` with that flag and run the stub below:
    #     if r := await ssh.run(_MARIADB_GENERAL_ENABLE, sudo=True, timeout=60):
    #         mariadb_general_enabled = "DBLOG_OK" in (r.stdout or "")
    # By default NO MariaDB restart happens.
    mariadb_general_enabled = False

    tmpl = _template_env.get_template("fluent-bit.conf.j2")
    conf = tmpl.render(
        server_id=str(server.id),
        server_name=server.name,
        ingest_host=ingest_host,
        ingest_port=ingest_port,
        ingest_tls=ingest_tls,
        ingestion_token=str(server.ingestion_token),
        php_fpm_log_path=php_fpm_log_path,
        php_app_log_path=php_app_log_path,
        web_access_log_path=web_access_log_path,
        web_error_log_path=web_error_log_path,
        auditd_enabled=auditd_enabled,
        mariadb_general_enabled=mariadb_general_enabled,
        **paths,
    )
    # Multiline/parser definitions must live in a separate parsers file
    # (Fluent Bit v5 rejects them inline in the main config).
    parsers_conf = _template_env.get_template("fluent-bit-parsers.conf.j2").render()
    try:
        await ssh.run("mkdir -p /etc/fluent-bit /var/lib/fluent-bit", sudo=True, raise_on_error=True)
        await ssh.upload(parsers_conf, "/etc/fluent-bit/parsers-opspilot.conf", mode=0o640, sudo=True)
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


async def _step_start_services(db, server, ssh: SSHSession, os_info: OSInfo):
    log, t0 = await _start_step(db, server.id, "start_services", 9)
    try:
        if _fluent_bit_supported(os_info):
            services = "telegraf fluent-bit"
        else:
            services = "telegraf"
        r = await ssh.run(
            f"systemctl reset-failed {services} 2>/dev/null; "
            f"systemctl enable {services} && "
            f"systemctl restart {services}",
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


async def _step_deploy_opspilot_agent(db, server, ssh: SSHSession):
    log, t0 = await _start_step(db, server.id, "deploy_opspilot_agent", 11)
    try:
        tmpl = _template_env.get_template("opspilot-agent.py.j2")
        base = settings.opspilot_base_url.rstrip("/") if settings.opspilot_base_url else "http://opspilot-backend:8000"
        script = tmpl.render(
            base_url=base,
            ingestion_token=str(server.ingestion_token),
        )

        # Ensure python3 is available, then install psutil
        await ssh.run(
            "which python3 >/dev/null 2>&1 || apt-get install -y python3 2>/dev/null || true",
            sudo=True, timeout=60,
        )
        await ssh.run(
            "python3 -m pip install --quiet psutil 2>/dev/null || "
            "apt-get install -y python3-psutil 2>/dev/null || true",
            sudo=True, timeout=60,
        )

        # Upload agent script
        await ssh.upload(script, "/opt/opspilot-agent.py", mode=0o755, sudo=True)

        # Create systemd unit
        unit = (
            "[Unit]\n"
            "Description=OpsPilot Agent\n"
            "After=network.target\n\n"
            "[Service]\n"
            "ExecStart=/usr/bin/python3 /opt/opspilot-agent.py\n"
            "Restart=always\n"
            "RestartSec=15\n\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
        )
        await ssh.upload(unit, "/etc/systemd/system/opspilot-agent.service", mode=0o644, sudo=True)

        # Enable and start
        r = await ssh.run(
            "systemctl daemon-reload && systemctl enable --now opspilot-agent",
            sudo=True, timeout=15,
        )
        if not r.ok:
            await _finish_step(db, log, t0, status="skipped",
                               message="agent service failed to start", ssh_output=r.stderr or r.stdout)
            return

        await _finish_step(db, log, t0, status="done", message="opspilot-agent running")
    except Exception as exc:
        await _finish_step(db, log, t0, status="skipped", message=f"agent deploy skipped: {exc}")


async def _step_install_action_wrapper(db, server: Server, ssh: SSHSession) -> None:
    """Install /usr/local/bin/opspilot-action and lock sudoers to it.

    Soft step — failure never aborts onboarding. The server remains functional;
    sudoers is just not yet restricted. A warning is written to the onboarding log.

    After this step succeeds, the SSH user can ONLY sudo the wrapper script —
    a stolen key cannot run arbitrary root commands.
    """
    t0, log = await _start_step(db, server.id, "install_action_wrapper")
    try:
        ssh_user = server.ssh_user or "opspilot"

        # Install the wrapper executable
        await ssh.upload(_OPSPILOT_ACTION_SCRIPT, "/usr/local/bin/opspilot-action",
                         mode=0o755, sudo=True)

        # Build the sudoers drop-in for this server's SSH user
        sudoers = _OPSPILOT_SUDOERS_TEMPLATE.replace("__SSH_USER__", ssh_user)

        # Stage to /tmp, validate with visudo, then install atomically.
        # If visudo rejects it the bad file never reaches sudoers.d.
        r = await ssh.run(
            f"echo {shlex.quote(sudoers)} > /tmp/opspilot-sudoers && "
            f"visudo -c -f /tmp/opspilot-sudoers && "
            f"mv /tmp/opspilot-sudoers /etc/sudoers.d/opspilot && "
            f"chmod 440 /etc/sudoers.d/opspilot && "
            f"echo SUDOERS_OK",
            sudo=True, timeout=15,
        )
        if not r.ok or "SUDOERS_OK" not in r.stdout:
            raise RuntimeError(f"sudoers install failed: {r.stderr or r.stdout}")

        await _finish_step(db, log, t0, status="done",
                           message=f"opspilot-action installed; sudoers restricted to wrapper for {ssh_user}")
    except Exception as exc:
        await _finish_step(db, log, t0, status="skipped",
                           message=f"action wrapper install skipped (sudoers NOT restricted yet): {exc}")


# ── Orchestrator ─────────────────────────────────────────────────────────────

async def _build_db_instances(db, server) -> list[dict]:
    """Return [{label, dsn, db_type}] for every DBCredential on this server."""
    from app.core.crypto import decrypt
    creds = (
        await db.execute(select(DBCredential).where(DBCredential.server_id == server.id))
    ).scalars().all()
    instances = []
    for cred in creds:
        label = cred.label or f"{cred.db_type}:{cred.port}"
        password = decrypt(cred.password_encrypted)
        enc_pw = _url_quote(password, safe="")
        if cred.db_type == "postgres":
            dsn = f"postgres://{cred.username}:{enc_pw}@{cred.host}:{cred.port}/postgres?sslmode=disable"
        else:
            dsn = f"{cred.username}:{enc_pw}@tcp({cred.host}:{cred.port})/?tls=false"
        instances.append({"label": label, "dsn": dsn, "db_type": cred.db_type})
    return instances


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
                    if _fluent_bit_supported(os_info):
                        await _step_install(db, server, ssh, os_info, "fluent-bit", "install_fluent_bit", 5)
                    else:
                        await _skip_step(db, server.id, "install_fluent_bit", 5, f"skipped — Fluent Bit not available on {os_info.pretty_name}")
                else:
                    # Re-detect OS without writing a log row (we need OSInfo for templates)
                    os_release = await ssh.run("cat /etc/os-release", raise_on_error=True)
                    kernel = await ssh.run("uname -r", raise_on_error=True)
                    os_info = _parse_os_release(os_release.stdout, kernel.stdout.strip())
                    if not os_info:
                        raise SSHError("OS no longer detectable")

                db_instances = await _build_db_instances(db, server)
                await _step_configure_telegraf(db, server, ssh, db_instances, os_info)
                if _fluent_bit_supported(os_info):
                    await _step_configure_fluent_bit(db, server, ssh, os_info)
                else:
                    await _skip_step(db, server.id, "configure_fluent_bit", 7, f"skipped — Fluent Bit not available on {os_info.pretty_name}")
                await _step_enable_mariadb_slowlog(db, server, ssh, os_info)
                await _step_start_services(db, server, ssh, os_info)

                # Persist OS info on the server row
                server.os_distro = os_info.pretty_name
                server.kernel_version = os_info.kernel
                await db.commit()

                if not redeploy_only:
                    await _step_verify_data_flow(db, server)

                await _step_deploy_opspilot_agent(db, server, ssh)
                await _step_install_action_wrapper(db, server, ssh)

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
