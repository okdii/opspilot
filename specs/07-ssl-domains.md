# Spec 07 — SSL & Domain Monitoring

**Version:** 1.0  
**Date:** 2026-06-01  
**Status:** Approved

---

## 1. Overview

SSL & Domain Monitoring tracks two related but distinct expiry signals:

- **SSL certificates** — the TLS cert served on a port (default 443), checked daily via direct socket connection
- **Domain registration** — the WHOIS expiry date for a domain name, checked daily via `python-whois`

A `Domain` record is the parent entity. An `SSLCert` record always has a `domain_id` FK to a `Domain` — orphaned SSL records are not allowed. Both are scoped to an `Organization` (not to a specific server). The combined `/ssl-domains` page shows both in a unified, sortable table with an expiry timeline chart.

PRD references: §5.6, §5.9, §5.16.7, §9 (Domain, SSLCert models)

---

## 2. Routes

| Route | Access | Description |
|---|---|---|
| `/ssl-domains` | All roles | Combined SSL cert + domain list for active org |

Single-page design — no separate detail page in v1. All actions (add/edit/delete) open modals from this page.

---

## 3. Page Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ SSL & Domain Monitoring                      [+ Add Domain]          │
│                                                                      │
│  Expiry Timeline                                                     │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  ·           ·     ·          ·   ·                           │  │
│  │──────────────────────────────────────────────────────────────  │  │
│  │ Today       +30d            +60d         +90d                  │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  Filter: [All Types ▼]  [All Status ▼]  [Search _____________]       │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ Name           Type   Expiry Date   Days Left   Status  [⋮]   │  │
│  ├────────────────────────────────────────────────────────────────┤  │
│  │ example.com    Domain  2026-11-14    166 days   ✓ Valid  [⋮]  │  │
│  │ example.com    SSL     2026-09-02    93 days    ✓ Valid  [⋮]  │  │
│  │ api.client.io  Domain  2026-07-20    49 days    ⚠ Expiring [⋮]│  │
│  │ api.client.io  SSL     2026-07-05    34 days    ⚠ Expiring [⋮]│  │
│  │ old-site.net   SSL     2026-06-08    7 days     ✕ Critical [⋮]│  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. Expiry Timeline Chart

### 4.1 Chart Type

Scatter / milestone chart (ApexCharts `scatter` type). Horizontal x-axis = calendar date. Each item is a dot placed at its expiry date. Hovering a dot shows a tooltip.

```
Today                                               +180 days
  │                                                      │
  │   ✕          ⚠           ○           ○              │
  │ old-site   api.client  example.com  client2.net     │
  └──────────────────────────────────────────────────────┘
```

### 4.2 Dot Colour Coding

| Colour | Condition |
|---|---|
| Red | `status = 'critical'` or `status = 'expired'` |
| Amber | `status = 'expiring_soon'` |
| Green | `status = 'valid'` |
| Grey | `status = 'unreachable'` (SSL only) |

### 4.3 Tooltip on Hover

```
example.com — SSL Certificate
Expires: 2026-09-02
Days remaining: 93
Issuer: Let's Encrypt Authority X3
Status: Valid ✓
```

For Domain dots:
```
example.com — Domain Registration
Expires: 2026-11-14
Days remaining: 166
Registrar: Namecheap, Inc.
Status: Valid ✓
```

### 4.4 X-Axis Range

