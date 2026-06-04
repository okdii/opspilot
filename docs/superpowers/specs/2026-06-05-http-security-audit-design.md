# HTTP Security Audit — Design Spec
Date: 2026-06-05

## Overview

Extend OpsPilot's HTTP service monitoring to perform a full security posture audit on every HTTPS service — covering TLS configuration, cipher strength, certificate integrity, and HTTP security headers. Results are stored per-service, surfaced as a letter grade (A+–F) with a detailed breakdown, and severe findings fire real alerts.

---

## Decisions (locked)

- **Approach**: New `security_checker.py` module, separate from `probe.py` and `ssl_checker.py`
- **Alerting**: Hybrid — only the most severe findings fire alerts; cosmetic findings are display-only
- **Display**: Security grade column on SSL & Domains page + full Security tab in service detail
- **Score format**: Letter grade A+–F with a numeric score (0–100) and a legend
- **TLS depth**: Full — negotiate handshake, enumerate accepted protocols, detect weak ciphers, check PFS and OCSP stapling
- **Check frequency**: Triggered from `probe_service()` when `last_security_scan` > 24 h ago; also fires immediately on service creation

---

## 1. Data Layer

### New table: `service_security_scans`

One row per completed scan per service. Latest row = current posture. Key fields indexed; full breakdown in JSONB so new checks never require schema migrations.

```sql
CREATE TABLE service_security_scans (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_id        UUID NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    scanned_at        TIMESTAMPTZ NOT NULL,

    -- Score
    grade             VARCHAR(2) NOT NULL,   -- A+, A, B, C, D, E, F
    score             INT NOT NULL,          -- 0–100

    -- TLS
    tls_version       VARCHAR,               -- TLSv1.3, TLSv1.2, TLSv1.1, TLSv1.0, SSLv3
    tls_ok            BOOLEAN,
    cipher_suite      VARCHAR,
    cipher_ok         BOOLEAN,               -- false if RC4/DES/3DES/NULL
    pfs_supported     BOOLEAN,
    key_size          INT,                   -- RSA bits or ECDSA curve size
    key_size_ok       BOOLEAN,               -- >= 2048 RSA or >= 256 ECDSA
    self_signed       BOOLEAN,
    ocsp_stapling     BOOLEAN,

    -- HTTP headers
    https_redirect    BOOLEAN,
    hsts              BOOLEAN,
    hsts_max_age      INT,
    csp               BOOLEAN,
    x_frame_options   BOOLEAN,
    x_content_type    BOOLEAN,
    referrer_policy   BOOLEAN,
    permissions_policy BOOLEAN,
    server_disclosure BOOLEAN,               -- Server header leaks version number
    x_powered_by      VARCHAR,              -- raw value; NULL if absent

    -- Full findings
    findings          JSONB NOT NULL DEFAULT '[]'
    -- [{check, severity, passed, detail}]
);

CREATE INDEX ON service_security_scans (service_id, scanned_at DESC);
```

### Column added to `services`

```sql
ALTER TABLE services ADD COLUMN last_security_scan TIMESTAMPTZ;
```

### Scoring weights

| Category      | Max pts | Key rules |
|---------------|---------|-----------|
| TLS protocol  | 25      | TLS 1.3=25, TLS 1.2=20, TLS 1.1=5, TLS 1.0/SSL=0 |
| Cipher suite  | 20      | No weak + PFS=20, no PFS=15, 3DES=5, RC4/NULL=0 |
| Certificate   | 15      | Key size ok=5, not self-signed=5, OCSP=5 |
| HTTP headers  | 30      | HSTS=10, CSP=8, X-Frame=4, X-Content-Type=3, Referrer=3, Permissions=2 |
| Protocol      | 10      | HTTPS redirect=5, no Server disclosure=3, no X-Powered-By=2 |

### Grade scale

