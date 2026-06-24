# MPHTJ Incident — Monitoring Hardening & Detection Gap Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 5 detection/response gaps that caused OpsPilot to miss CVE-2026-48908 on MPHTJ, and push fixes to both existing and new servers.

**Architecture:** Three layers — (1) onboarding discovers real nginx vhost log paths and document root over SSH, stores them in the DB, and injects them into Fluent Bit config and audit rules; (2) detection and response rules are extended for `sppb_exploit` with differentiated `block_category` gating auto-unblock; (3) a new `POST /reconfigure-monitoring` endpoint re-runs discovery and pushes updated configs to any already-deployed server.

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy async + Alembic, PostgreSQL/JSONB, Jinja2 templates, Vue 3 + Pinia

## Global Constraints

- All new DB columns nullable or have `server_default` — zero downtime migration
- Discovery functions are best-effort: SSH failure never aborts onboarding or reconfigure
- Vhost log inputs are tagged `nginx_access` — existing detection rules match with zero rule changes
- `_build_auditd_setup` uses `.replace("{webroot}", webroot)` NOT an f-string — shell script contains `$WEBUID` and other `$VAR` that must not be interpolated by Python
- Migration `0034` adds columns; migration `0035` backfills new SPPB rules to existing servers
- `create_default_rules` must be per-pattern idempotent before the reconfigure endpoint calls it

---

## File Map

| File | Change |
|------|--------|
| `backend/migrations/versions/0034_monitoring_hardening.py` | New: 3 column additions |
| `backend/migrations/versions/0035_sppb_detection_rules.py` | New: backfill SPPB rules to existing servers |
| `backend/app/models/server.py` | Add `extra_nginx_log_paths` (JSONB), `detected_webroot` (VARCHAR 255) |
| `backend/app/models/other.py` | Add `block_category` (VARCHAR 20) to `SecurityAction` |
| `backend/app/services/onboarding.py` | Add `_fetch_nginx_t`, `_discover_nginx_vhost_logs`, `_discover_webroot`; convert `_AUDITD_SETUP` → template + `_build_auditd_setup(webroot)`; convert `_OPSPILOT_ACTION_SCRIPT` → template + `_build_action_script(extra_root)`; update `_setup_auditd`, `_step_configure_fluent_bit`, `_step_install_action_wrapper`; add exported `reconfigure_monitoring` |
| `backend/app/services/templates/fluent-bit.conf.j2` | Add `extra_nginx_log_paths` loop block |
| `backend/app/routers/alert_rules.py` | Add 4 rules to `DEFAULT_LOG_RULES`; fix `create_default_rules` to per-pattern idempotency |
| `backend/app/services/security_responder.py` | Add `sppb_exploit` to `CONFIDENCE`/`ACTION_PLAN`/`_IP_LOG_PATTERNS`; add `_BLOCK_CATEGORY`; populate `block_category` on creation; skip exploit in auto-unblock |
| `backend/app/routers/servers.py` | Add `POST /api/servers/{id}/reconfigure-monitoring` |
| `backend/app/schemas/server.py` | Add `ReconfigureResult` schema |
| `frontend/src/stores/server.ts` | Add `reconfigureMonitoring(id)` action |
| `frontend/src/components/servers/tabs/InfoTab.vue` | Add "Reconfigure Monitoring" button + result display |
| `backend/tests/services/test_onboarding_discovery.py` | New: unit tests for pure discovery functions |
| `backend/tests/services/test_config_generation.py` | New: unit tests for auditd + action wrapper builders |
| `backend/tests/services/test_security_responder_block_category.py` | New: unit tests for block_category + auto-unblock skip |
| `backend/tests/routers/test_alert_rules_idempotency.py` | New: unit tests for per-pattern idempotency + new rules |

---

### Task 1: DB Migration — Add 3 Columns

**Files:**
- Modify: `backend/app/models/server.py`
- Modify: `backend/app/models/other.py`
- Create: `backend/migrations/versions/0034_monitoring_hardening.py`

**Interfaces:**
- Produces: `Server.extra_nginx_log_paths: list | None` (JSONB, default `[]`), `Server.detected_webroot: str | None` (VARCHAR 255), `SecurityAction.block_category: str | None` (VARCHAR 20)

- [ ] **Step 1: Add columns to Server model**

In `backend/app/models/server.py`, add `JSONB` to the postgresql import and two new columns after `block_ttl_hours`:

```python
# Change import line:
from sqlalchemy.dialects.postgresql import JSONB, UUID

# Add after block_ttl_hours column:
    extra_nginx_log_paths: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, default=list, server_default="'[]'::jsonb")
    detected_webroot: Mapped[str | None] = mapped_column(String(255), nullable=True)
```

- [ ] **Step 2: Add block_category to SecurityAction model**

In `backend/app/models/other.py`, add after the `confidence` column in `SecurityAction`:

```python
    block_category: Mapped[str | None] = mapped_column(String(20), nullable=True)
```

- [ ] **Step 3: Write migration**

Create `backend/migrations/versions/0034_monitoring_hardening.py`:

```python
"""Add extra_nginx_log_paths, detected_webroot to server; block_category to security_actions.

Revision ID: 0034_monitoring_hardening
Revises: 0033_ip_intel
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0034_monitoring_hardening"
down_revision = "0033_ip_intel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("server", sa.Column(
        "extra_nginx_log_paths", JSONB, nullable=True, server_default="'[]'::jsonb"))
    op.add_column("server", sa.Column(
        "detected_webroot", sa.String(255), nullable=True))
    op.add_column("security_actions", sa.Column(
        "block_category", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("server", "extra_nginx_log_paths")
    op.drop_column("server", "detected_webroot")
    op.drop_column("security_actions", "block_category")
```

