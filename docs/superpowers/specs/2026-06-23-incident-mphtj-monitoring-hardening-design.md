# Design: MPHTJ Incident — Monitoring Hardening & Detection Gap Fixes

**Date:** 2026-06-23  
**Incident:** CVE-2026-48908 — SP Page Builder unauthenticated file upload (RCE) on mphtj.gov.my  
**Reference:** SECURITY-INCIDENT-REPORT-2026-06-23.md, OpsPilot Incident Review  
**Scope:** All 5 detection/response gaps identified post-incident; applies to existing + new servers

---

## Problem Summary

OpsPilot was running on MPHTJ during the active compromise but missed the entire attack. Five root causes:

1. **Gap 1 (Critical):** Fluent Bit tails `/var/log/nginx/access.log` only. The site vhost writes to `/var/log/nginx/mphtj.access.log`. 377+ exploit lines never reached the backend.
2. **Gap 2:** No detection rule for `com_sppagebuilder` / `asset.uploadCustomIcon` (CVE-2026-48908).
3. **Gap 3 (High):** Audit `webroot_write` rule watches `/var/www`. Real webroot is `/home/mphtj/web`. Zero webshell-plant events fired.
4. **Gap 4:** Agent is heartbeat-only; no local fallback when cloud detection fails (by design — out of scope for this fix).
5. **Gap 5:** `block_ip` auto-unblock expired scanner blocks during active exploitation, re-admitting previously banned IPs.

---

## Design

### 1. Data Model

**One Alembic migration** adding three columns:

| Table | Column | Type | Default | Purpose |
|-------|--------|------|---------|---------|
| `servers` | `extra_nginx_log_paths` | `JSON` | `[]` | Vhost-specific log paths beyond `/var/log/nginx/access.log` |
| `servers` | `detected_webroot` | `VARCHAR` | `NULL` | Real document root found in nginx vhost `root` directives |
| `security_actions` | `block_category` | `VARCHAR` | `NULL` | `"exploit"` \| `"scanner"` \| `"ssh"` — controls auto-unblock TTL |

---

### 2. SSH Discovery Functions (Gap 1 + Gap 3)

Two new functions in `backend/app/services/onboarding.py`, both called during onboarding and reconfigure. Both are best-effort — any SSH failure returns a safe default without aborting the parent operation.

**`_fetch_nginx_t(ssh: SSHSession) → str`**

Single helper that runs `nginx -T 2>/dev/null` and returns stdout. Returns `""` on SSH error or non-zero exit. Called once per onboarding/reconfigure; its output is passed to both parsers below.

**`_discover_nginx_vhost_logs(nginx_t_output: str) → list[str]`**

Pure function (no SSH call). Given the `nginx -T` stdout:
1. Parse all `access_log` directives across all `server {}` blocks via regex.
2. Filter out: `/var/log/nginx/access.log` (already hardcoded in template), `off`, `stderr`, duplicates.
3. Return unique extra paths. Example for MPHTJ: `["/var/log/nginx/mphtj.access.log"]`.
4. On empty input: return `[]`.

**`_discover_webroot(nginx_t_output: str) → str`**

Pure function (no SSH call). Given the `nginx -T` stdout:
1. Extract `root` directives from all server blocks.
2. Return the first non-standard root (not `/var/www`, `/usr/share/nginx/html`, `/srv/www`, `/var/www/html`).
3. Fallback: `"/var/www/html"`.
4. On empty input: return `"/var/www/html"`.

**Integration into existing onboarding** — `configure_fluent_bit` calls `_fetch_nginx_t` once, then passes the output to both `_discover_nginx_vhost_logs` and `_discover_webroot`. Results are written to `server.extra_nginx_log_paths` and `server.detected_webroot` before the Fluent Bit config is rendered.

---

### 3. Config Generation Changes

**`fluent-bit.conf.j2`** — add a loop immediately after the hardcoded nginx access INPUT:

```jinja2
{% for extra_path in extra_nginx_log_paths %}
# ── Nginx vhost access ({{ extra_path }}) ────────────────────────────────
[INPUT]
    Name              tail
    Path              {{ extra_path }}
    Tag               nginx_access
    DB                /var/lib/fluent-bit/{{ extra_path | replace('/', '_') | replace('.', '_') }}.db
    Skip_Long_Lines   On
{% endfor %}
```

Tagged `nginx_access` so all existing detection rules (matching `source LIKE '%access%'`) apply without changes.

**`_AUDITD_SETUP`** — convert from a module-level string constant to a function `_build_auditd_setup(webroot: str) -> str`. The shell script contains `$WEBUID` and other `$` variables, so the function must **not** use an f-string over the whole block (which would try to interpolate `$WEBUID`). Instead, use string `.replace("{webroot}", webroot)` on a template where only the literal text `{webroot}` is a placeholder — all other `$VAR` shell variables are left untouched:

```python
_AUDITD_SETUP_TEMPLATE = """
...
-w {webroot} -p wa -k webroot_write
...
"""

def _build_auditd_setup(webroot: str) -> str:
    return _AUDITD_SETUP_TEMPLATE.replace("{webroot}", webroot)
```

**`opspilot-action` wrapper** — `_OPSPILOT_ACTION_SCRIPT` becomes a template. The `_validate_path` function's allowed-roots list includes the detected webroot as an additional entry alongside the existing standard roots. Regenerated and re-pushed on every onboarding/reconfigure run.