| Grade | Score |
|-------|-------|
| A+    | 100   |
| A     | 90–99 |
| B     | 75–89 |
| C     | 60–74 |
| D     | 45–59 |
| E     | 30–44 |
| F     | 0–29  |

---

## 2. Security Checker Module

**File**: `backend/app/services/security_checker.py`

### Internal functions

#### `_audit_tls(hostname, port) → TLSAudit`
Runs in a thread (blocking socket work):
- Negotiate TLS handshake → extract `tls_version`, `cipher_suite`
- Parse cert DER via `cryptography` library → `key_size`, `self_signed` (issuer == subject CN)
- Detect PFS: cipher name contains `ECDHE` or `DHE`
- Detect OCSP stapling: TLS extension 18 present in server hello
- Enumerate accepted protocols: retry handshake forcing TLS 1.0, then TLS 1.1 — sets `tls_ok=False` if either succeeds

#### `_audit_headers(url) → HeaderAudit`
Two httpx requests:
1. GET `http://` version with `follow_redirects=False` → check for 301/302 to `https://` (sets `https_redirect`)
2. GET `https://` version with `follow_redirects=True` → parse all response headers

Header checks:
- `hsts`, `hsts_max_age` from `Strict-Transport-Security`
- `csp` from `Content-Security-Policy`
- `x_frame_options` from `X-Frame-Options`
- `x_content_type` from `X-Content-Type-Options: nosniff`
- `referrer_policy` from `Referrer-Policy`
- `permissions_policy` from `Permissions-Policy`
- `server_disclosure`: `Server` header contains a version number (regex `[\d\.]+`)
- `x_powered_by`: raw `X-Powered-By` value, `None` if absent

#### `_compute_score(tls, headers) → (score, grade, findings)`
Pure function. Applies the weight table above. Returns:
- `score: int` (0–100)
- `grade: str` (A+, A, B, …, F)
- `findings: list[dict]` — one entry per check with `{check, severity, passed, detail}`

`severity` values: `critical` | `warning` | `info`

#### `run_security_check(service_id) → None` (public entry point)
1. Load service — skip if not HTTP or not `is_active`
2. Run `_audit_tls` + `_audit_headers` (sequential, same thread pool)
3. Compute score + grade via `_compute_score`
4. INSERT row into `service_security_scans`
5. Update `services.last_security_scan = now`
6. Fire/resolve alerts for severe findings
7. Broadcast `service_security_updated` WS event

---

## 3. Alert Mapping

Only severe findings fire alerts. All others are display-only.

| Finding | Alert type | Severity | Resolve condition |
|---------|------------|----------|-------------------|
| TLS 1.0 or 1.1 accepted | `security_tls_deprecated` | critical | Next scan: tls_ok = True |
| SSLv3 accepted | `security_tls_deprecated` | critical | Next scan: tls_ok = True |
| RC4 / DES / NULL cipher | `security_weak_cipher` | critical | Next scan: cipher_ok = True |
| Self-signed certificate | `security_self_signed` | warning | Next scan: self_signed = False |
| Grade F | `security_grade_f` | warning | Next scan: grade != 'F' |

All four alert types use `service_id` as the FK. No domain/ssl_cert FK.

### Probe integration

In `probe_service()` (`probe.py`), after the uptime check:

```python
needs_security = (
    service.type == "http"
    and service.is_active
    and (
        service.last_security_scan is None
        or (now - _aware(service.last_security_scan)) > timedelta(hours=24)
    )
)
if needs_security:
    await run_security_check(service_id)
```

Also called immediately after service creation (same pattern as `probe_now`).

### WebSocket event

```json
{
  "event": "service_security_updated",
  "data": {
    "service_id": "...",
    "grade": "B",
    "score": 78,
    "scanned_at": "2026-06-05T02:00:00Z"
  }
}
```

---

## 4. API Changes

### New endpoint

```
GET /api/organizations/{org_id}/services/{service_id}/security
```