- [ ] **Step 4: Run migration**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend alembic upgrade head
```

Expected: `Running upgrade 0033_ip_intel -> 0034_monitoring_hardening`

- [ ] **Step 5: Verify columns**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres \
  psql -U opspilot -c "\d server" | grep -E "extra_nginx|detected_webroot"
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres \
  psql -U opspilot -c "\d security_actions" | grep block_category
```

Expected:
```
 extra_nginx_log_paths | jsonb
 detected_webroot      | character varying(255)
 block_category        | character varying(20)
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/server.py backend/app/models/other.py \
        backend/migrations/versions/0034_monitoring_hardening.py
git commit -m "feat(db): add extra_nginx_log_paths, detected_webroot, block_category columns"
```

---

### Task 2: nginx -T Discovery Functions

**Files:**
- Modify: `backend/app/services/onboarding.py`
- Create: `backend/tests/__init__.py` (empty)
- Create: `backend/tests/services/__init__.py` (empty)
- Create: `backend/tests/services/test_onboarding_discovery.py`

**Interfaces:**
- Produces:
  - `_fetch_nginx_t(ssh: SSHSession) -> str` — SSH call, returns stdout or `""`
  - `_discover_nginx_vhost_logs(nginx_t_output: str) -> list[str]` — pure function
  - `_discover_webroot(nginx_t_output: str) -> str` — pure function, fallback `"/var/www/html"`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/__init__.py` and `backend/tests/services/__init__.py` as empty files, then create `backend/tests/services/test_onboarding_discovery.py`:

```python
from app.services.onboarding import _discover_nginx_vhost_logs, _discover_webroot

NGINX_T_MPHTJ = """
server {
    server_name mphtj.gov.my;
    access_log /var/log/nginx/mphtj.access.log;
    root /home/mphtj/web;
    listen 443 ssl;
}
server {
    server_name _;
    access_log /var/log/nginx/access.log;
    root /var/www/html;
    listen 80;
}
"""

NGINX_T_MULTI = """
server {
    server_name site1.example.com;
    access_log /var/log/nginx/site1.access.log;
    root /home/site1/web;
}
server {
    server_name site2.example.com;
    access_log /var/log/nginx/site2.access.log;
    root /var/www/site2;
}
server {
    server_name _;
    access_log /var/log/nginx/access.log;
    root /var/www/html;
}
"""


def test_discovers_extra_vhost_log():
    result = _discover_nginx_vhost_logs(NGINX_T_MPHTJ)
    assert "/var/log/nginx/mphtj.access.log" in result


def test_excludes_default_access_log():
    result = _discover_nginx_vhost_logs(NGINX_T_MPHTJ)
    assert "/var/log/nginx/access.log" not in result


def test_multi_site_discovers_all_extra_logs():
    result = _discover_nginx_vhost_logs(NGINX_T_MULTI)
    assert "/var/log/nginx/site1.access.log" in result
    assert "/var/log/nginx/site2.access.log" in result
    assert "/var/log/nginx/access.log" not in result


def test_deduplicates_paths():
    doubled = NGINX_T_MPHTJ + "\naccess_log /var/log/nginx/mphtj.access.log;\n"
    result = _discover_nginx_vhost_logs(doubled)
    assert result.count("/var/log/nginx/mphtj.access.log") == 1


def test_empty_input_returns_empty_list():
    assert _discover_nginx_vhost_logs("") == []


def test_excludes_off_keyword():
    output = "access_log off;\naccess_log /var/log/nginx/real.log;\n"
    result = _discover_nginx_vhost_logs(output)
    assert "off" not in result
    assert "/var/log/nginx/real.log" in result


def test_webroot_returns_nonstandard_root():
    assert _discover_webroot(NGINX_T_MPHTJ) == "/home/mphtj/web"


def test_webroot_skips_standard_var_www():
    output = "root /var/www/html;\nroot /usr/share/nginx/html;\n"
    assert _discover_webroot(output) == "/var/www/html"


def test_webroot_fallback_on_empty():
    assert _discover_webroot("") == "/var/www/html"


def test_webroot_first_nonstandard_wins():
    assert _discover_webroot(NGINX_T_MULTI) == "/home/site1/web"
```

- [ ] **Step 2: Run — verify FAIL**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend \
  python -m pytest backend/tests/services/test_onboarding_discovery.py -v 2>&1 | head -20
```

Expected: `ImportError` or `AttributeError` — functions don't exist yet.

- [ ] **Step 3: Implement the three functions**

In `backend/app/services/onboarding.py`, add after the existing `_web_error_log` function (around line 640):

```python
_NGINX_T_SKIP_LOG_PATHS = {
    "/var/log/nginx/access.log",
    "off",
    "stderr",
    "/dev/stdout",
    "/dev/stderr",
}

_STANDARD_WEBROOTS = {
    "/var/www",
    "/var/www/html",
    "/usr/share/nginx/html",
    "/srv/www",
    "/usr/share/nginx",
}


async def _fetch_nginx_t(ssh: SSHSession) -> str:
    """Run `nginx -T` and return merged config stdout. Returns '' on any error."""
    try:
        r = await ssh.run("nginx -T 2>/dev/null", timeout=15)
        return r.stdout or ""
    except Exception:
        return ""


def _discover_nginx_vhost_logs(nginx_t_output: str) -> list[str]:
    """Return vhost-specific access_log paths from nginx -T output.

    Excludes /var/log/nginx/access.log (hardcoded in template), 'off',
    stderr aliases, and duplicates.
    """
    if not nginx_t_output:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for m in re.finditer(r"\baccess_log\s+(\S+)", nginx_t_output):
        path = m.group(1).rstrip(";")
        if path in _NGINX_T_SKIP_LOG_PATHS or path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def _discover_webroot(nginx_t_output: str) -> str:
    """Return first non-standard document root from nginx -T output.

    Falls back to /var/www/html if none found or input is empty.
    """
    if not nginx_t_output:
        return "/var/www/html"
    for m in re.finditer(r"\broot\s+(\S+)", nginx_t_output):
        path = m.group(1).rstrip(";")
        if path not in _STANDARD_WEBROOTS and not any(
            path == r or path.startswith(r + "/") for r in _STANDARD_WEBROOTS
        ):
            return path
    return "/var/www/html"
```

