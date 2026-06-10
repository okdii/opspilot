# Vhost Auto-Discovery — Design Spec
Date: 2026-06-10

## Overview

A "Scan Web Services" button in the ServicesTab lets users auto-discover virtual hosts
from a running nginx, apache, caddy, or litespeed installation via SSH, review the
results, and bulk-register selected domains as HTTP monitoring services.

---

## User Flow

1. User opens a server's ServicesTab, sees nginx/apache running in the system services table
2. Clicks **Scan Web Services** button (top-right of ServicesTab header)
3. SlideOver opens — scanning phase: SSH connects, runs discovery, shows spinner
4. SlideOver transitions to results phase: list of discovered vhosts with checkboxes
5. User reviews, checks/unchecks domains, clicks **Register X services**
6. Each selected domain is registered via `POST /api/services`; success toast on completion

---

## Architecture & Data Flow

```
User clicks "Scan Web Services"
  → SlideOver opens (scanning phase)
  → POST /api/servers/{server_id}/scan-vhosts  [admin only]
      → SSH into server via existing SSHSession
      → detect active web servers (nginx / apache / caddy / litespeed)
      → run discovery command per detected server
      → parse config → extract domain + port + ssl
      → cross-check against existing Service rows for this org
      → return list: { domain, url, scheme, port, server_type, already_monitored }
  → SlideOver shows results (select phase)
  → User selects domains → clicks "Register X services"
  → Frontend calls existing POST /api/services once per selected domain
  → Success toast, SlideOver closes
```

---

## Backend

### Endpoint

`POST /api/servers/{server_id}/scan-vhosts` — admin only

**Response shape:**
```json
[
  {
    "domain": "app.example.com",
    "url": "https://app.example.com",
    "port": 443,
    "scheme": "https",
    "server_type": "nginx",
    "already_monitored": false
  }
]
```

**File:** `backend/app/routers/vhost_scan.py`

### Web Server Detection

Try each in order; all detected servers are scanned (multiple web servers on one box are supported):

| Web Server  | Detection command              |
|-------------|-------------------------------|
| nginx       | `nginx -v`                    |
| apache      | `apache2ctl -v` or `httpd -v` |
| caddy       | `caddy version`               |
| litespeed   | `/usr/local/lsws/bin/lshttpd -v` |

### Discovery Commands & Parsers

| Web Server  | Command                                          | Parser strategy |
|-------------|--------------------------------------------------|-----------------|
| nginx       | `nginx -T`                                       | Regex over merged config: `server_name` + `listen` directives |
| apache      | `apache2ctl -S`                                  | Parse virtual host summary lines: `port 443 namevhost domain.com` |
| caddy       | Read `/etc/caddy/Caddyfile`                      | Regex over site address blocks (e.g. `domain.com`, `:443 { }`) |
| litespeed   | `cat /usr/local/lsws/conf/httpd_config.xml`      | XML parse `<virtualHost>` → `<serverName>` + `<listeners>` |

### Scheme Detection

- Port 443 or `listen 443 ssl` → `https://`
- Port 80 or unlabelled → `http://`

### Already-Monitored Check

After parsing, cross-check each discovered domain against existing `Service` rows
joined through `Server.org_id` for the current org. Set `already_monitored: true`
if a service with a matching URL exists.

### Error Responses

| Condition | Error key | Message |
|-----------|-----------|---------|
| SSH connection failure | `ssh_failed` | "Could not connect to server" |
| No web server detected | `no_webserver` | "No supported web server found (nginx/apache/caddy/litespeed)" |
| Scan timeout (>30s) | `timeout` | "Scan timed out" |
| Zero vhosts found | — | Return empty array `[]` |

---

## Frontend

### Button Placement

ServicesTab header — right-aligned alongside the section title:

```
System Services                    [Scan Web Services]
```

Button only shown to admin users (consistent with `canEdit = isAdmin`).

### SlideOver Component

**File:** `frontend/src/components/servers/VhostScanSlideOver.vue`

**Phase 1 — Scanning:**
- Spinner + "Connecting to server..." status text
- Transitions automatically to Phase 2 on API response

**Phase 2 — Results:**

```
Found 4 web services on this server

☑  https://app.example.com      nginx   [new]
☑  https://api.example.com      nginx   [new]
☐  http://staging.example.com   nginx   [new]     ← unchecked (http)
—  https://admin.example.com    nginx   [already monitoring]  ← grayed, no checkbox

[Cancel]                [Register 2 services →]
```

**Selection defaults:**
- HTTPS domains → checked by default
- HTTP domains → unchecked by default (user must opt in)
- Already monitored → grayed row, no checkbox, "already monitoring" badge

**Footer button:**
- Label updates live: "Register X services" as user checks/unchecks
- Disabled when zero domains selected

### Registration Flow

On submit: call `POST /api/services` for each selected domain sequentially.
- Show per-row progress indicator during registration
- On partial failure: show per-row error, continue remaining registrations
- Final summary toast: "3 services registered" or "3 registered, 1 failed"

### Error States (inside SlideOver)

| Condition | UI |
|-----------|----|
| SSH/connection error | Error message + Retry button |
| No web server found | Empty state: "No supported web server found on this server" |
| Empty results | Empty state: "No virtual hosts found in the web server config" |

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/routers/vhost_scan.py` | New — scan endpoint + four parsers |
| `backend/app/main.py` | Register `vhost_scan` router |
| `frontend/src/components/servers/VhostScanSlideOver.vue` | New — slide-over component |
| `frontend/src/components/servers/tabs/ServicesTab.vue` | Add scan button + wire up SlideOver |
| `frontend/src/services/api.ts` | Add `scanVhosts(serverId)` API call |