Spans from today to today + 365 days. Items expiring more than 365 days out are not plotted. Items already expired show at day 0 (today's position) with a red dot and a dashed vertical "Today" line clearly visible.

### 4.5 Click Action

Clicking a dot scrolls the table below to the matching row and briefly highlights it with a yellow outline (600ms fade).

---

## 5. Combined Table

### 5.1 Column Definitions

| Column | Description | Sortable |
|---|---|---|
| Name | Domain name or `domain:port` for SSL | Yes |
| Type | `Domain` badge (indigo) or `SSL` badge (cyan) | Yes |
| Expiry Date | `YYYY-MM-DD` | Yes (default sort: ascending) |
| Days Left | Integer, or `—` for unreachable SSL | Yes |
| Progress Bar | Horizontal bar, colour-coded | No |
| Status | Status chip | Yes |
| Last Checked | Relative time | No |
| [⋮] | Kebab menu | No |

### 5.2 Row Grouping

Rows are grouped by domain name — the Domain row appears first, immediately followed by its SSL cert row (if one exists). If a domain has no SSL cert, an "Add SSL +" inline chip appears in the SSL row slot.

```
  example.com    Domain   2026-11-14   166 days  ████████████ ✓ Valid
  example.com    SSL      2026-09-02    93 days  ████████░░░░ ✓ Valid  [⋮]
  api.client.io  Domain   2026-07-20    49 days  ████░░░░░░░░ ⚠ Expiring
  api.client.io  SSL      [+ Add SSL cert]
```

### 5.3 Progress Bar Colour Thresholds

| Days Remaining | Bar Colour |
|---|---|
| > 30 | Green |
| 8–30 | Amber |
| 1–7 | Red |
| 0 or expired | Red (solid, pulsing) |
| null (unreachable) | Grey (bar empty) |

### 5.4 Status Chips

| Status | Chip Label | Colour |
|---|---|---|
| `valid` | ✓ Valid | Green |
| `expiring_soon` | ⚠ Expiring | Amber |
| `critical` | ✕ Critical | Red |
| `expired` | ✕ Expired | Red (pulsing) |
| `unreachable` | — Unreachable | Grey (SSL only) |

### 5.5 Sort

Default: ascending by `expiry_date` with critical/expired items floated to top. User can click column headers to re-sort. Sort state preserved during the session (not persisted across page loads).

### 5.6 Filter Bar

| Control | Type | Behaviour |
|---|---|---|
| All Types | Dropdown | Domain / SSL / All |
| All Status | Dropdown | Valid / Expiring / Critical / Expired / Unreachable / All |
| Search | Text input | Filters by domain name, live, debounced 300ms |

---

## 6. Add Domain Modal

### 6.1 Trigger

`[+ Add Domain]` button in page header. Opens a centred modal (480px wide).

### 6.2 Form Fields

| Field | Type | Default | Validation |
|---|---|---|---|
| Domain Name | Text | — | Required; lowercase; strip leading `www.`; strip protocol (`https://`); example.com format; max 253 chars |
| Warn at (days) | Number | 60 | 1–365 |
| Critical at (days) | Number | 30 | 1–(warn_days - 1) |

**Domain normalisation:** Client-side strip on blur:
- Remove `https://`, `http://`, `www.` prefixes
- Lowercase
- Preview shows normalised value below the input: "Will be saved as: `example.com`"

**Duplicate check:** If a domain with the same name already exists in this org, show inline error: "example.com is already tracked in this organisation."

### 6.3 Submit Behaviour

POST `/api/domains` → modal closes → new row appears at top of table with grey "Checking..." status (server returns the created record with `status = 'checking'`, `last_checked = null`) → WHOIS lookup runs in background → row updates when complete.

**Polling:** Frontend calls `GET /api/organizations/:org_id/ssl-domains` every 10s until the new domain's `last_checked` is non-null (max 5 polls). Uses the combined fetch — no single-record endpoint needed. After 5 polls with no result, show "Could not retrieve WHOIS data — will retry tomorrow."

**Initial creation state returned by POST `/api/domains`:**
```json
{ "id": "uuid", "domain": "example.com", "status": "checking", "last_checked": null,
  "registrar": null, "expiry_date": null, "days_remaining": null,
  "warn_days": 60, "critical_days": 30 }
```

### 6.4 Add SSL Cert (from table inline chip or domain row)

Triggered two ways:
1. Click `[+ Add SSL cert]` inline chip in the SSL row slot in the table
2. Click `[⋮] → Add SSL Cert` on the Domain row

Opens a smaller modal (420px):

| Field | Type | Default | Validation |
|---|---|---|---|
| Domain | Display-only | Pre-filled from parent domain | Not editable |
| Port | Number | 443 | 1–65535 |
| Warn at (days) | Number | 30 | 1–365 |
| Critical at (days) | Number | 7 | 1–(warn_days - 1) |

Submit: POST `/api/ssl-certs` → modal closes → SSL row appears with grey "Checking..." status (server returns the created record with `status = 'checking'`, `last_checked = null`, `issuer = null`, `expiry_date = null`, `days_remaining = null`) → SSL check runs immediately in background → same combined-endpoint 10s polling pattern, max 5 polls.

---

## 7. Edit Domain / Edit SSL Cert Modal

### 7.1 Edit Domain

Triggered: `[⋮] → Edit` on Domain row.

Editable fields: `warn_days`, `critical_days`. Domain name is **not editable** after creation (shown as read-only text with explanation: "Domain name cannot be changed — delete and re-add if needed.").

### 7.2 Edit SSL Cert

Triggered: `[⋮] → Edit` on SSL row.

Editable fields: `port`, `warn_days`, `critical_days`.

Both modals: PATCH `/api/domains/:id` or PATCH `/api/ssl-certs/:id` → row updates in place.

---

## 8. Delete Domain / Delete SSL Cert

### 8.1 Delete SSL Cert

Triggered: `[⋮] → Delete` on SSL row.

Confirmation modal:
```
Delete SSL cert for example.com:443?

This will permanently remove:
  • All SSL check history

[Cancel]  [Delete SSL Cert]
```

No typed-name confirmation required (lower stakes than server/service delete). Single confirm click.

### 8.2 Delete Domain

Triggered: `[⋮] → Delete` on Domain row.

If a linked SSL cert exists, domain deletion is **blocked**:

```
Cannot Delete Domain

example.com has a linked SSL certificate.
Delete the SSL cert first, then delete the domain.

[Close]
```

If no linked SSL cert, standard confirmation:

```
Delete example.com?

This will permanently remove:
  • Domain registration record
  • All linked alert history

[Cancel]  [Delete Domain]
```

---

## 9. Force Re-check

Available from `[⋮]` menu on any row:

- `[⋮] → Check Now` — triggers an immediate background check for that record.
- Toast appears: "Re-checking example.com... this may take a few seconds."
- Row enters a "Checking..." transient state (spinner in the Status column).
- On completion (10s polling): row status updates.
- Rate-limited: one manual trigger per record per 5 minutes. If triggered again within 5 min, toast shows "Check already in progress or recently completed."

API: POST `/api/domains/:id/check` and POST `/api/ssl-certs/:id/check`.

Both return `200 { "ok": true }` on success. Rate-limit exceeded returns `429 { "error": "rate_limited", "retry_after_sec": 214 }`. On completion the updated record is visible via the next combined-endpoint poll.

---

## 10. Empty State

When no domains have been added for the active org:

```
┌───────────────────────────────────────────────┐
│                                               │
│       No domains tracked yet                 │
│                                               │
│   Add your domains to get notified before    │
│   SSL certificates or domain registrations   │
│   expire and cause outages.                  │
│                                               │
│           [+ Add Your First Domain]          │
│                                               │
└───────────────────────────────────────────────┘
```

---

## 11. Backend — Checker Jobs

### 11.1 SSL Checker Job

Scheduled: APScheduler `CronTrigger` — runs daily at 02:00 UTC. Job ID: `ssl_checker_daily`.

For each active `SSLCert` record, in sequence:

```
1. Open TCP socket to domain:port with 10s timeout
2. Perform TLS handshake
3. Extract certificate:
   - issuer (CN from issuer field)
   - expiry_date (notAfter)
   - days_remaining = expiry_date - today
4. Update SSLCert:
   - issuer, expiry_date, days_remaining, last_checked = now
   - status:
     - days_remaining > warn_days → 'valid'
     - days_remaining <= warn_days AND > critical_days → 'expiring_soon'
     - days_remaining <= critical_days AND > 0 → 'critical'
     - days_remaining <= 0 → 'expired'
     - socket timeout / connection refused → 'unreachable'; days_remaining = NULL
5. Evaluate alert:
   - status in ('expiring_soon', 'critical') → fire alert if not already firing
   - status = 'valid' → resolve any existing ssl_expiry alert for this cert
```

Library: Python `ssl` module + `cryptography` for cert parsing.

No staggering needed for SSL checks (direct socket, not a shared WHOIS server). 50 certs at 10s timeout each = max 500s sequentially, or run with asyncio for faster completion.

### 11.2 Domain WHOIS Checker Job

Scheduled: APScheduler `CronTrigger` — runs daily at 03:00 UTC. Job ID: `domain_checker_daily`.

Checks are staggered — 30-second delay between each domain — to avoid WHOIS rate-limiting:

```
for each Domain record (ordered by last_checked ASC):
  1. Call python-whois for domain
  2. Extract: registrar, expiry_date
  3. days_remaining = expiry_date - today
  4. Update Domain:
     - registrar, expiry_date, days_remaining, last_checked = now
     - status:
       - days_remaining > warn_days → 'valid'
       - days_remaining <= warn_days AND > critical_days → 'expiring_soon'
       - days_remaining <= critical_days AND > 0 → 'critical'
       - days_remaining <= 0 → 'expired'
  5. Evaluate alert (same as SSL logic above)
  6. Sleep 30 seconds before next domain
```

WHOIS failures (library error, unparseable response, unsupported TLD): log the error, do NOT update `days_remaining` or `status` — preserve last known state. Show `last_checked` as null / stale in the UI.

### 11.3 First-check on Add

When a Domain or SSLCert is added via the API, a one-shot APScheduler job is scheduled immediately (`date` trigger, run_date = now + 2s). This runs the same check logic as the daily job for that single record only. Job ID: `ssl_check_once:{ssl_cert_id}` or `domain_check_once:{domain_id}`.

---

## 12. Pinia Store — `useSslDomainStore`

```ts
// State
domains: Domain[]
sslCerts: SSLCert[]
isLoading: boolean
error: string | null

// Getters
combinedRows: CombinedRow[]   // domains + certs merged, sorted by expiry
criticalCount: number         // items with status 'critical' or 'expired'
expiringCount: number         // items with status 'expiring_soon'
timelineDots: TimelineDot[]   // for the scatter chart

// Actions
fetchAll(org_id: string): Promise<void>      // fetches domains + certs together
createDomain(payload): Promise<Domain>
updateDomain(id: string, payload): Promise<Domain>
deleteDomain(id: string): Promise<void>
createSslCert(payload): Promise<SSLCert>
updateSslCert(id: string, payload): Promise<SSLCert>
deleteSslCert(id: string): Promise<void>
triggerCheck(type: 'domain'|'ssl', id: string): Promise<void>
pollUntilChecked(type: 'domain'|'ssl', id: string): Promise<void>
```

`combinedRows` getter produces an array of shape:
```ts
interface CombinedRow {
  id: string
  domainName: string
  type: 'domain' | 'ssl'
  port?: number
  expiryDate: string | null
  daysRemaining: number | null
  status: string
  lastChecked: string | null
  // Domain-specific
  registrar?: string
  warnDays: number
  criticalDays: number
  // SSL-specific
  issuer?: string
  domainId?: string
}
```

---

## 13. API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/organizations/:org_id/ssl-domains` | Required | Fetch all domains + certs for org (combined) |
| POST | `/api/domains` | Required (Admin) | Create domain |
| PATCH | `/api/domains/:id` | Required (Admin) | Update domain thresholds |
| DELETE | `/api/domains/:id` | Required (Admin) | Delete domain (blocked if SSL cert exists) |
| POST | `/api/domains/:id/check` | Required (Admin) | Trigger immediate WHOIS check |
| POST | `/api/ssl-certs` | Required (Admin) | Create SSL cert (domain_id required) |
| PATCH | `/api/ssl-certs/:id` | Required (Admin) | Update SSL cert thresholds/port |
| DELETE | `/api/ssl-certs/:id` | Required (Admin) | Delete SSL cert |
| POST | `/api/ssl-certs/:id/check` | Required (Admin) | Trigger immediate SSL check |

### 13.1 GET `/api/organizations/:org_id/ssl-domains` Response

```json
{
  "domains": [
    {
      "id": "uuid",
      "domain": "example.com",
      "registrar": "Namecheap, Inc.",
      "expiry_date": "2026-11-14",
      "days_remaining": 166,
      "warn_days": 60,
      "critical_days": 30,
      "last_checked": "2026-06-01T03:14:22Z",
      "status": "valid"
    }
  ],
  "ssl_certs": [
    {
      "id": "uuid",
      "domain_id": "uuid",
      "domain": "example.com",
      "port": 443,
      "issuer": "Let's Encrypt Authority X3",
      "expiry_date": "2026-09-02",
      "days_remaining": 93,
      "warn_days": 30,
      "critical_days": 7,
      "last_checked": "2026-06-01T02:08:44Z",
      "status": "valid"
    }
  ]
}
```

---

## 14. Edge States

| State | Behaviour |
|---|---|
| Domain has no SSL cert | SSL row slot shows `[+ Add SSL cert]` inline chip |
| SSL cert unreachable | `days_remaining = null`, progress bar is empty grey, status chip "— Unreachable"; no expiry alert fired |
| WHOIS lookup fails (unsupported TLD / parse error) | Domain `last_checked` becomes stale; status unchanged; row shows "Check failed" tooltip on `last_checked` cell |
| Domain already expired | `days_remaining <= 0`; status = `expired`; row floats to top; red pulsing chip; existing alert stays open until resolved |
| `critical_days >= warn_days` | Validation error on form: "Critical threshold must be lower than warning threshold" |
| No domains for active org | Empty state shown; no chart |
| All domains valid, no items expiring soon | Timeline chart shows green dots only; no amber/red chips in table |
| Manual re-check within 5-minute window | Toast: "Check already in progress or recently completed"; API returns 429 with `retry_after` seconds |
| Domain deletion blocked by SSL cert | Blocked modal (see §8.2) |
| WHOIS returns no expiry date (some TLDs) | `expiry_date = null`, `days_remaining = null`, status = `'valid'` (assume ok); note displayed: "Expiry date not available for this TLD" |
| More than 50 domains in table | Table virtualised (same pattern as log viewer); timeline chart groups by month for readability |

---

## 15. Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `n` | Open Add Domain modal |
| `Escape` | Close modal |
| `r` | Refresh the combined table |
| `/` | Focus search bar |