- [ ] **Step 4: Run — verify PASS**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend \
  python -m pytest backend/tests/services/test_onboarding_discovery.py -v
```

Expected: 10/10 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/onboarding.py \
        backend/tests/__init__.py \
        backend/tests/services/__init__.py \
        backend/tests/services/test_onboarding_discovery.py
git commit -m "feat(onboarding): nginx -T discovery functions for vhost logs and webroot"
```

---

### Task 3: Config Builders — Fluent Bit Template + auditd + Action Wrapper

**Files:**
- Modify: `backend/app/services/templates/fluent-bit.conf.j2`
- Modify: `backend/app/services/onboarding.py`
- Create: `backend/tests/services/test_config_generation.py`

**Interfaces:**
- Produces:
  - Fluent Bit template accepts `extra_nginx_log_paths: list[str]` and renders one `[INPUT]` per path
  - `_build_auditd_setup(webroot: str) -> str`
  - `_build_action_script(extra_root: str | None) -> str`
  - `_setup_auditd(ssh, webroot: str = "/var/www/html") -> bool` (updated signature)

- [ ] **Step 1: Write failing tests**

Create `backend/tests/services/test_config_generation.py`:

```python
import os
from jinja2 import Environment, FileSystemLoader
from app.services.onboarding import _build_auditd_setup, _build_action_script

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "../../app/services/templates")


def _render_fb(extra_nginx_log_paths=None):
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    tmpl = env.get_template("fluent-bit.conf.j2")
    return tmpl.render(
        server_id="test-id", server_name="test",
        ingest_host="backend", ingest_port=8000, ingest_tls="Off",
        ingestion_token="tok",
        php_fpm_log_path="/var/log/php8.2-fpm.log", php_app_log_path="",
        web_access_log_path="/var/log/nginx/access.log", web_error_log_path="",
        auditd_enabled=False, mariadb_general_enabled=False,
        syslog_path="/var/log/syslog", auth_log_path="/var/log/auth.log",
        mariadb_error_path="/var/log/mysql/error.log",
        mariadb_slow_path="/var/log/mysql/slow.log",
        extra_nginx_log_paths=extra_nginx_log_paths or [],
    )


def test_no_extra_logs_no_extra_input_block():
    conf = _render_fb([])
    # mphtj log should not appear
    assert "/var/log/nginx/mphtj.access.log" not in conf


def test_extra_log_renders_additional_input():
    conf = _render_fb(["/var/log/nginx/mphtj.access.log"])
    assert "/var/log/nginx/mphtj.access.log" in conf


def test_extra_log_tagged_nginx_access():
    conf = _render_fb(["/var/log/nginx/mphtj.access.log"])
    # Find the block and confirm it has nginx_access tag
    idx = conf.index("/var/log/nginx/mphtj.access.log")
    block = conf[idx - 200:idx + 200]
    assert "nginx_access" in block


def test_extra_log_unique_db_path():
    conf = _render_fb(["/var/log/nginx/mphtj.access.log"])
    assert "_var_log_nginx_mphtj_access_log" in conf


def test_two_extra_logs_both_rendered():
    conf = _render_fb(["/var/log/nginx/site1.access.log", "/var/log/nginx/site2.access.log"])
    assert "/var/log/nginx/site1.access.log" in conf
    assert "/var/log/nginx/site2.access.log" in conf


# auditd builder
def test_build_auditd_setup_injects_webroot():
    script = _build_auditd_setup("/home/mphtj/web")
    assert "-w /home/mphtj/web -p wa -k webroot_write" in script


def test_build_auditd_setup_preserves_dollar_vars():
    script = _build_auditd_setup("/home/mphtj/web")
    assert "$WEBUID" in script
    assert "WEBUID=$(id -u" in script


def test_build_auditd_setup_default_path():
    script = _build_auditd_setup("/var/www/html")
    assert "-w /var/www/html -p wa -k webroot_write" in script


# action script builder
def test_build_action_script_adds_nonstandard_root():
    script = _build_action_script("/opt/custom/web")
    assert "/opt/custom/web" in script


def test_build_action_script_home_subdir_added_explicitly():
    script = _build_action_script("/home/mphtj/web")
    assert "/home/mphtj/web" in script


def test_build_action_script_none_produces_standard_roots():
    script = _build_action_script(None)
    assert "for root in /var/www /usr/share/nginx /srv/www /home" in script
    assert "{extra_roots_entry}" not in script
```

- [ ] **Step 2: Run — verify FAIL**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend \
  python -m pytest backend/tests/services/test_config_generation.py -v 2>&1 | head -20
```

Expected: Template render fails (`extra_nginx_log_paths` unknown), `ImportError` for builders.

- [ ] **Step 3: Update Fluent Bit template**

In `backend/app/services/templates/fluent-bit.conf.j2`, add this block immediately after the hardcoded `# ── Nginx access ──` INPUT block (after the `Refresh_Interval  5` line, before `# ── Nginx error ──`):

```jinja2
{% for extra_path in extra_nginx_log_paths %}
# ── Nginx vhost access ({{ extra_path }}) ────────────────────────────────────
[INPUT]
    Name              tail
    Path              {{ extra_path }}
    Tag               nginx_access
    DB                /var/lib/fluent-bit/{{ extra_path | replace('/', '_') | replace('.', '_') }}.db
    Skip_Long_Lines   On
{% endfor %}
```

- [ ] **Step 4: Convert _AUDITD_SETUP to template + builder**

In `backend/app/services/onboarding.py`, rename `_AUDITD_SETUP` to `_AUDITD_SETUP_TEMPLATE` and change ONLY the `-w /var/www` line to `-w {webroot}`. Every other `$` shell variable stays untouched:

