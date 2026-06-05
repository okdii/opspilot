# Domain Auto-SSL, Security Audit & Merged Row Design

**Date:** 2026-06-05
**Status:** Approved

## Problem

Currently:
- Adding a domain tracks WHOIS expiry only — SSL cert must be added separately as a second step
- No security audit for domains (only for HTTP services)
- Service rows were removed from the SSL & Domains page in the last redesign, breaking the org-wide SSL overview
- The table has no Security Grade column for domain rows

## Goal

1. **Auto-SSL on domain registration** — when a domain is added, automatically create an SSL cert record for port 443 and run a security audit against `https://{domain}`
2. **Merged domain row** — domain row shows worst-expiry (WHOIS vs SSL) as primary, both values as a subtitle, and a security grade
3. **Service rows restored** — read-only cross-reference rows so the page is a true org-wide SSL overview
4. **Stat cards + filter** updated to include service rows

## Out of Scope

- WHOIS tracking for services (services don't have WHOIS)
- Changing the security audit module itself
- Non-standard port auto-creation (user still manually adds IMAPS:993 etc.)

---

## Backend Changes

### 1. Auto-create SSL cert on domain registration

In `POST /api/domains` handler, after saving the domain record:
- Create an `ssl_cert` record: `domain_id={new_domain.id}`, `port=443`, `warn_days={domain.warn_days}`, `critical_days={domain.critical_days}`
- Enqueue an immediate SSL check for the new cert (same as the existing "Check Now" path)

### 2. Auto-trigger security audit after first SSL check

In the SSL probe logic (wherever ssl_cert status is updated after a check):
- After the first successful SSL check on a cert that has `port=443` and was auto-created from a domain:
  - Trigger a security audit against `https://{domain.domain}`
  - Store results on the ssl_cert record (`security_grade`, `security_score`, `security_scanned_at`, `security_findings`)
- Reuse the existing `run_security_audit(url)` function already used by services
- Respect the existing 24h throttle — don't re-run if already scanned within 24h

### 3. No new tables or schema changes

The `ssl_certs` table already has `security_grade`, `security_score`, `security_scanned_at`, `security_findings` columns (added in the HTTP security audit feature). These are reused for domain SSL certs.

### 4. No changes to DELETE

`DELETE /api/domains/{id}` already cascades to linked ssl_certs — auto-created cert is deleted automatically.

---

## Frontend Changes

### 1. Store (`sslDomains.ts`)

Add two new optional fields to `CombinedRow`:

```ts
export interface CombinedRow {
  // ... existing fields ...
  whoisExpiry?: string | null      // domain WHOIS expiry date
  sslExpiry?: string | null        // SSL cert expiry date (for subtitle line)
  sslDaysRemaining?: number | null // SSL cert days remaining (for subtitle)
  whoisDaysRemaining?: number | null // WHOIS days remaining (for subtitle)
}
```

**Domain row construction** — when building a domain's `CombinedRow`:
- Find the linked ssl_cert (port 443, same domain_id) from `sslCerts`
- `expiryDate` = sooner of WHOIS expiry and SSL expiry
- `daysRemaining` = min(whois days, ssl days)
- `status` = worst of domain status and ssl_cert status
- `warnThreshold` = sooner warn threshold
- `securityGrade` = ssl_cert.security_grade (if cert exists)
- `securityScore` = ssl_cert.security_score (if cert exists)
- `whoisExpiry` = domain.expiry_date
- `sslExpiry` = ssl_cert.expiry_date
- `sslDaysRemaining` = ssl_cert.days_remaining
- `whoisDaysRemaining` = domain.days_remaining
- `lastChecked` = sooner of domain.last_checked and ssl_cert.last_checked

**SSL sub-rows for port 443 hidden** — when building SSL rows, skip certs that are port 443 AND have a linked domain (they are displayed merged in the domain row). Non-standard ports (993, 465 etc.) still show as separate SSL rows.

**Service rows** — restored exactly as before the last redesign:

```ts
for (const s of serviceSsl.value) {
  rows.push({
    id: s.id,
    domainName: s.name,
    type: 'service',
    expiryDate: s.ssl_expiry_date,
    daysRemaining: s.ssl_days_remaining,
    status: s.ssl_status ?? 'checking',
    lastChecked: s.ssl_last_checked,
    issuer: s.ssl_issuer,
    serviceId: s.id,
    warnDays: s.ssl_warn_days,
    criticalDays: s.ssl_critical_days,
    warnThreshold: s.ssl_warn_days,
    securityGrade: s.security_grade ?? null,
    securityScore: s.security_score ?? null,
  })
}
```

### 2. `SslDomainsView.vue` — Table

**Expiry cell** — domain rows get a two-line display:
```html
<td class="mono">
  <template v-if="r.type === 'domain' && (r.sslExpiry || r.whoisExpiry)">
    <div>{{ formatDate(r.expiryDate) }}</div>
    <div class="expiry-sub">
      <span v-if="r.sslDaysRemaining != null">SSL: {{ r.sslDaysRemaining }}d</span>
      <span v-else-if="r.sslExpiry === undefined">SSL: pending</span>
      <span v-if="r.whoisDaysRemaining != null"> · WHOIS: {{ r.whoisDaysRemaining }}d</span>
    </div>
  </template>
  <template v-else>{{ formatDate(r.expiryDate) }}</template>
</td>
```

**Security Grade column** — restored for all row types:
```html
<th class="col-security sortable" @click="toggleSort('security')">
  Security<span v-if="sortKey === 'security'" class="sort-arrow">...</span>
</th>
<!-- in tbody -->
<td class="col-security">
  <SecurityGrade
    v-if="r.type !== 'ssl'"
    :grade="r.securityGrade ?? null"
    :score="r.securityScore ?? null"
    size="sm"
  />
  <span v-else class="muted-dash">—</span>
</td>
```

Non-HTTP SSL rows (IMAPS, SMTPS etc.) always show `—`. Domain and service rows always render SecurityGrade — which handles `null` grade internally (shows placeholder).

**`security` sort key** — restored in `sortKey` type union and switch-case.

**Service rows** — restored (remove `r.type !== 'service'` filter from `trackedRows`/`filtered`).

**Type filter** — "Service" option restored.

**"Add SSL Cert" kebab item** — updated hint text:
```html
<button
  v-if="r.type === 'domain'"
  class="kmi"
  @click="openAddSsl(r)"
>Add SSL (non-standard port)</button>
```
The button is always shown for domain rows since port 443 is auto-created and the button is now for non-standard ports only.

### 3. `SslDomainsView.vue` — Stat cards

`trackedRows` reverts to include all types (domain + ssl + service):

```ts
const trackedRows = computed(() => store.combinedRows)
```

Stat card counts remain the same logic (worst status per row).

### 4. CSS additions

```css
.expiry-sub { font-size: 11px; color: var(--muted); margin-top: 2px; }
```

---

## Data Flow

```
User adds domain "example.com"
  → POST /api/domains
  → Domain record saved (WHOIS check queued)
  → ssl_cert record created (port 443, check queued)
  → SSL probe runs → cert status updated
  → Security audit triggered → grade/score stored on ssl_cert
  → GET /api/organizations/{id}/ssl-domains returns merged data
  → Frontend builds CombinedRow with worst expiry + security grade
  → Domain row shows: "2026-09-14 | SSL: 45d · WHOIS: 120d | B | valid"
```

---

## Smoke Test

1. Add a new domain on the SSL & Domains page
2. Verify no separate SSL sub-row appears for port 443 — data is merged into the domain row
3. Domain row shows two-line expiry: primary date + "SSL: Xd · WHOIS: Yd" subtitle
4. Within 24h, security grade appears on the domain row
5. Service rows appear in the table with SSL expiry + security grade (read-only)
6. "View in Services →" is the only kebab action for service rows
7. Type filter shows Domain / SSL / Service options
8. "Add SSL (non-standard port)" button in domain kebab still works — can add IMAPS:993
9. Deleting a domain removes both the WHOIS record and its auto-created SSL:443 cert
10. Stat cards count includes service rows
