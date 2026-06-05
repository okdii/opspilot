# SSL & Domains Page — Intelligent Summary Redesign

**Date:** 2026-06-05
**Status:** Approved

## Problem

The SSL & Domains page (`/ssl-domains`) currently shows three row types in one table: standalone domains (WHOIS), non-HTTP SSL certs (IMAPS, SMTPS, etc.), and service SSL rows pulled from HTTPS services. Service SSL is auto-tracked when a service is registered — there is no management action available for service rows on this page (kebab only shows "View in Services →"). This creates redundancy: service SSL details live properly in service detail's SecurityTab, yet ghost rows appear here too.

## Goal

1. Remove service rows from the table — service SSL belongs exclusively in service detail.
2. Add an intelligent summary header (stat cards + insight line) so the page communicates health at a glance rather than requiring the user to scan a raw table.
3. Keep all domain WHOIS management and non-HTTP SSL cert management unchanged.

## Out of Scope

- Backend changes — no API changes required.
- Service detail / SecurityTab — untouched.
- The SSL domains store (`sslDomains.ts`) — no changes; the view simply ignores `service` type rows.

---

## Page Structure (top to bottom)

```
Page Header: "SSL & Domain Monitoring"   [Refresh]  [+ Add Domain]
────────────────────────────────────────────────────────────────────
[Total Tracked]  [Critical / Expired]  [Expiring Soon]  [Healthy]
Insight line: "1 cert expired, 1 expiring in 8 days — action needed."
────────────────────────────────────────────────────────────────────
Expiry Timeline (unchanged)
────────────────────────────────────────────────────────────────────
Filter bar  (Type: Domain | SSL — no Service option)
Table: Name | Type | Expiry | Days Left | Bar | Status | Last Checked | ⋮
(no Security column, no service rows)
```

---

## Stat Cards

Reuse the existing `StatCard` component. Count **only domains + non-HTTP SSL certs** — service SSL is excluded entirely.

| Card | Value | Accent colour |
|---|---|---|
| Total Tracked | `domains.length + sslCerts.length` | neutral |
| Critical / Expired | status `critical` or `expired` | red (shows green at 0) |
| Expiring Soon | status `expiring_soon` | amber (neutral at 0) |
| Healthy | status `valid` | green |

Cards sit in a 4-column flex row below the page header.

---

## Smart Insight Line

A single plain-English line rendered below the stat cards. Computed from the same filtered counts (domains + non-HTTP SSL only). Priority — first matching condition wins:

| Condition | Text |
|---|---|
| expired > 0 AND expiring_soon > 0 | `"{expired} expired, {expiring_soon} expiring soon — action needed."` |
| expired > 0 | `"{expired} cert(s) expired — renew immediately."` |
| critical > 0 | `"{critical} item(s) in critical state — expiring very soon."` |
| expiring_soon > 0 | `"{expiring_soon} item(s) expiring soon — plan renewal."` |
| unreachable > 0 | `"{unreachable} item(s) unreachable — check your servers."` |
| total > 0, all valid | `"All {total} items are healthy — nothing to action."` |
| total === 0 | *(hidden — empty state renders instead)* |

**Styling:** compact banner row with a left-border accent. Red tint for expired/critical conditions, amber for expiring/unreachable, green for all-healthy. No icons — stat cards carry the visual weight.

---

## Table Changes

Only these changes to `SslDomainsView.vue`:

1. **Filter out service rows** — in the `filtered` computed, add `r.type !== 'service'` (or filter at `combinedRows` level in the template).
2. **Remove Security column** — remove `th.col-security` and the `td` containing `SecurityGrade`.
3. **Remove "Service" from type filter** — remove `<option value="service">Service</option>`.
4. **Remove `security` sort key** — remove from `sortKey` type union and the sort switch-case.
5. **Remove `col-security` CSS** — the two rules targeting `.col-security`.

Everything else is unchanged: all modals (Add Domain, Edit Domain, Add SSL, Edit SSL, Delete confirm), kebab menu, Check Now, keyboard shortcuts, expiry timeline, ExpiryBar, StatusBadge.

---

## New Computed Properties (SslDomainsView.vue)

Add these to the script setup, derived from `store.domains` and `store.sslCerts` only (not `store.serviceSsl`):

```ts
const trackedRows = computed(() =>
  store.combinedRows.filter(r => r.type !== 'service')
)

const statTotal          = computed(() => trackedRows.value.length)
// statCritical = critical OR expired (used for the stat card)
const statCritical       = computed(() => trackedRows.value.filter(r => r.status === 'critical' || r.status === 'expired').length)
const statExpiring       = computed(() => trackedRows.value.filter(r => r.status === 'expiring_soon').length)
const statHealthy        = computed(() => trackedRows.value.filter(r => r.status === 'valid').length)
// Separate counts used only for insight text messaging
const _statExpiredOnly   = computed(() => trackedRows.value.filter(r => r.status === 'expired').length)
const _statCriticalOnly  = computed(() => trackedRows.value.filter(r => r.status === 'critical').length)
const _statUnreachable   = computed(() => trackedRows.value.filter(r => r.status === 'unreachable').length)

const insightText = computed(() => {
  if (statTotal.value === 0) return null
  const expired  = _statExpiredOnly.value
  const critical = _statCriticalOnly.value
  const expiring = statExpiring.value
  const unreach  = _statUnreachable.value
  const danger   = expired + critical
  if (danger > 0 && expiring > 0)
    return `${danger} critical/expired, ${expiring} expiring soon — action needed.`
  if (expired > 0 && critical > 0)
    return `${expired} expired, ${critical} critical — renew or investigate immediately.`
  if (expired > 0)
    return `${expired} cert(s) expired — renew immediately.`
  if (critical > 0)
    return `${critical} item(s) in critical state — expiring very soon.`
  if (expiring > 0)
    return `${expiring} item(s) expiring soon — plan renewal.`
  if (unreach > 0)
    return `${unreach} item(s) unreachable — check your servers.`
  return `All ${statTotal.value} items are healthy — nothing to action.`
})

const insightTone = computed(() => {
  if (statCritical.value > 0) return 'danger'
  if (statExpiring.value > 0 || _statUnreachable.value > 0) return 'warn'
  return 'ok'
})
```

Replace the existing `summary` computed (used in page header subtitle) with `insightText` or keep both — the header subtitle can still show the item count string.

---

## Implementation Scope

All changes are in one file: `frontend/src/views/ssl-domains/SslDomainsView.vue`.

- Add 4 stat cards below the page header
- Add insight banner below the stat cards
- Filter `r.type !== 'service'` from the filtered computed
- Remove Security column (th + td)
- Remove Service type filter option
- Remove security sort key
- Add CSS for stat cards row and insight banner

No changes to: store, backend, router, other components.

---

## Smoke Test

1. Open `/ssl-domains` — stat cards appear with correct counts
2. Insight line shows correct text for current data state
3. No service rows appear in the table
4. Type filter has only "Domain" and "SSL" options
5. Security column is gone
6. All domain/SSL management still works: Add Domain, Add SSL Cert, Edit, Delete, Check Now
7. Expiry Timeline still renders and dot-click still scrolls + highlights