```python
_AUDITD_SETUP_TEMPLATE = """\
WEBUID=$(id -u www-data 2>/dev/null || id -u apache 2>/dev/null || id -u nginx 2>/dev/null || echo 33)
( apt-get install -y auditd >/dev/null 2>&1 || yum install -y audit >/dev/null 2>&1 || true )
mkdir -p /etc/audit/rules.d
cat >/etc/audit/rules.d/opspilot.rules <<RULES
-w {webroot} -p wa -k webroot_write
-a exit,always -F arch=b64 -F uid=$WEBUID -S execve -k webshell_exec
-a exit,always -F arch=b32 -F uid=$WEBUID -S execve -k webshell_exec
-w /root/.ssh/authorized_keys -p wa -k ssh_key_change
-a always,exit -F arch=b64 -F dir=/home -F name=authorized_keys -F perm=wa -k ssh_key_change
-a always,exit -F arch=b32 -F dir=/home -F name=authorized_keys -F perm=wa -k ssh_key_change
-w /var/log -p wa -k log_tamper
RULES
augenrules --load >/dev/null 2>&1 && echo AUDITD_OK
"""


def _build_auditd_setup(webroot: str) -> str:
    return _AUDITD_SETUP_TEMPLATE.replace("{webroot}", webroot)
```

Then update `_setup_auditd` signature:

```python
async def _setup_auditd(ssh: SSHSession, webroot: str = "/var/www/html") -> bool:
    try:
        r = await ssh.run(_build_auditd_setup(webroot), sudo=True, timeout=120)
        return "AUDITD_OK" in (r.stdout or "")
    except SSHError:
        return False
```

- [ ] **Step 5: Convert _OPSPILOT_ACTION_SCRIPT to template + builder**

In `backend/app/services/onboarding.py`:
1. Rename `_OPSPILOT_ACTION_SCRIPT` → `_OPSPILOT_ACTION_SCRIPT_TEMPLATE`
2. In the template, find the `_validate_path` function's for-loop line and add `{extra_roots_entry}`:

```bash
    for root in /var/www /usr/share/nginx /srv/www /home{extra_roots_entry}; do
```

3. Add the builder function and the set of standard roots after the template constant:

```python
_STANDARD_VALIDATE_ROOTS = frozenset({"/var/www", "/usr/share/nginx", "/srv/www", "/home"})


def _build_action_script(extra_root: str | None) -> str:
    if extra_root and not any(
        extra_root == r or extra_root.startswith(r + "/")
        for r in _STANDARD_VALIDATE_ROOTS
    ):
        entry = f" {extra_root}"
    else:
        entry = ""
    return _OPSPILOT_ACTION_SCRIPT_TEMPLATE.replace("{extra_roots_entry}", entry)
```

- [ ] **Step 6: Run — verify PASS**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend \
  python -m pytest backend/tests/services/test_config_generation.py -v
```

Expected: All 13 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/templates/fluent-bit.conf.j2 \
        backend/app/services/onboarding.py \
        backend/tests/services/test_config_generation.py
git commit -m "feat(config): vhost log inputs in Fluent Bit, webroot-aware auditd, templated action wrapper"
```

---

### Task 4: Wire Discovery into Onboarding

**Files:**
- Modify: `backend/app/services/onboarding.py`

**Interfaces:**
- Consumes: `_fetch_nginx_t`, `_discover_nginx_vhost_logs`, `_discover_webroot`, `_setup_auditd(ssh, webroot)`, `_build_action_script` (all from Tasks 2–3)
- Produces: `server.extra_nginx_log_paths` and `server.detected_webroot` written to DB; Fluent Bit config includes vhost logs; auditd watches real webroot

- [ ] **Step 1: Update _step_configure_fluent_bit**

In `_step_configure_fluent_bit` (line ~704), after the existing `web_access_log_path = await _detect_web_access_log(ssh)` line, add:

```python
    # ── Gap 1 + Gap 3 fix: discover vhost logs + real webroot ────────────────
    nginx_t_output = await _fetch_nginx_t(ssh)
    extra_nginx_log_paths = _discover_nginx_vhost_logs(nginx_t_output)
    detected_webroot = _discover_webroot(nginx_t_output)
    server.extra_nginx_log_paths = extra_nginx_log_paths
    server.detected_webroot = detected_webroot
    await db.flush()
```

Then change the `_setup_auditd` call to pass the webroot:

```python
    auditd_enabled = await _setup_auditd(ssh, detected_webroot)
```

Then add `extra_nginx_log_paths=extra_nginx_log_paths` to the `tmpl.render(...)` call (alongside the other keyword args).

- [ ] **Step 2: Update _step_install_action_wrapper**

In `_step_install_action_wrapper` (line ~911), change the upload line from:

```python
        await ssh.upload(_OPSPILOT_ACTION_SCRIPT, "/usr/local/bin/opspilot-action",
```

to:

```python
        action_script = _build_action_script(server.detected_webroot)
        await ssh.upload(action_script, "/usr/local/bin/opspilot-action",
```

- [ ] **Step 3: Smoke test on test VM**

Trigger onboarding on the test server (from `test-target/README.md`). After it completes:

```bash
# On target server:
sudo cat /etc/fluent-bit/fluent-bit.conf | grep -A6 "vhost access"
sudo cat /etc/audit/rules.d/opspilot.rules | grep webroot_write
```

If the server has no vhosts beyond the default, the Fluent Bit output will show no extra blocks — that's correct. The auditd rule will show the discovered webroot (or `/var/www/html` fallback).

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/onboarding.py
git commit -m "feat(onboarding): wire vhost log discovery into configure_fluent_bit and action wrapper"
```

---

### Task 5: Detection Rules + Idempotency + Backfill Migration

**Files:**
- Modify: `backend/app/routers/alert_rules.py`
- Create: `backend/migrations/versions/0035_sppb_detection_rules.py`
- Create: `backend/tests/routers/__init__.py` (empty)
- Create: `backend/tests/routers/test_alert_rules_idempotency.py`

**Interfaces:**
- Produces: 4 new entries in `DEFAULT_LOG_RULES`; `create_default_rules` is now per-pattern idempotent (return type `tuple[int, int]` unchanged)

- [ ] **Step 1: Write failing tests**

Create `backend/tests/routers/__init__.py` (empty) and `backend/tests/routers/test_alert_rules_idempotency.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.routers.alert_rules import DEFAULT_LOG_RULES, create_default_rules