---

### 4. Detection Rules (Gap 2)

**`DEFAULT_LOG_RULES` additions in `backend/app/routers/alert_rules.py`:**

```python
# SP Page Builder CVE-2026-48908
("%access%", "%com_sppagebuilder%uploadCustomIcon%", "critical", 1, 300),
# Case-insensitive PHP upload extensions missed by existing .php rules
("%access%", "%/media/%.PHP%", "critical", 1, 300),
("%access%", "%/media/%.pHp%", "critical", 1, 300),
# High-volume POST to index.php 200 (generic CMS exploit signal)
("%access%", "%POST%index.php% 200 %", "warning", 10, 60),
```

**`security_responder.py` wiring for `sppb_exploit`:**

```python
CONFIDENCE["sppb_exploit"] = "high"
ACTION_PLAN["sppb_exploit"] = [("block_ip", 1)]
_IP_LOG_PATTERNS["sppb_exploit"] = "%com_sppagebuilder%"
```

**`create_default_rules` idempotency fix** — currently skips all rule insertion if the server has *any* existing log rule. Change to per-pattern check: for each entry in `DEFAULT_LOG_RULES`, only insert if no `LogAlertRule` with that exact `(server_id, source, pattern)` exists. This makes the function safe to call on MPHTJ and other existing servers without duplicating their current rules.

---

### 5. Differentiated Block TTL (Gap 5)

**`block_category` mapping** — populate on `SecurityAction` creation in `security_responder.py`:

```python
_BLOCK_CATEGORY = {
    "jce_exploit_attempt":   "exploit",
    "sppb_exploit":          "exploit",
    "webshell_upload":       "exploit",
    "webshell_execution":    "exploit",
    "webshell_command_exec": "exploit",
    "probe_scan":            "scanner",
    "ssh_brute_force":       "ssh",
}
```

**`_auto_unblock_expired`** — skip any `SecurityAction` where `block_category == "exploit"`. Scanner and SSH blocks keep the existing `block_ttl_hours` setting unchanged.

---

### 6. Reconfigure Endpoint + UI

**`POST /api/servers/{id}/reconfigure-monitoring`** — admin-only, synchronous (completes in ~5–10 SSH commands, no background job needed).

Steps in order:
1. Open SSH session.
2. Run `nginx -T` once; pass output to both `_discover_nginx_vhost_logs` and `_discover_webroot`.
3. Re-run `_setup_auditd` with discovered webroot.
4. Re-push `opspilot-action` wrapper with updated `_validate_path` roots.
5. Regenerate Fluent Bit config from template with new `extra_nginx_log_paths` and `detected_webroot`.
6. Write config via SSH; run `systemctl restart fluent-bit`.
7. Update `server.extra_nginx_log_paths` and `server.detected_webroot` in DB.
8. Call `create_default_rules` (per-pattern idempotent) to seed any missing rules including SPPB.
9. Return `{ extra_logs_added: [...], webroot: "...", rules_added: N, warnings: [...] }`.

Any step failure appends to `warnings` and continues — partial success is valid. A 500 is only returned if the SSH session cannot be opened at all.

**Frontend** — single **"Reconfigure Monitoring"** button in the server settings panel. Loading state during request. On success: inline result toast listing changes (e.g. `"Found 1 additional log file · Webroot updated to /home/mphtj/web · 4 new alert rules added"`). On partial success: same toast with a warning icon for skipped steps.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/models/server.py` | Add `extra_nginx_log_paths`, `detected_webroot` columns |
| `backend/app/models/other.py` | Add `block_category` column to `SecurityAction` (line ~161) |
| `backend/app/migrations/versions/XXXX_monitoring_hardening.py` | Alembic migration |
| `backend/app/services/onboarding.py` | Add `_discover_nginx_vhost_logs`, `_discover_webroot`; update `_AUDITD_SETUP` → `_build_auditd_setup(webroot)`; update `_OPSPILOT_ACTION_SCRIPT` to be templated; integrate both into `configure_fluent_bit` |
| `backend/app/services/templates/fluent-bit.conf.j2` | Add `extra_nginx_log_paths` loop block |
| `backend/app/routers/alert_rules.py` | Add 4 new entries to `DEFAULT_LOG_RULES`; fix `create_default_rules` to per-pattern idempotency |
| `backend/app/services/security_responder.py` | Add `sppb_exploit` to `CONFIDENCE`, `ACTION_PLAN`, `_IP_LOG_PATTERNS`; add `_BLOCK_CATEGORY` map; populate `block_category` on action creation; update `_auto_unblock_expired` to skip exploit blocks |
| `backend/app/routers/servers.py` (or new router) | Add `POST /api/servers/{id}/reconfigure-monitoring` |
| `frontend/src/pages/ServerSettings.vue` (or equivalent) | Add "Reconfigure Monitoring" button + result toast |

---

## Out of Scope

- Gap 4 (no local agent security enforcement) — architectural, separate design required
- Joomla / SP Page Builder version detection during onboarding (Section 8, Priority 4)
- Monitoring coverage health UI (Approach 3 from brainstorm — follow-on if needed)
- fail2ban filter update for SPPB (server-side manual fix per Section 9.3)
