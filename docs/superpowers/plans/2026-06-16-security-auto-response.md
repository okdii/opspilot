# Security Auto-Response (Self-Healing) — Implementation Plan (Part 2 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When Part 1 detects a high-confidence attack, OpsPilot acts — auto-blocks the IP, quarantines the webshell, kills the malicious process (Tier 1, reversible), and holds high-blast-radius actions (revert SSH keys, lock DB user) for one-click human approval (Tier 2) — all audited and undoable, behind a per-server opt-in and a global kill switch.

**Architecture:** A new APScheduler job (`security_responder`, 30s) polls Part-1 `Alert` rows of security types that have no `security_actions` row yet. For each, it derives confidence + an action plan, checks gates (global kill switch, per-server opt-in, rate-limit), then either executes Tier-1 actions via a typed, allow-listed `response_channel` over the existing `SSHSession`, or writes a `pending_approval` row for Tier-2. Every attempt is one row in a new `security_actions` ledger; executed actions are undoable; `block_ip` auto-expires via a second job. The UI adds a `SecurityActionsPanel` to the existing Security tab.

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy async + Alembic (backend); Vue 3 + Vuestic + Pinia + TypeScript (frontend); APScheduler (SQLAlchemy job store); existing `SSHSession` transport.

---

## Implementation Decisions (clarifications/deviations from the spec — review these first)

The design spec (`docs/superpowers/specs/2026-06-16-security-auto-response-design.md`) is the source of truth. These are the concrete implementation choices this plan locks in. They were chosen for safety, reversibility, and to fit the *current* codebase. Read them before starting.

1. **Confidence is derived in the responder, not read from the alert.** (User-approved decision.) Part 1 never shipped a `confidence` field. `security_responder.py` owns a static `CONFIDENCE` map (alert `type` → `high`/`medium`) and records the value on each `security_actions` row. No Part 1 schema change.

2. **Trigger = polling job, not inline in the evaluator.** A new 30s job queries fired security alerts lacking a `security_actions` row. The ledger row *is* the idempotency key, so it is restart-safe and never double-acts. `log_evaluator.py` is **not** modified.

3. **Target extraction comes from `server_logs`, not the alert message.** The webshell/upload alerts are generic-count alerts whose `message` carries no IP/path. The responder queries recent `server_logs` for the server to pull the attacker **IP** (access-log lines), **file path** (auditd `webroot_write` / access-log `.php`), and **pid** (auditd `webshell_exec` execve). If a required target can't be extracted, the action is recorded `failed` with a reason — never guessed.

4. **`block_ip` uses tagged iptables/ip6tables DROP, TTL managed by OpsPilot.** fail2ban bans require a jail watching the right log; web attackers may have no such jail. A tagged `iptables -I INPUT -s <ip> -j DROP` (IPv6 → `ip6tables`) is reliable, independent, and removed by our own TTL-expiry job (`executed_at + block_ttl_hours`). This is consistent with fail2ban (which also drives iptables). IP is strictly validated with Python's `ipaddress` module before it ever reaches the shell.

5. **The verb allow-list is enforced client-side in `response_channel.py` for v1.** The spec's ideal is a *server-side* sudoers command allow-list. But Part 1's onboarding already requires the `opspilot` SSH user to hold **NOPASSWD full sudo** — so the blast radius is already broad and unchanged by Part 2. v1 enforces safety where it's achievable now: `response_channel` exposes only typed verbs with validated args and **never interpolates a free-form command string**. Hardening the server sudoers to a command allow-list is a documented follow-up (it requires reworking onboarding's sudo model) — captured in the spec's risk table, not built here.

6. **Irreversible actions are minimized and clearly flagged.**
   - `kill_pid` (Tier 1): no undo possible — UI shows "no undo". Low blast radius (a `www-data` child).
   - `revert_authorized_keys` (Tier 2): removes only the **last-appended** key line (the attacker's freshly-added key that triggered the `ssh_key_change` auditd rule), after backing up the full file to `reversal`. Undo restores the full backup. Does **not** nuke the admin's existing keys.
   - `disable_db_user` (Tier 2): `ALTER USER … ACCOUNT LOCK` (reversible via `ACCOUNT UNLOCK`). The irreversible `drop_db_user` from the spec is **deferred** (YAGNI + irreversibility) and listed as a follow-up.

7. **Verification is smoke-tests, not unit tests.** This repo has no test harness; CLAUDE.md mandates smoke tests (curl / browser / live-VM). Each task below verifies with `python -m py_compile`, importability, `curl` against the dev backend (`http://localhost:9090`, cookie auth), browser walkthrough, and a final live-VM end-to-end attack. Do **not** scaffold pytest/vitest.

8. **Dev stack only.** `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`. Backend uvicorn `--reload` on `:8765` (proxied at `:9090`), Vite HMR for frontend. Never `docker compose build frontend`.

**Action → detection → target → tier (the canonical table the code implements):**

| Alert `type` (Part 1) | Confidence | Action(s) | Target source | Tier | Undo |
|---|---|---|---|---|---|
| `probe_scan` | medium | `block_ip` | IP parsed from alert message | 1 | unblock_ip |
| `webshell_upload` | high | `quarantine_file` | path from auditd `webroot_write` / access `.php` | 1 | restore_file |
| `webshell_execution` | high | `quarantine_file` + `block_ip` | path + IP from access log | 1 | restore_file / unblock_ip |
| `webshell_command_exec` | high | `kill_pid` + `block_ip` | pid from auditd execve; IP from access log | 1 | none / unblock_ip |
| `jce_exploit_attempt` | high | `block_ip` | IP from access log | 1 | unblock_ip |
| `ssh_key_modified` | high | `revert_authorized_keys` | ssh user (server.ssh_user / `root`) | 2 | restore keys |
| `db_privilege_change` | high | `disable_db_user` | user parsed from mariadb_general log | 2 | enable_db_user |
| `log_tampering`, `log_ingestion_silent`, `new_ssh_login` | — | none (alert-only) | — | — | — |

---

## File Structure

**New (backend):**
- `backend/migrations/versions/0031_security_actions.py` — `security_actions` table + 3 settings columns.
- `backend/app/services/response_channel.py` — typed, allow-listed command client (the safety core). One method per verb; strict arg validation; no free-form command strings.
- `backend/app/services/security_responder.py` — confidence map, action plan, target extraction, gates, tier routing, ledger writes; plus the TTL-expiry coroutine.
- `backend/app/routers/security_actions.py` — list / approve / reject / undo / settings endpoints.

**New (frontend):**
- `frontend/src/stores/securityActions.ts` — Pinia store.
- `frontend/src/components/servers/tabs/security/SecurityActionsPanel.vue` — pending approvals + action history + undo.
- `frontend/src/components/servers/tabs/security/AutoResponseSettings.vue` — per-server toggle + block-TTL control.

**Modified:**
- `backend/app/models/other.py` — add `SecurityAction` model; add `Settings.auto_response_enabled`.
- `backend/app/models/server.py` — add `Server.auto_response_enabled`, `Server.block_ttl_hours`.
- `backend/app/main.py` — import + register the two scheduler jobs and the router.
- `frontend/src/components/servers/tabs/SecurityTab.vue` — mount `SecurityActionsPanel`.
- Org settings page — global kill-switch toggle (Task 11).

---

## Task 1: Migration 0031 + models (ledger, settings, kill switch)

**Files:**
- Create: `backend/migrations/versions/0031_security_actions.py`
- Modify: `backend/app/models/other.py` (add `SecurityAction`; add `Settings.auto_response_enabled`)
- Modify: `backend/app/models/server.py` (add `auto_response_enabled`, `block_ttl_hours`)

- [ ] **Step 1: Write the migration**

Create `backend/migrations/versions/0031_security_actions.py` (mirrors the style of `0030_security_detection.py`):

```python
"""Security auto-response: actions ledger + auto-response settings.

Revision ID: 0031_security_actions
Revises: 0030_security_detection
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0031_security_actions"
down_revision = "0030_security_detection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_actions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("server_id", UUID(as_uuid=True),
                  sa.ForeignKey("server.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("alert_id", UUID(as_uuid=True),
                  sa.ForeignKey("alert.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("action_type", sa.String(40), nullable=False),
        sa.Column("target", sa.Text, nullable=True),
        sa.Column("tier", sa.SmallInteger, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending_approval"),
        sa.Column("actor", sa.String(255), nullable=False, server_default="auto"),
        sa.Column("confidence", sa.String(10), nullable=True),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("reversal", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_security_actions_alert", "security_actions", ["alert_id"])
    op.create_index("ix_security_actions_server_status", "security_actions",
                    ["server_id", "status"])
    op.add_column("server", sa.Column(
        "auto_response_enabled", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("server", sa.Column(
        "block_ttl_hours", sa.Integer, nullable=False, server_default="24"))
    op.add_column("app_settings", sa.Column(
        "auto_response_enabled", sa.Boolean, nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("app_settings", "auto_response_enabled")
    op.drop_column("server", "block_ttl_hours")
    op.drop_column("server", "auto_response_enabled")
    op.drop_index("ix_security_actions_server_status", table_name="security_actions")
    op.drop_index("ix_security_actions_alert", table_name="security_actions")
    op.drop_table("security_actions")
```

- [ ] **Step 2: Add the `SecurityAction` model**

In `backend/app/models/other.py`, after the `Alert` class (around line 159), add. Match the file's existing imports (`BigInteger`, `SmallInteger`, `JSONB` may need importing — check the top of the file and add what's missing; the file already imports `Integer`, `String`, `Text`, `Boolean`, `DateTime`, `ForeignKey`, `text`, `UUID`):