def test_sppb_rule_present():
    patterns = [p for _, p, *_ in DEFAULT_LOG_RULES]
    assert any("com_sppagebuilder" in p and "uploadCustomIcon" in p for p in patterns)


def test_php_uppercase_rule_present():
    patterns = [p for _, p, *_ in DEFAULT_LOG_RULES]
    assert any("/media/%.PHP%" in p for p in patterns)


def test_sppb_rule_is_critical():
    for _, pattern, severity, *_ in DEFAULT_LOG_RULES:
        if "com_sppagebuilder" in pattern:
            assert severity == "critical"
            return
    pytest.fail("SPPB rule not found")


@pytest.mark.asyncio
async def test_create_default_rules_skips_existing_pattern():
    """When all log patterns already exist, log_added must be 0."""
    call_count = 0

    async def fake_scalar(stmt, *a, **kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None   # no existing metric rules → add metric rules
        return "exists"   # every log pattern check returns "exists"

    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=fake_scalar)
    db.add = MagicMock()

    server = MagicMock()
    server.id = "00000000-0000-0000-0000-000000000001"

    _metric_added, log_added = await create_default_rules(db, server)
    assert log_added == 0


@pytest.mark.asyncio
async def test_create_default_rules_adds_missing_pattern():
    """When no log rules exist, log_added equals len(DEFAULT_LOG_RULES)."""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)  # nothing exists
    db.add = MagicMock()

    server = MagicMock()
    server.id = "00000000-0000-0000-0000-000000000001"

    _metric_added, log_added = await create_default_rules(db, server)
    assert log_added == len(DEFAULT_LOG_RULES)
```

- [ ] **Step 2: Run — verify FAIL**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend \
  python -m pytest backend/tests/routers/test_alert_rules_idempotency.py -v 2>&1 | head -20
```

Expected: `test_sppb_rule_present` FAILS — rule not yet added.

- [ ] **Step 3: Add 4 new rules to DEFAULT_LOG_RULES**

In `backend/app/routers/alert_rules.py`, append to `DEFAULT_LOG_RULES` after the last existing entry:

```python
    # ── SP Page Builder CVE-2026-48908 + case-insensitive PHP upload hardening ──
    ("%access%", "%com_sppagebuilder%uploadCustomIcon%", "critical", 1, 300),
    ("%access%", "%/media/%.PHP%", "critical", 1, 300),
    ("%access%", "%/media/%.pHp%", "critical", 1, 300),
    ("%access%", "%POST%index.php% 200 %", "warning", 10, 60),
```

- [ ] **Step 4: Fix create_default_rules to per-pattern idempotency**

In `backend/app/routers/alert_rules.py`, in `create_default_rules`, replace the existing log-rule block:

```python
    # OLD (replace this entire block):
    existing_log = await db.scalar(
        select(LogAlertRule.id).where(LogAlertRule.server_id == server_id).limit(1)
    )
    log_added = 0
    if existing_log is None:
        for source, pattern, severity, threshold, window_sec in DEFAULT_LOG_RULES:
            db.add(LogAlertRule(...))
            log_added += 1

    # NEW (per-pattern idempotency):
    log_added = 0
    for source, pattern, severity, threshold, window_sec in DEFAULT_LOG_RULES:
        exists = await db.scalar(
            select(LogAlertRule.id)
            .where(
                LogAlertRule.server_id == server_id,
                LogAlertRule.source == source,
                LogAlertRule.pattern == pattern,
            )
            .limit(1)
        )
        if exists:
            continue
        db.add(
            LogAlertRule(
                server_id=server_id,
                source=source,
                pattern=pattern,
                severity=severity,
                threshold=threshold,
                window_sec=window_sec,
                cooldown_min=60,
                enabled=True,
            )
        )
        log_added += 1
```

- [ ] **Step 5: Run — verify PASS**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend \
  python -m pytest backend/tests/routers/test_alert_rules_idempotency.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 6: Write backfill migration**

Create `backend/migrations/versions/0035_sppb_detection_rules.py`:

```python
"""Backfill SP Page Builder + case-insensitive PHP detection rules to existing servers.

Revision ID: 0035_sppb_detection_rules
Revises: 0034_monitoring_hardening
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0035_sppb_detection_rules"
down_revision = "0034_monitoring_hardening"
branch_labels = None
depends_on = None

NEW_RULES = [
    ("%access%", "%com_sppagebuilder%uploadCustomIcon%", "critical", 1, 300),
    ("%access%", "%/media/%.PHP%", "critical", 1, 300),
    ("%access%", "%/media/%.pHp%", "critical", 1, 300),
    ("%access%", "%POST%index.php% 200 %", "warning", 10, 60),
]


def upgrade() -> None:
    conn = op.get_bind()
    servers = conn.execute(sa.text("SELECT id FROM server")).fetchall()
    for (server_id,) in servers:
        for source, pattern, severity, threshold, window_sec in NEW_RULES:
            exists = conn.execute(
                sa.text(
                    "SELECT 1 FROM log_alert_rule "
                    "WHERE server_id = :sid AND source = :source AND pattern = :pattern LIMIT 1"
                ),
                {"sid": server_id, "source": source, "pattern": pattern},
            ).first()
            if exists:
                continue
            conn.execute(
                sa.text(
                    "INSERT INTO log_alert_rule "
                    "(server_id, source, pattern, severity, threshold, window_sec, cooldown_min, enabled) "
                    "VALUES (:sid, :source, :pattern, :severity, :threshold, :window_sec, 60, true)"
                ),
                {"sid": server_id, "source": source, "pattern": pattern,
                 "severity": severity, "threshold": threshold, "window_sec": window_sec},
            )


def downgrade() -> None:
    conn = op.get_bind()
    for source, pattern, *_ in NEW_RULES:
        conn.execute(
            sa.text("DELETE FROM log_alert_rule WHERE source = :source AND pattern = :pattern"),
            {"source": source, "pattern": pattern},
        )
```