Response schema `ServiceSecurityOut`:
```
{
  grade: str,
  score: int,
  scanned_at: datetime,
  tls: {
    version, ok, cipher_suite, cipher_ok, pfs, key_size, key_size_ok,
    self_signed, ocsp
  },
  headers: {
    https_redirect, hsts, hsts_max_age, csp, x_frame_options,
    x_content_type, referrer_policy, permissions_policy,
    server_disclosure, x_powered_by
  },
  findings: [{ check, severity, passed, detail }]
}
```

Returns HTTP 404 if no scan has run yet. Frontend shows "Not scanned yet — will run within 24 h of first probe."

### Extended SSL domains endpoint

Existing `GET /api/organizations/{org_id}/ssl-domains` returns service rows via `ServiceSslOut`. Add two new nullable fields:

```
security_grade: str | None
security_score: int | None
```

Populated by a LEFT JOIN on `service_security_scans` (latest scan per service, via `DISTINCT ON (service_id) ORDER BY scanned_at DESC`).

### New alert types

Added to the `Alert.type` enum:
- `security_tls_deprecated`
- `security_weak_cipher`
- `security_self_signed`
- `security_grade_f`

All use `service_id` FK in `fire_alert`.

---

## 5. Frontend

### New shared component: `SecurityGrade.vue`

Located: `frontend/src/components/SecurityGrade.vue`

Props: `grade: string | null`, `score: number | null`, `size: 'sm' | 'md' | 'lg'`

Color mapping:
| Grade | Color |
|-------|-------|
| A+, A | green `#22c55e` |
| B | teal `#14b8a6` |
| C | yellow `#eab308` |
| D | orange `#f97316` |
| E, F | red `#ef4444` |
| null | gray `—` (not scanned) |

Clicking the badge shows a tooltip with the numeric score.

### New `SecurityTab.vue` — service detail drawer

Located: `frontend/src/components/services/tabs/SecurityTab.vue`

Layout:
```
┌─────────────────────────────────────┐
│  Grade  A     Score 92/100          │
│  Last scanned: 2026-06-05 02:00 UTC │
├─────────────────────────────────────┤
│ ▶ TLS Protocol          ✅ 25/25   │
│ ▶ Cipher Suite          ✅ 20/20   │
│ ▶ Certificate           ⚠️  10/15  │
│ ▶ HTTP Headers          ✅ 27/30   │
│ ▶ Protocol              ✅  9/10   │
├─────────────────────────────────────┤
│ Grade Legend                        │
│ A+ Perfect · A Excellent            │
│ B  Good    · C  Fair                │
│ D  Poor    · E  Bad  · F  Critical  │
└─────────────────────────────────────┘
```

Each collapsible section shows individual check rows with pass/fail icon and the `detail` string from `findings`. Empty state: "Security scan not yet run — will run within 24 h of first probe."

### SSL & Domains page — `SslDomainsView.vue`

- Add **Security** column after the Status column
- Shows `<SecurityGrade size="sm">` for `type='service'` rows
- Shows `—` for `type='domain'` and `type='ssl'` rows (not applicable)
- Column is sortable by `security_score`
- Column header has a `?` icon that opens a `VaPopover` with the grade legend (A+–F descriptions, one line each)

### Grade legend copy

| Grade | Label | Description |
|-------|-------|-------------|
| A+ | Perfect | All checks pass, including OCSP and PFS |
| A | Excellent | All critical checks pass |
| B | Good | Minor issues only |
| C | Fair | Some important headers missing |
| D | Poor | Multiple issues, including header gaps |
| E | Bad | Serious configuration problems |
| F | Critical | Deprecated TLS, broken ciphers, or severe misconfiguration |

---

## Out of Scope

- Cookie `Secure`/`HttpOnly` flag checking (requires session-based probing)
- DNS CAA / DNSSEC checks (separate domain concern)
- Qualys SSL Labs integration
- Historical grade trend chart (future phase)
- Security audit for TCP/DB service types