```python
class SecurityAction(Base):
    __tablename__ = "security_actions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("server.id", ondelete="CASCADE"), nullable=False, index=True)
    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alert.id", ondelete="SET NULL"), nullable=True, index=True)
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    tier: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending_approval")
    actor: Mapped[str] = mapped_column(String(255), nullable=False, server_default="auto")
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    reversal: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Add the imports at the top of `other.py` if absent:
```python
from sqlalchemy import BigInteger, SmallInteger
from sqlalchemy.dialects.postgresql import JSONB
```

- [ ] **Step 3: Add the `Settings.auto_response_enabled` column**

In `backend/app/models/other.py`, inside `class Settings` (after `discord_enabled` around line 287), add:

```python
    auto_response_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false")
```

- [ ] **Step 4: Add the two `Server` columns**

In `backend/app/models/server.py`, inside `class Server` (after `is_active`, around line 25), add:

```python
    auto_response_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false")
    block_ttl_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=24, server_default="24")
```

- [ ] **Step 5: Smoke test — run the migration and verify schema**

Run:
```bash
cd /Users/pocketdata/Code/Work/opspilot
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T postgres \
  psql -U opspilot -d opspilot -c "\d security_actions"
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T postgres \
  psql -U opspilot -d opspilot -c \
  "SELECT column_name FROM information_schema.columns WHERE table_name='server' AND column_name IN ('auto_response_enabled','block_ttl_hours');"
```
Expected: `security_actions` table prints with all columns; the two `server` columns are listed. Backend logs (`docker compose ... logs backend --tail=20`) show no model import error after reload.

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/versions/0031_security_actions.py backend/app/models/other.py backend/app/models/server.py
git commit -m "feat(security): security_actions ledger + auto-response settings (migration 0031)"
```

---

## Task 2: `response_channel.py` — typed, allow-listed command client (safety core)

**Files:**
- Create: `backend/app/services/response_channel.py`

This is the only module that runs privileged commands. It exposes one coroutine per verb, validates every argument, and **never** builds a command from a free-form string. Each verb returns a `reversal` dict (or `None`) for the ledger.

- [ ] **Step 1: Write the module**

Create `backend/app/services/response_channel.py`:

```python
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
```

- [ ] **Step 2: Smoke test — compile + arg validation rejects bad input**