- [ ] **Step 7: Run migration**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend alembic upgrade head
```

Expected: `Running upgrade 0034_monitoring_hardening -> 0035_sppb_detection_rules`

- [ ] **Step 8: Verify rules in DB**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres \
  psql -U opspilot -c \
  "SELECT source, pattern, severity FROM log_alert_rule WHERE pattern LIKE '%sppagebuilder%' LIMIT 5;"
```

Expected: rows with `pattern = %com_sppagebuilder%uploadCustomIcon%`, `severity = critical`.

- [ ] **Step 9: Commit**

```bash
git add backend/app/routers/alert_rules.py \
        backend/migrations/versions/0035_sppb_detection_rules.py \
        backend/tests/routers/__init__.py \
        backend/tests/routers/test_alert_rules_idempotency.py
git commit -m "feat(detection): SPPB + PHP upload rules, per-pattern idempotent create_default_rules, backfill migration"
```

---

### Task 6: Security Responder — SPPB Wiring + block_category + Auto-Unblock Fix

**Files:**
- Modify: `backend/app/services/security_responder.py`
- Create: `backend/tests/services/test_security_responder_block_category.py`

**Interfaces:**
- Produces: `_BLOCK_CATEGORY` dict; `SecurityAction.block_category` populated on `block_ip` creation; `_auto_unblock_expired` skips rows where `block_category = 'exploit'`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/services/test_security_responder_block_category.py`:

```python
from app.services.security_responder import (
    CONFIDENCE, ACTION_PLAN, _IP_LOG_PATTERNS, _BLOCK_CATEGORY,
)


def test_sppb_in_confidence():
    assert CONFIDENCE.get("sppb_exploit") == "high"


def test_sppb_in_action_plan():
    assert ACTION_PLAN.get("sppb_exploit") == [("block_ip", 1)]


def test_sppb_in_ip_log_patterns():
    assert "%com_sppagebuilder%" in _IP_LOG_PATTERNS.get("sppb_exploit", "")


def test_exploit_types_map_to_exploit():
    for t in ("jce_exploit_attempt", "sppb_exploit", "webshell_upload",
              "webshell_execution", "webshell_command_exec"):
        assert _BLOCK_CATEGORY.get(t) == "exploit", f"{t} should be 'exploit'"


def test_scanner_maps_to_scanner():
    assert _BLOCK_CATEGORY.get("probe_scan") == "scanner"


def test_ssh_brute_force_maps_to_ssh():
    assert _BLOCK_CATEGORY.get("ssh_brute_force") == "ssh"
```

- [ ] **Step 2: Run — verify FAIL**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend \
  python -m pytest backend/tests/services/test_security_responder_block_category.py -v 2>&1 | head -20
```

Expected: `ImportError` for `_BLOCK_CATEGORY`; `KeyError` on `sppb_exploit`.

- [ ] **Step 3: Add sppb_exploit to the three dicts**

In `backend/app/services/security_responder.py`:

```python
# Add to CONFIDENCE:
    "sppb_exploit": "high",

# Add to ACTION_PLAN:
    "sppb_exploit":          [("block_ip", 1)],

# Add to _IP_LOG_PATTERNS:
    "sppb_exploit":          "%com_sppagebuilder%",
```

- [ ] **Step 4: Add _BLOCK_CATEGORY map**

In `backend/app/services/security_responder.py`, add after `_IP_LOG_PATTERNS`:

```python
_BLOCK_CATEGORY: dict[str, str] = {
    "jce_exploit_attempt":   "exploit",
    "sppb_exploit":          "exploit",
    "webshell_upload":       "exploit",
    "webshell_execution":    "exploit",
    "webshell_command_exec": "exploit",
    "probe_scan":            "scanner",
    "ssh_brute_force":       "ssh",
}
```

- [ ] **Step 5: Populate block_category on SecurityAction creation**

In `_handle_alert`, find the `SecurityAction(...)` constructor (around line 219) and add the `block_category` field:

```python
        row = SecurityAction(
            server_id=server.id, alert_id=alert.id, action_type=action_type,
            target=target, tier=tier, confidence=confidence, actor="auto",
            status="pending_approval",
            block_category=_BLOCK_CATEGORY.get(alert.type) if action_type == "block_ip" else None,
        )
```

- [ ] **Step 6: Update _auto_unblock_expired to skip exploit blocks**

In `_auto_unblock_expired` (around line 286), add `or_` to the imports at the top of the file:

```python
from sqlalchemy import or_, select, text
```

Then in the `.where(...)` clause of the query, add:

```python
                   or_(
                       SecurityAction.block_category != "exploit",
                       SecurityAction.block_category.is_(None),
                   ),
```

The full updated `.where(...)` block:

```python
            .where(SecurityAction.action_type == "block_ip",
                   SecurityAction.status == "executed",
                   SecurityAction.executed_at.isnot(None),
                   SecurityAction.executed_at >= _now() - timedelta(days=_TTL_GIVEUP_DAYS),
                   or_(
                       SecurityAction.block_category != "exploit",
                       SecurityAction.block_category.is_(None),
                   ))
```

- [ ] **Step 7: Run — verify PASS**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend \
  python -m pytest backend/tests/services/test_security_responder_block_category.py -v
```

Expected: All 6 tests PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/security_responder.py \
        backend/tests/services/test_security_responder_block_category.py
git commit -m "feat(security): sppb_exploit response, block_category, permanent exploit blocks"
```

