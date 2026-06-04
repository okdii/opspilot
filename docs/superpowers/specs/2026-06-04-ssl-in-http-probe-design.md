# SSL Certificate Tracking Embedded in HTTP Service Probes

**Date:** 2026-06-04  
**Status:** Approved

## Problem

Adding HTTPS service monitoring currently requires two separate registrations:
1. Add the service in Services (uptime probe)
2. Add the same domain again in SSL & Domain (cert expiry)

This is redundant. The HTTP probe already opens a TLS connection to the target — the cert info is available for free at that point.

## Decision

**Approach A — Inline SSL columns on Service.**  
Add 8 SSL tracking columns directly to the `service` table. The HTTP probe extracts cert info via stdlib `ssl` socket after each probe run. SSL expiry alerts use the existing `Alert.service_id` FK with `type="ssl_expiry"`. No changes to `SSLCert`, `Domain`, or `Alert` schema.

The SSL & Domain page retains its existing role: domain WHOIS registration tracking + non-standard-port SSL certs (e.g. IMAPS:993, SMTPS:587). A hint is added to the page noting that HTTPS service SSL is tracked automatically in Services.

---

## Section 1: Schema

New migration adds 8 columns to the `service` table:

| Column | Type | Default | Description |
|---|---|---|---|
| `ssl_enabled` | bool | `false` | Auto-set `true` when URL starts with `https://` |
| `ssl_warn_days` | int | `30` | Warning threshold (days before expiry) |
| `ssl_critical_days` | int | `7` | Critical threshold (days before expiry) |
| `ssl_expiry_date` | datetime (tz) | null | Certificate notAfter date |
| `ssl_days_remaining` | int | null | Computed on each probe run |
| `ssl_status` | varchar(30) | null | `valid` / `expiring_soon` / `critical` / `expired` / `unreachable` |
| `ssl_issuer` | varchar(255) | null | Issuer CN or organization from cert |
| `ssl_last_checked` | datetime (tz) | null | Timestamp of last SSL read |

No changes to `SSLCert`, `Domain`, or `Alert`.

---

## Section 2: Backend

### 2.1 SSL Extraction in probe.py

After the HTTP probe check completes, if `service.ssl_enabled is True`, extract the SSL cert in the same probe cycle.

Reuse `_fetch_ssl_cert(hostname, port)` from `app.services.ssl_checker` — no duplication. Parse hostname and port from `service.url`:
- Strip scheme and path: `https://host:8443/path` → hostname `host`, port `8443`
- Port defaults to `443` when not explicit in URL

**Throttle:** SSL cert is re-read only when `ssl_last_checked` is null or more than 6 hours ago. Probes run as often as every 60 seconds — reading the cert on every cycle would be 1,440 connections/day per service for data that changes at most once per renewal. Six hours gives same-day detection of renewals without the noise.

**Probe flow per HTTP service cycle:**
```
1. _run_check(service)  →  (status, response_ms, cause)   [existing]
2. if ssl_enabled and (ssl_last_checked is null or age > 6h):
     try:
       expiry, issuer = await _fetch_ssl_cert(hostname, port)
       days = (expiry - now()).days
       ssl_status = _compute_status(days, ssl_warn_days, ssl_critical_days)
       update service SSL columns
       fire/resolve ssl_expiry alert with service_id
     except:
       ssl_status = 'unreachable'
       ssl_days_remaining = null
3. persist service + broadcast  [existing path, now includes SSL fields in payload]
```

### 2.2 Alert Behaviour

Uses existing `fire_alert` / `resolve_alert` from `app.services.alerting`:
- `type="ssl_expiry"`, `service_id=service.id`
- `expiring_soon` → severity `warning`
- `critical` or `expired` → severity `critical`
- `valid` → resolve any open `ssl_expiry` alert for this service
- `unreachable` → no alert change (preserve last known state, matching ssl_checker behaviour)

### 2.3 Service Router (create / update)

On **create**:
- Auto-set `ssl_enabled = url.startswith("https://")` server-side
- Accept optional `ssl_warn_days` (default 30) and `ssl_critical_days` (default 7) in request body

On **update**:
- If URL changes from `https://` to `http://`: auto-set `ssl_enabled = false`, clear all SSL columns, resolve any open ssl_expiry alert
- If URL changes from `http://` to `https://`: auto-set `ssl_enabled = true`
- Expose `ssl_warn_days` and `ssl_critical_days` as editable fields

### 2.4 Service API Response

Include all 8 SSL fields in the service response schema so the frontend can display them without a separate endpoint.

---

## Section 3: Frontend

### 3.1 Service Detail Page — SSL Card

For HTTPS services (`ssl_enabled = true`), render an **SSL Certificate** card below the existing uptime/response-time section.

Reuses existing components:
- `StatusBadge` — for ssl_status display
- `ExpiryBar` (from `frontend/src/components/ssl-domains/ExpiryBar.vue`) — progress bar (days remaining vs warn threshold)

Card content:
- Status badge
- Expiry date (YYYY-MM-DD)
- Days remaining
- Issuer name
- ExpiryBar progress visualization
- Last checked (relative time)

Card is hidden entirely for `http://`, TCP, and DB service types.

### 3.2 Add / Edit Service Modal

When service type is `http` and URL starts with `https://`, show a collapsible **SSL Thresholds** section with:
- Warn at `__` days (number input, default 30, range 1–365)
- Critical at `__` days (number input, default 7, must be < warn_days)

Section auto-shows/hides reactively as the URL field changes between `http://` and `https://` prefixes. Hidden for `http://`, TCP, DB types.

### 3.3 Service List / Services Tab on Server Detail

Add a small SSL status pill next to the uptime badge for HTTPS services. Only renders when `ssl_status` is `expiring_soon`, `critical`, or `expired`. No pill for `valid` or null (keeps the list uncluttered).

### 3.4 SSL & Domain Page

No structural changes. Add hint text in the page subtitle or empty state:
> "SSL for HTTPS services is tracked automatically — add non-HTTP SSL certs (e.g. IMAPS, SMTPS) here."

---

## Out of Scope

- No changes to `SSLCert` model or SSL/Domain management flows
- No WHOIS integration for HTTP services
- No manual enable/disable toggle for SSL tracking per service (auto-derived from URL scheme)
- No SSL check history table (single current-state columns only, matching existing SSLCert pattern)