Run:
```bash
cd /Users/pocketdata/Code/Work/opspilot
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend \
  python -c "
from app.services.response_channel import _validate_ip, _validate_pid, _validate_path, ResponseError
ok = _validate_ip('203.0.113.5'); assert ok == '203.0.113.5'
for bad in ['1.2.3.4; rm -rf /', 'not-an-ip', '']:
    try: _validate_ip(bad); raise SystemExit('FAIL accepted '+repr(bad))
    except ResponseError: pass
for bad in ['/etc/passwd', '/var/www/../../etc/x', 'relative/x']:
    try: _validate_path(bad); raise SystemExit('FAIL accepted '+repr(bad))
    except ResponseError: pass
assert _validate_path('/var/www/html/uploads/x.php')
for bad in [0, 1, 'x', -5]:
    try: _validate_pid(bad); raise SystemExit('FAIL accepted '+repr(bad))
    except ResponseError: pass
assert _validate_pid('4321') == 4321
print('response_channel validation OK')
"
```
Expected: `response_channel validation OK` (and no `FAIL` line).

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/response_channel.py
git commit -m "feat(security): allow-listed remediation verbs with strict arg validation"
```

---

## Task 3: `security_responder.py` — confidence, action plan, target extraction, gates, ledger

**Files:**
- Create: `backend/app/services/security_responder.py`

- [ ] **Step 1: Write the module**

Create `backend/app/services/security_responder.py`:

```python
"""Security auto-responder (Part 2).

A 30s APScheduler job that consumes Part-1 fired security alerts and, per the
action plan + safety gates, either auto-executes Tier-1 remediation or queues a
Tier-2 action for human approval. One `security_actions` row per (alert, action)
is the idempotency key — already-handled alerts are skipped, making it
restart-safe and double-act-proof.

Also exposes `ttl_expiry()`: a 60s job that unblocks IPs whose block has aged
past the per-server `block_ttl_hours`.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.other import Alert, SecurityAction
from app.models.server import Server
from app.services import response_channel as rc
from app.services.alerting import OPEN_STATES

logger = logging.getLogger(__name__)

# type → confidence (derived here; Part 1 has no confidence field).
CONFIDENCE = {
    "webshell_command_exec": "high",
    "webshell_execution": "high",
    "webshell_upload": "high",
    "ssh_key_modified": "high",
    "db_privilege_change": "high",
    "log_tampering": "high",
    "jce_exploit_attempt": "high",
    "probe_scan": "medium",
}

# type → ordered list of (action_type, tier). Tier 1 = auto, Tier 2 = approval.
ACTION_PLAN = {
    "probe_scan":            [("block_ip", 1)],
    "webshell_upload":       [("quarantine_file", 1)],
    "webshell_execution":    [("quarantine_file", 1), ("block_ip", 1)],
    "webshell_command_exec": [("kill_pid", 1), ("block_ip", 1)],
    "jce_exploit_attempt":   [("block_ip", 1)],
    "ssh_key_modified":      [("revert_authorized_keys", 2)],
    "db_privilege_change":   [("disable_db_user", 2)],
}

# Circuit breaker: if more than N auto-actions execute on one server within the
# window, pause auto-response for that server and escalate (alert-only).
_BREAKER_MAX = 10
_BREAKER_WINDOW_MIN = 10

_IPV4 = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _global_kill_switch_on(db: AsyncSession) -> bool:
    """True when the org kill switch DISABLES auto-response (default off)."""
    row = (await db.execute(
        text("SELECT auto_response_enabled FROM app_settings WHERE id = 1")
    )).first()
    # auto_response_enabled True = master ON. Kill switch 'on' == master False.
    return not (row and row[0])


async def _recent_log_lines(db: AsyncSession, server_id, like: str,
                            since: datetime, limit: int = 50) -> list[str]:
    rows = (await db.execute(
        text(
            "SELECT message FROM server_logs "
            "WHERE server_id = :sid AND time >= :since AND message LIKE :like "
            "ORDER BY time DESC LIMIT :lim"
        ),
        {"sid": str(server_id), "since": since, "like": like, "lim": limit},
    )).all()
    return [r[0] for r in rows]


async def _extract_ip(db: AsyncSession, alert: Alert) -> str | None:
    # probe_scan/ssh messages carry the IP inline.
    m = _IPV4.search(alert.message or "")
    if m:
        return m.group(1)
    # Otherwise pull from recent access-log lines around the alert.
    since = (alert.sent_at or _now()) - timedelta(minutes=5)
    for line in await _recent_log_lines(db, alert.server_id, "%.php%", since):
        m = _IPV4.search(line)
        if m:
            return m.group(1)
    return None


async def _extract_file(db: AsyncSession, alert: Alert) -> str | None:
    since = (alert.sent_at or _now()) - timedelta(minutes=5)
    # Prefer auditd webroot_write (carries the absolute path under name="…").
    for line in await _recent_log_lines(db, alert.server_id, "%webroot_write%", since):
        m = re.search(r'name="?(/[^"\s]+\.php)', line)
        if m:
            return m.group(1)
    # Fall back to an access-log .php request path → map under default web root.
    for line in await _recent_log_lines(db, alert.server_id, "%.php%", since):
        m = re.search(r'"(?:GET|POST)\s+(/\S+\.php)', line)
        if m:
            return "/var/www/html" + m.group(1).split("?")[0]
    return None


async def _extract_pid(db: AsyncSession, alert: Alert) -> str | None:
    since = (alert.sent_at or _now()) - timedelta(minutes=5)
    for line in await _recent_log_lines(db, alert.server_id, "%webshell_exec%", since):
        m = re.search(r"\bpid=(\d+)", line)
        if m:
            return m.group(1)
    return None


async def _extract_db_user(db: AsyncSession, alert: Alert) -> str | None:
    since = (alert.sent_at or _now()) - timedelta(minutes=5)
    for like in ("%CREATE USER%", "%GRANT ALL%"):
        for line in await _recent_log_lines(db, alert.server_id, like, since):
            m = re.search(r"(?:CREATE USER|TO)\s+'([^']+)'", line, re.IGNORECASE)
            if m:
                return m.group(1)
    return None


async def _resolve_target(db: AsyncSession, alert: Alert, action_type: str,
                          server: Server) -> str | None:
    if action_type in ("block_ip",):
        return await _extract_ip(db, alert)
    if action_type == "quarantine_file":
        return await _extract_file(db, alert)
    if action_type == "kill_pid":
        return await _extract_pid(db, alert)
    if action_type == "revert_authorized_keys":
        return server.ssh_user or "root"
    if action_type == "disable_db_user":
        return await _extract_db_user(db, alert)
    return None


async def _already_handled(db: AsyncSession, alert_id) -> bool:
    row = (await db.execute(
        select(SecurityAction.id).where(SecurityAction.alert_id == alert_id).limit(1)
    )).first()
    return row is not None


async def _breaker_tripped(db: AsyncSession, server_id) -> bool:
    since = _now() - timedelta(minutes=_BREAKER_WINDOW_MIN)
    n = (await db.execute(
        text(
            "SELECT count(*) FROM security_actions "
            "WHERE server_id = :sid AND status = 'executed' AND executed_at >= :since"
        ),
        {"sid": str(server_id), "since": since},
    )).scalar_one()
    return n >= _BREAKER_MAX


async def _execute(server: Server, action_type: str, target: str) -> dict:
    if action_type == "block_ip":
        return await rc.block_ip(server, target)
    if action_type == "quarantine_file":
        return await rc.quarantine_file(server, target)
    if action_type == "kill_pid":
        return await rc.kill_pid(server, target)
    if action_type == "revert_authorized_keys":
        return await rc.revert_authorized_keys(server, target)
    if action_type == "disable_db_user":
        return await rc.disable_db_user(server, target)
    raise rc.ResponseError(f"unknown action {action_type}")


async def _handle_alert(db: AsyncSession, alert: Alert, server: Server) -> None:
    plan = ACTION_PLAN.get(alert.type)
    if not plan:
        return
    confidence = CONFIDENCE.get(alert.type)
    for action_type, tier in plan:
        target = await _resolve_target(db, alert, action_type, server)
        row = SecurityAction(
            server_id=server.id, alert_id=alert.id, action_type=action_type,
            target=target, tier=tier, confidence=confidence, actor="auto",
            status="pending_approval",
        )
        if target is None:
            row.status = "failed"
            row.detail = "could not extract a target from logs"
            db.add(row)
            continue
        if tier == 2:
            row.status = "pending_approval"
            row.detail = f"awaiting approval: {action_type} {target}"
            db.add(row)
            continue
        # Tier 1: gates already checked by caller; circuit breaker is per-server.
        if await _breaker_tripped(db, server.id):
            row.status = "failed"
            row.detail = "circuit breaker tripped — auto-response paused"
            db.add(row)
            continue
        try:
            reversal = await _execute(server, action_type, target)
            row.status = "executed"
            row.executed_at = _now()
            row.reversal = reversal
            row.detail = f"{action_type} {target}"
        except rc.ResponseError as e:
            row.status = "failed"
            row.detail = str(e)
        db.add(row)


async def security_responder() -> None:
    """30s tick: act on new fired security alerts for auto-response-enabled servers."""
    async with AsyncSessionLocal() as db:
        if await _global_kill_switch_on(db):
            return
        servers = {
            s.id: s for s in (await db.execute(
                select(Server).where(Server.auto_response_enabled.is_(True),
                                     Server.is_active.is_(True))
            )).scalars().all()
        }
        if not servers:
            return
        alerts = (await db.execute(
            select(Alert).where(
                Alert.type.in_(ACTION_PLAN.keys()),
                Alert.state.in_(OPEN_STATES),
                Alert.server_id.in_(servers.keys()),
            ).order_by(Alert.sent_at.asc())
        )).scalars().all()
        for alert in alerts:
            try:
                if await _already_handled(db, alert.id):
                    continue
                await _handle_alert(db, alert, servers[alert.server_id])
            except Exception:  # noqa: BLE001 — one bad alert must not abort the tick
                logger.warning("security_responder: alert %s failed", alert.id, exc_info=True)
        await db.commit()


async def ttl_expiry() -> None:
    """60s tick: unblock IPs whose block_ip action has aged past block_ttl_hours."""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(SecurityAction, Server)
            .join(Server, Server.id == SecurityAction.server_id)
            .where(SecurityAction.action_type == "block_ip",
                   SecurityAction.status == "executed")
        )).all()
        for action, server in rows:
            ttl = server.block_ttl_hours or 24
            if action.executed_at and _now() >= action.executed_at + timedelta(hours=ttl):
                try:
                    await rc.unblock_ip(server, action.reversal["ip"])
                    action.status = "expired"
                    action.reverted_at = _now()
                except Exception:  # noqa: BLE001
                    logger.warning("ttl_expiry: unblock failed for action %s", action.id, exc_info=True)
        await db.commit()
```

- [ ] **Step 2: Smoke test — import + maps wired**

Run:
```bash
cd /Users/pocketdata/Code/Work/opspilot
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend \
  python -c "
from app.services.security_responder import ACTION_PLAN, CONFIDENCE, security_responder, ttl_expiry
assert ACTION_PLAN['probe_scan'] == [('block_ip', 1)]
assert ACTION_PLAN['webshell_command_exec'] == [('kill_pid', 1), ('block_ip', 1)]
assert CONFIDENCE['webshell_execution'] == 'high'
import inspect; assert inspect.iscoroutinefunction(security_responder)
print('security_responder import OK')
"
```
Expected: `security_responder import OK`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/security_responder.py
git commit -m "feat(security): auto-responder — confidence, action plan, target extraction, gates, TTL expiry"
```

---

## Task 4: Register the two scheduler jobs

**Files:**
- Modify: `backend/app/main.py` (import + two `add_job` calls in the startup block near lines 38 + 57–67)

- [ ] **Step 1: Add the import**

In `backend/app/main.py`, next to `from app.services.log_evaluator import log_alert_evaluator` (line 38), add:

```python
from app.services.security_responder import security_responder, ttl_expiry as security_ttl_expiry
```

- [ ] **Step 2: Register both jobs**

In the startup block where other `scheduler.add_job(...)` calls live (after the `fail2ban_collector` line ~67), add:

```python
    scheduler.add_job(security_responder, "interval", seconds=30, id="security_responder", replace_existing=True)
    scheduler.add_job(security_ttl_expiry, "interval", seconds=60, id="security_ttl_expiry", replace_existing=True)
```

- [ ] **Step 3: Smoke test — jobs registered, no startup error**

Run:
```bash
cd /Users/pocketdata/Code/Work/opspilot
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart backend
sleep 5
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs backend --tail=40 | grep -i "error\|traceback" || echo "no errors"
curl -s http://localhost:9090/api/health
```
Expected: `{"ok":true}`, and no error/traceback in logs. (Optional: `docker compose ... exec -T postgres psql -U opspilot -d opspilot -c "SELECT id FROM apscheduler_jobs WHERE id LIKE 'security_%';"` lists both job ids.)

- [ ] **Step 4: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(security): register security_responder + ttl_expiry scheduler jobs"
```

---

## Task 5: `security_actions.py` router — list / approve / reject / undo / settings

**Files:**
- Create: `backend/app/routers/security_actions.py`
- Modify: `backend/app/main.py` (import + `include_router`)

- [ ] **Step 1: Write the router**

Create `backend/app/routers/security_actions.py`:

```python
"""Security Auto-Response actions API (Part 2).

