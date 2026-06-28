# Track A — Quarantine Hardening

**Document date:** 2026-06-28
**Source audit:** MPHTJ OpsPilot Security Audit Report (2026-06-25)
**Findings addressed:** #3 (quarantine 0% success), #1 (wrong file path)

---

## Goal

Fix `quarantine_file` auto-response so it targets the correct file on the correct server path, and never wastes an SSH call on a file that was never served.

---

## Root causes (from audit)

1. `_extract_file()` hardcodes `/var/www/html` — ignores `server.detected_webroot` which already exists on the model and is populated during onboarding
2. `_extract_file()` fallback uses `%.php%` (now `%POST%.php%` after v1.2.98) but still picks `index.php` paths, not actual webshell paths
3. All 923 MPHTJ quarantine failures were on **403** responses — attack probes that nginx blocked before the file was ever served; quarantine on a non-existent file always fails

---

## What already exists

- `Server.detected_webroot: str | None` — column present since migration 0034, populated by `onboarding._discover_webroot(nginx -T output)`
- `_resolve_target(db, alert, action_type, server)` — already receives `server` object, just doesn't pass it to `_extract_file`
- `onboarding.py:1063` — already uses `server.detected_webroot or "/var/www/html"` for action scripts

---

## Architecture

Three independent fixes, all backend:

```
_resolve_target(db, alert, "quarantine_file", server)
    │
    ├── [NEW] HTTP 200 gate — skip if alert.message has no " 200 "
    │         → log "skipped: file not served (non-200 response)"
    │
    └── _extract_file(db, alert, server)   ← server now passed
            │
            ├── auditd webroot_write path (unchanged, highest priority)
            │
            └── fallback: access-log POST line
                    webroot = server.detected_webroot or "/var/www/html"
                    path = webroot + matched php path (strip query string)
```

---

## Section 1 — HTTP 200 gate

**File:** `backend/app/services/security_responder.py`

In `_resolve_target`, before dispatching `quarantine_file`, check:

```python
if action_type == "quarantine_file":
    if " 200 " not in (alert.message or ""):
        logger.info(
            "quarantine skipped for alert %s: non-200 response (file not served)",
            alert.id,
        )
        return None
    return await _extract_file(db, alert, server)
```

Returning `None` causes the caller to skip the action (existing behaviour for unresolved targets).

---

## Section 2 — `_extract_file` uses server webroot

**File:** `backend/app/services/security_responder.py`

Change signature: `async def _extract_file(db, alert, server) -> str | None`

Update the fallback path prefix:

```python
webroot = (server.detected_webroot or "/var/www/html").rstrip("/")
return webroot + m.group(1).split("?")[0]
```

Update call site in `_resolve_target`:

```python
return await _extract_file(db, alert, server)
```

---

## Section 3 — Server Settings webroot field

**Files:**
- `backend/app/schemas/server.py` — add `detected_webroot: str | None` to `ServerPatch`
- `backend/app/routers/servers.py` — allow PATCH to update `detected_webroot`
- `frontend/src/components/servers/tabs/InfoTab.vue` — add "Web Root" text input in the server settings section (admin only)

**Behaviour:**
- Field labelled "Web Root" with placeholder `/var/www/html`
- Shows current value (from onboarding detection or previous manual entry)
- On save, PATCHes `detected_webroot` on the server row
- Help text: "Detected automatically during onboarding. Override if your site root differs."

---

## Files changed

| File | Change |
|------|--------|
| `backend/app/services/security_responder.py` | HTTP 200 gate in `_resolve_target`; pass `server` to `_extract_file`; use `server.detected_webroot` in fallback |
| `backend/app/schemas/server.py` | Add `detected_webroot` to `ServerPatch` |
| `backend/app/routers/servers.py` | Allow PATCH to write `detected_webroot` |
| `frontend/src/components/servers/tabs/InfoTab.vue` | Web Root field in settings section |

No new migration needed — column already exists.

---

## What is NOT in this spec

- Safelist for monitor/bot IPs — not needed after v1.2.98 POST-filter + majority-vote fix
- Re-probe webroot button — manual field covers this; onboarding already detects on fresh installs
- Quarantine for 403 attacks — by design excluded (files not on disk)
- Quarantine action disabling — HTTP 200 gate achieves the same outcome without a new toggle

---

## Testing

1. Ensure `server.detected_webroot` is set (or manually patch via API)
2. Fire a `webshell_execution` alert with ` 200 ` in the message → quarantine_file attempts, uses correct webroot
3. Fire a `webshell_execution` alert without ` 200 ` (e.g. 403) → quarantine_file skipped, logged
4. PATCH `detected_webroot` via Server Settings UI → value persists, used on next quarantine attempt