---

### Task 7: Reconfigure Monitoring Endpoint

**Files:**
- Modify: `backend/app/services/onboarding.py`
- Modify: `backend/app/routers/servers.py`
- Modify: `backend/app/schemas/server.py`

**Interfaces:**
- Produces: `POST /api/servers/{server_id}/reconfigure-monitoring` → `{ extra_logs_added, webroot, rules_added, warnings }`; `reconfigure_monitoring(db, server)` exported from onboarding service

- [ ] **Step 1: Add ReconfigureResult schema**

In `backend/app/schemas/server.py`, add at the end:

```python
class ReconfigureResult(BaseModel):
    extra_logs_added: list[str]
    webroot: str
    rules_added: int
    warnings: list[str]
```

- [ ] **Step 2: Add reconfigure_monitoring to onboarding service**

In `backend/app/services/onboarding.py`, add this exported function after `_step_install_action_wrapper`. It reuses all existing helpers — `_fetch_nginx_t`, `_discover_nginx_vhost_logs`, `_discover_webroot`, `_setup_auditd`, `_build_action_script`, `_detect_web_access_log`, `_web_server_kind`, `_web_error_log`, `_template_env`, `settings`:

```python
async def reconfigure_monitoring(db, server: Server) -> dict:
    """Re-discover nginx vhost config over SSH, push updated Fluent Bit + auditd + action wrapper,
    seed any missing default detection rules. Best-effort per step.
    """
    from urllib.parse import urlparse
    from app.routers.alert_rules import create_default_rules

    warnings: list[str] = []
    extra_logs_added: list[str] = []
    webroot: str = server.detected_webroot or "/var/www/html"
    rules_added = 0

    try:
        async with SSHSession(server) as ssh:
            # 1. Discover vhost logs + webroot
            nginx_t = await _fetch_nginx_t(ssh)
            extra_logs_added = _discover_nginx_vhost_logs(nginx_t)
            webroot = _discover_webroot(nginx_t)

            # 2. Auditd with real webroot
            if not await _setup_auditd(ssh, webroot):
                warnings.append("auditd rule update failed or skipped")

            # 3. Action wrapper
            try:
                await ssh.upload(
                    _build_action_script(webroot),
                    "/usr/local/bin/opspilot-action",
                    mode=0o755, sudo=True,
                )
            except SSHError as e:
                warnings.append(f"action wrapper update failed: {e}")

            # 4. Fluent Bit config re-render + push
            try:
                base = (settings.opspilot_base_url or "http://opspilot-backend:8000").rstrip("/")
                parsed = urlparse(base)
                ingest_host = parsed.hostname or "opspilot-backend"
                ingest_port = parsed.port or (443 if parsed.scheme == "https" else 80)
                ingest_tls = "On" if parsed.scheme == "https" else "Off"

                web_access_log_path = await _detect_web_access_log(ssh)
                web_kind = _web_server_kind(web_access_log_path)
                web_error_log_path = _web_error_log(web_kind)

                tmpl = _template_env.get_template("fluent-bit.conf.j2")
                conf = tmpl.render(
                    server_id=str(server.id),
                    server_name=server.name,
                    ingest_host=ingest_host,
                    ingest_port=ingest_port,
                    ingest_tls=ingest_tls,
                    ingestion_token=str(server.ingestion_token),
                    php_fpm_log_path="/var/log/php*-fpm.log",
                    php_app_log_path="",
                    web_access_log_path=web_access_log_path,
                    web_error_log_path=web_error_log_path,
                    auditd_enabled=False,
                    mariadb_general_enabled=False,
                    extra_nginx_log_paths=extra_logs_added,
                    syslog_path="/var/log/syslog",
                    auth_log_path="/var/log/auth.log",
                    mariadb_error_path="/var/log/mysql/error.log",
                    mariadb_slow_path="/var/log/mysql/slow.log",
                )
                parsers_conf = _template_env.get_template("fluent-bit-parsers.conf.j2").render()
                await ssh.run("mkdir -p /etc/fluent-bit /var/lib/fluent-bit",
                              sudo=True, raise_on_error=True)
                await ssh.upload(parsers_conf, "/etc/fluent-bit/parsers-opspilot.conf",
                                 mode=0o640, sudo=True)
                await ssh.upload(conf, "/etc/fluent-bit/fluent-bit.conf",
                                 mode=0o640, sudo=True)
                await ssh.run("systemctl restart fluent-bit", sudo=True, timeout=15)
            except Exception as e:
                warnings.append(f"fluent-bit config push failed: {e}")

    except Exception as e:
        warnings.append(f"SSH connection failed: {e}")

    # 5. Persist to DB
    server.extra_nginx_log_paths = extra_logs_added
    server.detected_webroot = webroot
    await db.flush()

    # 6. Seed missing detection rules (per-pattern idempotent)
    try:
        _m, rules_added = await create_default_rules(db, server)
    except Exception as e:
        warnings.append(f"rule seeding failed: {e}")

    return {
        "extra_logs_added": extra_logs_added,
        "webroot": webroot,
        "rules_added": rules_added,
        "warnings": warnings,
    }
```

- [ ] **Step 3: Add endpoint to servers router**

In `backend/app/routers/servers.py`, add the import and endpoint after `redeploy_agents`:

```python
from app.schemas.server import ReconfigureResult  # add to existing imports

@router.post("/api/servers/{server_id}/reconfigure-monitoring",
             response_model=ReconfigureResult)
async def reconfigure_monitoring(
    server_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)
):
    server = await db.scalar(
        select(Server).where(Server.id == server_id, Server.is_active == True)
    )
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})
    result = await onboarding_service.reconfigure_monitoring(db, server)
    await db.commit()
    return result
```

Also check the existing `from app.services import onboarding as onboarding_service` import is present; if not, add it.

- [ ] **Step 4: Smoke test**