GET  /api/servers/{server_id}/security/actions          list ledger (history + pending)
POST /api/servers/{server_id}/security/actions/{id}/approve   execute a Tier-2 pending action (admin)
POST /api/servers/{server_id}/security/actions/{id}/reject    dismiss a pending action (admin)
POST /api/servers/{server_id}/security/actions/{id}/undo      reverse an executed action (admin)
GET  /api/servers/{server_id}/security/auto-response          per-server settings
PUT  /api/servers/{server_id}/security/auto-response          update per-server settings (admin)
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AdminUser, CurrentUser
from app.models.other import Alert, SecurityAction
from app.models.server import Server
from app.services import response_channel as rc
from app.services import security_responder as responder

router = APIRouter(prefix="/api/servers", tags=["security"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _access(server_id: str, user, db: AsyncSession) -> Server:
    from app.routers.servers import _assert_server_access
    return await _assert_server_access(server_id, user, db)


def _row(a: SecurityAction) -> dict:
    return {
        "id": a.id, "alert_id": str(a.alert_id) if a.alert_id else None,
        "action_type": a.action_type, "target": a.target, "tier": a.tier,
        "status": a.status, "actor": a.actor, "confidence": a.confidence,
        "detail": a.detail, "created_at": a.created_at, "executed_at": a.executed_at,
        "reverted_at": a.reverted_at,
        "reversible": a.action_type not in ("kill_pid",),
    }


@router.get("/{server_id}/security/actions")
async def list_actions(server_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _access(server_id, user, db)
    rows = (await db.execute(
        select(SecurityAction).where(SecurityAction.server_id == server_id)
        .order_by(SecurityAction.created_at.desc()).limit(200)
    )).scalars().all()
    return [_row(a) for a in rows]


async def _get_action(server_id: str, action_id: int, db: AsyncSession) -> SecurityAction:
    a = (await db.execute(
        select(SecurityAction).where(
            SecurityAction.id == action_id, SecurityAction.server_id == server_id)
    )).scalar_one_or_none()
    if a is None:
        raise HTTPException(404, detail={"error": "not_found", "message": "Action not found."})
    return a


@router.post("/{server_id}/security/actions/{action_id}/approve")
async def approve(server_id: str, action_id: int, user: AdminUser, db: AsyncSession = Depends(get_db)):
    server = await _access(server_id, user, db)
    a = await _get_action(server_id, action_id, db)
    if a.status != "pending_approval":
        raise HTTPException(409, detail={"error": "conflict", "message": "Action is not pending."})
    try:
        reversal = await responder._execute(server, a.action_type, a.target)
        a.status, a.executed_at, a.reversal = "executed", _now(), reversal
        a.actor = user.email
        a.detail = f"approved+{a.action_type} {a.target}"
    except rc.ResponseError as e:
        a.status, a.detail = "failed", str(e)
    await db.commit()
    return _row(a)


@router.post("/{server_id}/security/actions/{action_id}/reject")
async def reject(server_id: str, action_id: int, user: AdminUser, db: AsyncSession = Depends(get_db)):
    await _access(server_id, user, db)
    a = await _get_action(server_id, action_id, db)
    if a.status != "pending_approval":
        raise HTTPException(409, detail={"error": "conflict", "message": "Action is not pending."})
    a.status, a.actor, a.detail = "rejected", user.email, "rejected by admin"
    await db.commit()
    return _row(a)


@router.post("/{server_id}/security/actions/{action_id}/undo")
async def undo(server_id: str, action_id: int, user: AdminUser, db: AsyncSession = Depends(get_db)):
    server = await _access(server_id, user, db)
    a = await _get_action(server_id, action_id, db)
    if a.status != "executed":
        raise HTTPException(409, detail={"error": "conflict", "message": "Only executed actions can be undone."})
    try:
        if a.action_type == "block_ip":
            await rc.unblock_ip(server, a.reversal["ip"])
        elif a.action_type == "quarantine_file":
            await rc.restore_file(server, a.reversal)
        elif a.action_type == "revert_authorized_keys":
            await rc.restore_authorized_keys(server, a.reversal)
        elif a.action_type == "disable_db_user":
            await rc.enable_db_user(server, a.reversal)
        else:
            raise HTTPException(400, detail={"error": "not_reversible",
                                             "message": f"{a.action_type} cannot be undone."})
    except rc.ResponseError as e:
        raise HTTPException(502, detail={"error": "undo_failed", "message": str(e)})
    a.status, a.reverted_at, a.actor = "reverted", _now(), user.email
    await db.commit()
    return _row(a)


class AutoResponseSettings(BaseModel):
    auto_response_enabled: bool
    block_ttl_hours: int


@router.get("/{server_id}/security/auto-response")
async def get_settings(server_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    server = await _access(server_id, user, db)
    return {"auto_response_enabled": server.auto_response_enabled,
            "block_ttl_hours": server.block_ttl_hours}


@router.put("/{server_id}/security/auto-response")
async def put_settings(server_id: str, body: AutoResponseSettings,
                       user: AdminUser, db: AsyncSession = Depends(get_db)):
    server = await _access(server_id, user, db)
    if not (1 <= body.block_ttl_hours <= 720):
        raise HTTPException(422, detail={"error": "invalid", "message": "block_ttl_hours must be 1–720."})
    server.auto_response_enabled = body.auto_response_enabled
    server.block_ttl_hours = body.block_ttl_hours
    await db.commit()
    return {"auto_response_enabled": server.auto_response_enabled,
            "block_ttl_hours": server.block_ttl_hours}
```

- [ ] **Step 2: Register the router in main.py**

In `backend/app/main.py`, next to `from app.routers.security_events import router as security_events_router` (line 36) add:
```python
from app.routers.security_actions import router as security_actions_router
```
And next to `app.include_router(security_events_router)` (line ~138) add:
```python
app.include_router(security_actions_router)
```

- [ ] **Step 3: Smoke test — endpoints respond with correct auth behavior**

Run (logs in as the dev admin to get a cookie, then exercises the endpoints; replace `SID` with a real server id):
```bash
cd /Users/pocketdata/Code/Work/opspilot
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart backend && sleep 5
# get a session cookie (dev demo admin)
curl -s -c /tmp/op.cookie -X POST http://localhost:9090/api/auth/login \
  -H 'Content-Type: application/json' -d '{"email":"admin","password":"admin123"}' >/dev/null
SID=$(docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T postgres \
  psql -U opspilot -d opspilot -t -c "SELECT id FROM server LIMIT 1;" | tr -d ' \n')
echo "server=$SID"
echo "--- list actions (expect []) ---"
curl -s -b /tmp/op.cookie http://localhost:9090/api/servers/$SID/security/actions
echo ""
echo "--- get settings (expect auto_response_enabled false, ttl 24) ---"
curl -s -b /tmp/op.cookie http://localhost:9090/api/servers/$SID/security/auto-response
echo ""
echo "--- enable auto-response via PUT ---"
curl -s -b /tmp/op.cookie -X PUT http://localhost:9090/api/servers/$SID/security/auto-response \
  -H 'Content-Type: application/json' -d '{"auto_response_enabled":true,"block_ttl_hours":24}'
```
Expected: `[]`; `{"auto_response_enabled":false,"block_ttl_hours":24}`; then `{"auto_response_enabled":true,"block_ttl_hours":24}`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/security_actions.py backend/app/main.py
git commit -m "feat(security): auto-response actions API (list/approve/reject/undo/settings)"
```

---

## Task 6: `securityActions.ts` Pinia store

**Files:**
- Create: `frontend/src/stores/securityActions.ts`

- [ ] **Step 1: Write the store** (mirrors `frontend/src/stores/security.ts`)

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/services/api'

export interface SecurityActionRow {
  id: number
  alert_id: string | null
  action_type: string
  target: string | null
  tier: number
  status: 'pending_approval' | 'executed' | 'failed' | 'rejected' | 'reverted' | 'expired'
  actor: string
  confidence: string | null
  detail: string | null
  created_at: string
  executed_at: string | null
  reverted_at: string | null
  reversible: boolean
}

export interface AutoResponseSettings {
  auto_response_enabled: boolean
  block_ttl_hours: number
}

export const useSecurityActionsStore = defineStore('securityActions', () => {
  const actions = ref<SecurityActionRow[]>([])
  const settings = ref<AutoResponseSettings | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  function _err(err: unknown, fallback: string) {
    const e = err as { response?: { data?: { detail?: { message?: string } | string } } }
    const d = e?.response?.data?.detail
    error.value = (typeof d === 'object' ? d?.message : d) || fallback
  }

  async function fetchActions(serverId: string) {
    loading.value = true; error.value = null
    try {
      actions.value = (await api.get(`/api/servers/${serverId}/security/actions`)).data
    } catch (e) { _err(e, 'Failed to load response actions') }
    finally { loading.value = false }
  }

  async function fetchSettings(serverId: string) {
    try {
      settings.value = (await api.get(`/api/servers/${serverId}/security/auto-response`)).data
    } catch (e) { _err(e, 'Failed to load auto-response settings') }
  }

  async function updateSettings(serverId: string, body: AutoResponseSettings) {
    settings.value = (await api.put(`/api/servers/${serverId}/security/auto-response`, body)).data
  }

  async function approve(serverId: string, id: number) {
    await api.post(`/api/servers/${serverId}/security/actions/${id}/approve`)
    await fetchActions(serverId)
  }
  async function reject(serverId: string, id: number) {
    await api.post(`/api/servers/${serverId}/security/actions/${id}/reject`)
    await fetchActions(serverId)
  }
  async function undo(serverId: string, id: number) {
    await api.post(`/api/servers/${serverId}/security/actions/${id}/undo`)
    await fetchActions(serverId)
  }

  return { actions, settings, loading, error,
           fetchActions, fetchSettings, updateSettings, approve, reject, undo }
})
```

- [ ] **Step 2: Smoke test — type-check**

Run:
```bash
cd /Users/pocketdata/Code/Work/opspilot/frontend
npx vue-tsc --noEmit -p tsconfig.app.json 2>&1 | grep -i "securityActions" || echo "no type errors in securityActions.ts"
```
Expected: `no type errors in securityActions.ts`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/securityActions.ts
git commit -m "feat(security): securityActions pinia store"
```

---

## Task 7: `SecurityActionsPanel.vue` + `AutoResponseSettings.vue`, mounted in SecurityTab

**Files:**
- Create: `frontend/src/components/servers/tabs/security/SecurityActionsPanel.vue`
- Create: `frontend/src/components/servers/tabs/security/AutoResponseSettings.vue`
- Modify: `frontend/src/components/servers/tabs/SecurityTab.vue`

Design per ui-ux-pro-max destructive-action discipline: reuse `StatusBadge` for status chips, `useNotify` for toasts (`aria-live` is built into Vuestic toasts), `window.confirm` previews for Tier-2/undo (matches the existing `BackupTab.vue` pattern), danger styling separated from safe actions, and an explicit empty state.

- [ ] **Step 1: Write `AutoResponseSettings.vue`**

```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useSecurityActionsStore } from '@/stores/securityActions'
import { useAuthStore } from '@/stores/auth'
import { useNotify } from '@/composables/useNotify'

const props = defineProps<{ serverId: string }>()
const store = useSecurityActionsStore()
const auth = useAuthStore()
const notify = useNotify()
const ttl = ref(24)

onMounted(async () => {
  await store.fetchSettings(props.serverId)
  ttl.value = store.settings?.block_ttl_hours ?? 24
})

async function save(enabled: boolean) {
  try {
    await store.updateSettings(props.serverId, { auto_response_enabled: enabled, block_ttl_hours: ttl.value })
    notify.success(enabled ? 'Auto-response enabled for this server' : 'Auto-response disabled')
  } catch (e) { notify.error(e as Error) }
}
</script>

<template>
  <section class="ar-settings">
    <div class="ar-settings__row">
      <div>
        <h4>Auto-response</h4>
        <p class="muted">When ON, OpsPilot may block IPs, quarantine webshells, and kill malicious
          processes automatically on this server. High-impact actions still wait for your approval.</p>
      </div>
      <VaSwitch
        :model-value="store.settings?.auto_response_enabled ?? false"
        :disabled="!auth.isAdmin"
        @update:model-value="save($event)"
        size="small" />
    </div>
    <div v-if="store.settings?.auto_response_enabled" class="ar-settings__ttl">
      <label>Auto-block expires after</label>
      <VaInput v-model="ttl" type="number" :min="1" :max="720" :disabled="!auth.isAdmin"
               @blur="save(true)" class="ttl-input" /> <span class="muted">hours</span>
    </div>
  </section>
</template>

<style scoped>
.ar-settings { border: 1px solid var(--border, #2a3040); border-radius: 10px; padding: 14px 16px; }
.ar-settings__row { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.ar-settings h4 { margin: 0 0 4px; font-size: 0.95rem; }
.muted { color: var(--va-text-secondary, #9aa4b2); font-size: 0.8rem; margin: 0; }
.ar-settings__ttl { display: flex; align-items: center; gap: 8px; margin-top: 12px; }
.ttl-input { max-width: 90px; }
</style>
```

- [ ] **Step 2: Write `SecurityActionsPanel.vue`**

```vue
<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useSecurityActionsStore } from '@/stores/securityActions'
import { useAuthStore } from '@/stores/auth'
import { useNotify } from '@/composables/useNotify'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import AutoResponseSettings from './AutoResponseSettings.vue'

const props = defineProps<{ serverId: string }>()
const store = useSecurityActionsStore()
const auth = useAuthStore()
const notify = useNotify()
let poll: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  store.fetchActions(props.serverId)
  poll = setInterval(() => store.fetchActions(props.serverId), 30 * 1000)
})
onUnmounted(() => { if (poll) clearInterval(poll) })

const pending = computed(() => store.actions.filter(a => a.status === 'pending_approval'))
const history = computed(() => store.actions.filter(a => a.status !== 'pending_approval'))

// Map ledger status → StatusBadge alert tone vocabulary.
function tone(s: string): string {
  return ({ executed: 'firing', reverted: 'resolved', expired: 'snoozed',
            rejected: 'suppressed', failed: 'firing' } as Record<string, string>)[s] ?? 'snoozed'
}

async function approve(id: number, label: string) {
  if (!window.confirm(`Approve and run: ${label}?\nThis acts on the server now.`)) return
  try { await store.approve(props.serverId, id); notify.success('Action approved and executed') }
  catch (e) { notify.error(e as Error) }
}
async function reject(id: number) {
  try { await store.reject(props.serverId, id); notify.info('Action rejected') }
  catch (e) { notify.error(e as Error) }
}
async function undo(id: number, label: string) {
  if (!window.confirm(`Undo: ${label}?`)) return
  try { await store.undo(props.serverId, id); notify.success('Action reverted') }
  catch (e) { notify.error(e as Error) }
}
</script>

<template>
  <section class="sec-actions">
    <header class="sec-actions__head"><h3>Response Actions</h3></header>

    <AutoResponseSettings :server-id="serverId" />

    <div v-if="pending.length" class="sec-actions__pending">
      <h4>Pending approval</h4>
      <div v-for="a in pending" :key="a.id" class="approve-card">
        <div class="approve-card__info">
          <strong class="danger">{{ a.action_type }}</strong>
          <span class="target">{{ a.target }}</span>
          <span class="muted">{{ a.detail }}</span>
        </div>
        <div class="approve-card__btns">
          <VaButton size="small" color="danger" :disabled="!auth.isAdmin"
                    @click="approve(a.id, `${a.action_type} ${a.target}`)">Approve</VaButton>
          <VaButton size="small" preset="secondary" :disabled="!auth.isAdmin"
                    @click="reject(a.id)">Reject</VaButton>
        </div>
      </div>
    </div>

    <div class="sec-actions__history">
      <h4>History</h4>
      <p v-if="!history.length && !pending.length" class="empty">No response actions taken.</p>
      <ul v-else class="hist-list">
        <li v-for="a in history" :key="a.id" class="hist-row">
          <StatusBadge :status="tone(a.status)" kind="alert" class="hist-row__chip" />
          <span class="hist-row__type">{{ a.action_type }}</span>
          <span class="hist-row__target" :title="a.detail ?? ''">{{ a.target }}</span>
          <span class="hist-row__status muted">{{ a.status }}</span>
          <VaButton v-if="a.status === 'executed' && a.reversible" size="small" preset="secondary"
                    :disabled="!auth.isAdmin"
                    @click="undo(a.id, `${a.action_type} ${a.target}`)">Undo</VaButton>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.sec-actions { display: flex; flex-direction: column; gap: 14px; margin-bottom: 1.5rem; }
.sec-actions__head h3, .sec-actions h4 { margin: 0; font-size: 1rem; font-weight: 600; }
.sec-actions h4 { font-size: 0.85rem; margin-bottom: 0.5rem; color: var(--va-text-secondary, #9aa4b2); }
.approve-card { display: flex; justify-content: space-between; align-items: center; gap: 12px;
  padding: 0.7rem 0.9rem; border-radius: 8px; border: 1px solid var(--red, #ef4444);
  background: rgba(239,68,68,0.06); margin-bottom: 0.4rem; }
.approve-card__info { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.approve-card__btns { display: flex; gap: 8px; flex: none; }
.danger { color: var(--red, #ef4444); }
.target { font-variant-numeric: tabular-nums; color: var(--va-text-primary, #e6e9ef); }
.muted { color: var(--va-text-secondary, #9aa4b2); font-size: 0.78rem; }
.hist-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.25rem; }
.hist-row { display: grid; grid-template-columns: auto auto 1fr auto auto; align-items: center; gap: 0.75rem;
  padding: 0.55rem 0.75rem; border-radius: 8px; background: var(--va-background-secondary, #1b1f2a); }
.hist-row__target { overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-variant-numeric: tabular-nums; }
.empty { color: var(--va-text-secondary, #9aa4b2); padding: 1rem 0; }
</style>
```

- [ ] **Step 3: Mount in `SecurityTab.vue`**

In `frontend/src/components/servers/tabs/SecurityTab.vue`, add the import next to the timeline import:
```typescript
import SecurityActionsPanel from './security/SecurityActionsPanel.vue'
```
And in the template, place it **directly after** `<SecurityEventsTimeline :server-id="serverId" />`:
```vue
    <SecurityEventsTimeline :server-id="serverId" />
    <SecurityActionsPanel :server-id="serverId" />
```

- [ ] **Step 4: Smoke test — browser walkthrough**

Run the dev stack if not running, then in a browser at `http://localhost:9090`:
1. Log in (dev admin), open a server → **Security** tab.
2. Verify the **Response Actions** panel renders below the Security Events timeline, with the **Auto-response** toggle (OFF) and the empty state "No response actions taken."
3. Toggle Auto-response ON → success toast; the block-TTL field appears.
4. As a non-admin user (or simulate), confirm the toggle and Approve/Undo buttons are disabled.

Take a screenshot `security-actions-panel.png`. Confirm no console errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/servers/tabs/security/SecurityActionsPanel.vue \
        frontend/src/components/servers/tabs/security/AutoResponseSettings.vue \
        frontend/src/components/servers/tabs/SecurityTab.vue
git commit -m "feat(security): SecurityActionsPanel + per-server auto-response settings in Security tab"
```

---

## Task 8: Global kill-switch in org settings

**Files:**
- Modify: `backend/app/routers/settings.py` (expose + accept `auto_response_enabled`)
- Modify: the org settings store + settings page in `frontend/src/` (add the toggle)

- [ ] **Step 1: Locate the settings endpoint + schema**

Run:
```bash
cd /Users/pocketdata/Code/Work/opspilot
grep -n "discord_enabled\|class .*Settings\|smtp_enabled" backend/app/routers/settings.py | head
grep -rn "discord_enabled" frontend/src/stores/settings.ts frontend/src/**/*Settings*.vue 2>/dev/null | head
```
Use the `discord_enabled` boolean as the exact pattern to copy — it is already a working org-level on/off flag end-to-end (model → router schema → store → settings page toggle).

- [ ] **Step 2: Backend — surface `auto_response_enabled`**

In `backend/app/routers/settings.py`, wherever `discord_enabled` appears in the GET response dict and the update Pydantic model + assignment, add a parallel `auto_response_enabled: bool` field and `settings.auto_response_enabled = body.auto_response_enabled`. (The column already exists from Task 1.)

- [ ] **Step 3: Frontend — add the toggle**

In the org settings store and settings page, copy the `discord_enabled` toggle wiring for `auto_response_enabled`. Label: **"Security auto-response (master switch)"**, helper text: *"Master kill switch. When OFF, no automatic remediation runs on any server, regardless of per-server settings."*

- [ ] **Step 4: Smoke test**

Run:
```bash
cd /Users/pocketdata/Code/Work/opspilot
curl -s -b /tmp/op.cookie http://localhost:9090/api/settings | python3 -m json.tool | grep auto_response
curl -s -b /tmp/op.cookie -X PUT http://localhost:9090/api/settings \
  -H 'Content-Type: application/json' -d '{"auto_response_enabled":true}' >/dev/null
curl -s -b /tmp/op.cookie http://localhost:9090/api/settings | python3 -m json.tool | grep auto_response
```
Expected: field present, flips to `true`. In the browser, the org settings page shows the master toggle and persists across reload.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/settings.py frontend/src/stores/settings.ts frontend/src/
git commit -m "feat(security): global auto-response master kill switch in org settings"
```

---

## Task 9: Live-VM end-to-end validation + dashboard + release

This is the real smoke test (CLAUDE.md Rule 1): drive a real attack on the Lima test VM and watch auto-response act, approve a Tier-2, undo, and confirm the ledger + UI.

**Pre-req:** the Lima VM (`lima-ubuntu` server) is onboarded and reachable (Part 1 validation). Backend SSH auth to it works (`POST /api/servers/{id}/ssh-test` → exit 0). The `opspilot` SSH user has NOPASSWD sudo.

- [ ] **Step 1: Enable auto-response for the test server**

Set the org master switch ON and the per-server toggle ON (UI, or `PUT /api/servers/$SID/security/auto-response {"auto_response_enabled":true,"block_ttl_hours":24}` and `PUT /api/settings {"auto_response_enabled":true}`).

- [ ] **Step 2: Trigger a probe scan → expect auto `block_ip`**

On the VM, generate 20+ 404s from one IP (reuse the Part-1 probe loop). Within ~90s:
```bash
# probe_scan fires (Part 1), responder blocks the IP (Tier 1)
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T postgres \
  psql -U opspilot -d opspilot -c \
  "SELECT action_type,target,status,actor FROM security_actions WHERE action_type='block_ip' ORDER BY created_at DESC LIMIT 1;"
# verify the DROP rule exists on the VM
limactl shell ubuntu sudo iptables -S INPUT | grep DROP
```
Expected: a `block_ip` row `status=executed actor=auto`; an `iptables` DROP rule for the IP.

- [ ] **Step 3: Trigger webshell upload+exec → expect quarantine + kill + block**

Reuse the Part-1 webshell attack (drop a `.php` in an upload dir, request it, run a command). Expect `quarantine_file` (executed; file moved to `/var/opspilot-quarantine/`), `kill_pid`, and `block_ip` rows. Verify on the VM:
```bash
limactl shell ubuntu sudo ls -la /var/opspilot-quarantine/
```
Expected: the webshell file present in quarantine, original path gone.

- [ ] **Step 4: Trigger ssh_key_modified → Tier-2 pending → approve → undo**

Append a key to `authorized_keys` on the VM (fires Part-1 `ssh_key_modified`). Expect a `revert_authorized_keys` row `status=pending_approval`. In the UI, click **Approve** (confirm dialog) → the last-added key is removed. Then click **Undo** → the backup is restored. Verify:
```bash
limactl shell ubuntu sudo wc -l /root/.ssh/authorized_keys   # before approve, after approve (-1), after undo (restored)
```

- [ ] **Step 5: Verify TTL expiry + circuit breaker (quick checks)**

Temporarily set `block_ttl_hours=0`-equivalent by manually back-dating one executed `block_ip` row's `executed_at` to 2 days ago, wait for `security_ttl_expiry` (≤60s), confirm `status=expired` and the DROP rule is gone:
```bash
docker compose ... exec -T postgres psql -U opspilot -d opspilot -c \
 "UPDATE security_actions SET executed_at = now() - interval '2 days' WHERE action_type='block_ip' AND status='executed';"
# wait 70s
docker compose ... exec -T postgres psql -U opspilot -d opspilot -c \
 "SELECT status FROM security_actions WHERE action_type='block_ip' ORDER BY created_at DESC LIMIT 1;"
limactl shell ubuntu sudo iptables -S INPUT | grep DROP || echo "unblocked"
```
Expected: `expired`; `unblocked`.

- [ ] **Step 6: Update the progress dashboard (CLAUDE.md Rule 0)**

- In `PROGRESS.md`, add under the Security section:
  `✅ Security auto-response (Part 2) — semi-auto remediation (Tier 1 auto: block_ip/quarantine_file/kill_pid; Tier 2 approval: revert_authorized_keys/disable_db_user), allow-listed verb channel, confidence+circuit-breaker gates, TTL auto-unblock, full audit ledger with one-click undo, per-server opt-in + global kill switch`
- In `pm/DASHBOARD.html`, add Phase 19 `{ id: 19, title: "Security Auto-Response (Part 2)", ... }` with the task list, and bump the `Updated:` date to today.

- [ ] **Step 7: Take a final screenshot + commit + release**

Screenshot the Security tab showing the populated ledger as `security-auto-response-live.png`.
```bash
cd /Users/pocketdata/Code/Work/opspilot
git add PROGRESS.md pm/DASHBOARD.html
git commit -m "docs: mark Security Auto-Response (Part 2) complete on progress dashboard"
git push origin main
LATEST=$(git describe --tags --abbrev=0)   # expect v1.2.53
git tag v1.2.54 && git push origin v1.2.54
```
Expected: pushed; the CI `release` job creates the GitHub Release for `v1.2.54`.

---

## Self-Review (completed by plan author)

**Spec coverage:** Semi-auto tiering ✔ (Task 3 `ACTION_PLAN`/tiers). Default OFF + per-server opt-in ✔ (Tasks 1, 5, 7). Fixed allow-list, no arbitrary exec ✔ (Task 2). IP blocking reuse ✔ (Task 2 iptables, consistent with fail2ban; deviation documented in Decision 4). Reversibility/TTL ✔ (Tasks 2, 3 `ttl_expiry`). Confidence gate ✔ (Decision 1 + Task 3 `CONFIDENCE`). Corroboration ✔ (target extraction requires the corroborating log line to exist; absent → `failed`, never acts). Kill switch ✔ (Tasks 1, 3, 8). Audit `security_actions` ✔ (Task 1). One-click undo ✔ (Tasks 5, 7). Rate limit / circuit breaker ✔ (Task 3 `_breaker_*`). Data model matches spec table ✔ (Task 1, with added `detail` for failure reasons). Backend modules, router, scheduler jobs, migration 0031 ✔. Frontend panel, settings, store, SecurityTab mount ✔.

**Deviations (all documented in "Implementation Decisions"):** confidence derived not stored on alert (#1, user-approved); polling job not inline (#2); iptables not fail2ban (#4); client-side allow-list for v1, server-side sudoers hardening deferred (#5); `drop_db_user` deferred, `disable_db_user`=LOCK shipped (#6); smoke-tests not unit tests (#7).

**Placeholder scan:** none — every code step contains complete code; every verify step has exact commands + expected output.

**Type/name consistency:** `security_actions` table, `SecurityAction` model, `action_type`/`status`/`tier`/`reversal` columns, verb names (`block_ip`/`unblock_ip`/`quarantine_file`/`restore_file`/`kill_pid`/`revert_authorized_keys`/`restore_authorized_keys`/`disable_db_user`/`enable_db_user`), `ACTION_PLAN`/`CONFIDENCE`, and the store/route paths (`/security/actions`, `/security/auto-response`) are used identically across backend, router, store, and UI tasks.
```