```bash
SERVER_ID="<a-real-server-uuid>"
TOKEN="<your-session-token>"
curl -s -X POST "http://localhost:9090/api/servers/${SERVER_ID}/reconfigure-monitoring" \
  -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" | python3 -m json.tool
```

Expected JSON:
```json
{
  "extra_logs_added": [],
  "webroot": "/var/www/html",
  "rules_added": 4,
  "warnings": []
}
```

`rules_added: 4` confirms the 4 new SPPB/PHP rules were seeded. `extra_logs_added` will be non-empty on servers with site-specific vhost logs.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/onboarding.py \
        backend/app/routers/servers.py \
        backend/app/schemas/server.py
git commit -m "feat(api): POST /reconfigure-monitoring — re-push configs and seed missing rules"
```

---

### Task 8: Frontend — Reconfigure Monitoring Button

**Files:**
- Modify: `frontend/src/stores/server.ts`
- Modify: `frontend/src/components/servers/tabs/InfoTab.vue`

**Interfaces:**
- Consumes: `POST /api/servers/{id}/reconfigure-monitoring` (Task 7)
- Produces: button in InfoTab with loading state + inline result summary

- [ ] **Step 1: Add store action**

In `frontend/src/stores/server.ts`, add after the `redeploy` function:

```typescript
  async function reconfigureMonitoring(id: string): Promise<{
    extra_logs_added: string[]
    webroot: string
    rules_added: number
    warnings: string[]
  }> {
    const res = await api.post(`/api/servers/${id}/reconfigure-monitoring`)
    return res.data
  }
```

Add `reconfigureMonitoring` to the store's return statement alongside `redeploy`.

- [ ] **Step 2: Add reactive state + handler to InfoTab.vue**

In `frontend/src/components/servers/tabs/InfoTab.vue`, add alongside the existing `redeploying` refs at the top of `<script setup>`:

```typescript
const reconfiguring = ref(false)
const reconfigureResult = ref<{
  extra_logs_added: string[]
  webroot: string
  rules_added: number
  warnings: string[]
} | null>(null)
const reconfigureError = ref('')

async function reconfigureMonitoring() {
  const id = props.server?.id
  if (!id) return
  reconfiguring.value = true
  reconfigureResult.value = null
  reconfigureError.value = ''
  try {
    reconfigureResult.value = await serverStore.reconfigureMonitoring(id)
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    reconfigureError.value = typeof detail === 'object'
      ? (detail?.message ?? 'Unknown error')
      : (detail ?? 'Request failed')
  } finally {
    reconfiguring.value = false
  }
}
```

- [ ] **Step 3: Add button + result to template**

In the template, add directly below the existing "Reconfigure Agents" `<button>` block:

```html
<button class="agent-btn" :disabled="reconfiguring" @click="reconfigureMonitoring">
  {{ reconfiguring ? 'Reconfiguring…' : 'Reconfigure Monitoring' }}
</button>
<div v-if="reconfigureResult" class="agent-result"
     :style="reconfigureResult.warnings.length ? 'color: var(--va-warning)' : ''">
  <span v-if="reconfigureResult.extra_logs_added.length">
    {{ reconfigureResult.extra_logs_added.length }} additional log file(s) found ·
  </span>
  <span v-else>No new log files · </span>
  <span>Webroot: {{ reconfigureResult.webroot }}</span>
  <span v-if="reconfigureResult.rules_added"> · {{ reconfigureResult.rules_added }} rules added</span>
  <span v-if="reconfigureResult.warnings.length">
    · ⚠ {{ reconfigureResult.warnings.length }} warning(s)
  </span>
</div>
<p v-if="reconfigureError" class="agent-error">Reconfigure failed: {{ reconfigureError }}</p>
```

- [ ] **Step 4: Smoke test in browser**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

Open `http://localhost:9090`, navigate to any server → Info tab. Verify:
- "Reconfigure Monitoring" button appears
- Click shows "Reconfiguring…" loading state
- On success: result line shows log files, webroot, rules added
- On SSH error: error message displayed

- [ ] **Step 5: Commit and tag release**

```bash
git add frontend/src/stores/server.ts \
        frontend/src/components/servers/tabs/InfoTab.vue
git commit -m "feat(ui): Reconfigure Monitoring button with live result in InfoTab"

PREV=$(git describe --tags --abbrev=0)
# bump patch: e.g. v1.2.79 → v1.2.80
NEW_TAG=$(echo $PREV | awk -F. '{print $1"."$2"."$3+1}')
git tag $NEW_TAG && git push origin main $NEW_TAG
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|-----------------|-----------|
| `extra_nginx_log_paths` + `detected_webroot` on Server | Task 1 |
| `block_category` on SecurityAction | Task 1 |
| `_fetch_nginx_t` / `_discover_nginx_vhost_logs` / `_discover_webroot` | Task 2 |
| Fluent Bit template `extra_nginx_log_paths` loop | Task 3 |
| `_build_auditd_setup(webroot)` — `.replace` not f-string | Task 3 |
| `_build_action_script(extra_root)` | Task 3 |
| Wire into `_step_configure_fluent_bit` | Task 4 |
| Wire into `_step_install_action_wrapper` | Task 4 |
| 4 new entries in `DEFAULT_LOG_RULES` | Task 5 |
| Per-pattern idempotent `create_default_rules` | Task 5 |
| Backfill migration for existing servers | Task 5 |
| `sppb_exploit` in `CONFIDENCE` / `ACTION_PLAN` / `_IP_LOG_PATTERNS` | Task 6 |
| `_BLOCK_CATEGORY` map | Task 6 |
| `block_category` populated on action creation | Task 6 |
| `_auto_unblock_expired` skips `exploit` blocks | Task 6 |
| `reconfigure_monitoring` service function | Task 7 |
| `POST /reconfigure-monitoring` endpoint | Task 7 |
| Frontend "Reconfigure Monitoring" button + result | Task 8 |

All spec requirements covered. No placeholders or TBDs in task steps.
