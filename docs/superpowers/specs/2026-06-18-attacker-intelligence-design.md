# Attacker Intelligence — Design Spec

**Date:** 2026-06-18
**Status:** Approved for planning
**Sub-project:** #1 of the Threat Intelligence roadmap (Attacker Intelligence → Faster Response → Attack-Campaign View → Effectiveness & Reporting)

## Goal

Add an **Attackers** sub-tab to the Server → Security tab that pivots the existing
security alerts/actions by **source IP** into attacker profiles, enriched with
AbuseIPDB reputation, plus a global attack-trend chart. This answers questions the
current per-event timeline cannot: *who* is attacking us, *how far* each attacker
got through the kill-chain, *how dangerous* the IP is (crowd-sourced reputation),
and *whether attacks are increasing over time*.

v1 is **read-only intelligence**. Manual block/unblock from this tab is explicitly
out of scope — it belongs to sub-project #2 ("Faster Response").

## Non-Goals (v1)

- Manual block / unblock buttons (→ sub-project #2).
- Persisting a `source_ip` column on `alert` / backfill (→ future upgrade if
  attribution gaps prove painful; see "IP attribution" below).
- Per-attacker trend charts (v1 ships a single global trend).
- Reputation providers other than AbuseIPDB (the cache layer is provider-agnostic
  so others can be added later, but only AbuseIPDB is wired in v1).
- Cross-tab navigation into the Threat Intelligence timeline (the Attackers tab is
  self-contained; clicking a row expands inline).

## IP Attribution (Approach A — derive at query time)

Alerts are keyed by alert, not by IP, so each attacker profile is built by
resolving an IP per alert **at query time** — no schema change, works on all
historical data immediately.

Resolution order per alert (cheap, no per-alert log queries):

1. **Inline regex on `alert.message`** — the first IPv4 match. probe_scan and the
   SSH alert types carry the IP inline (this reuses the same first step as
   `security_responder._extract_ip`).
2. **Fallback: the linked `block_ip` action's `target`** — for alerts whose message
   has no inline IP but which the responder mitigated with a `block_ip`
   (`SecurityAction.action_type == "block_ip"`, `SecurityAction.alert_id == alert.id`,
   `target` is an IPv4).
3. **Unattributed** — if neither yields an IP, the alert is **excluded** from the
   attacker grouping (it still appears in the existing incident timeline). This is
   the known limitation of Approach A: a webshell/file event with no inline IP and
   no block action will not attribute to an attacker. Documented as a v1 caveat,
   not a bug.

The expensive log-line fallback in `_extract_ip` (step 2 of that function, which
queries `server_logs`) is **NOT** used here — it is per-alert and would not scale
across an aggregate grouping. We deliberately use only the two O(1) sources above.

A shared helper extracts the inline-IPv4 regex so the responder and the new
attacker grouping share one source of truth for "the IP in this message":

- Add `extract_inline_ip(message: str) -> str | None` to a shared location
  (`backend/app/services/ip_intel.py`) and have `security_responder._extract_ip`
  call it for its first step. This keeps the regex DRY without changing responder
  behavior.

## Data Model

### New table: `ip_intel`

Caches AbuseIPDB reputation per IP. Provider-agnostic column set (AbuseIPDB fields
map directly; future providers populate the same columns where they overlap and
stash the rest in `raw`).

| column            | type          | notes                                             |
|-------------------|---------------|---------------------------------------------------|
| `ip`              | `inet`/`text` PK | the attacker IPv4                              |
| `abuse_score`     | `smallint`    | AbuseIPDB `abuseConfidenceScore` 0–100             |
| `country_code`    | `varchar(2)`  | ISO 3166 alpha-2, nullable                         |
| `isp`             | `text`        | nullable                                           |
| `usage_type`      | `text`        | e.g. "Data Center/Web Hosting", nullable           |
| `total_reports`   | `integer`     | AbuseIPDB `totalReports`, nullable                 |
| `last_reported_at`| `timestamptz` | AbuseIPDB `lastReportedAt`, nullable               |
| `raw`             | `jsonb`       | full provider response for forward-compat          |
| `fetched_at`      | `timestamptz` | when we last hit the provider (TTL anchor)         |

- PK on `ip` for upsert + fast cache lookup.
- Alembic migration creates the table.

### Settings additions (`app_settings`, singleton id=1)

Beside the existing encrypted provider creds (`ai_api_key_encrypted`,
`discord_webhook_url`):

- `abuseipdb_enabled: bool` — `server_default="false"`, not null.
- `abuseipdb_api_key_encrypted: text` — nullable, encrypted with the same helper
  used for `ai_api_key_encrypted` / `smtp_password_encrypted`.

Surfaced in the existing Settings page in a "Threat Intelligence" / reputation
section next to the AI provider config. When disabled or key absent, enrichment is
skipped entirely and the UI shows attacker profiles without reputation badges.

## Backend Services & Endpoints

### `backend/app/services/ip_intel.py` (new)

- `extract_inline_ip(message: str) -> str | None` — shared inline-IPv4 regex (see
  IP Attribution).
- `is_public_ip(ip: str) -> bool` — reject private/loopback/reserved (mirrors the
  guard already in `response_channel`; we never send a private IP to AbuseIPDB).
- `async def enrich(db, ip) -> IpIntel | None` — cache-first:
  1. Look up `ip_intel` by `ip`. If present and `fetched_at` within TTL
     (`_TTL = timedelta(days=7)`), return it.
  2. If AbuseIPDB disabled, no key, or `not is_public_ip(ip)`, return the cached
     row if any, else `None` (no API call).
  3. Otherwise call AbuseIPDB `GET https://api.abuseipdb.com/api/v2/check`
     (`ipAddress`, `maxAgeInDays=90`) with header `Key: <decrypted key>` and
     `Accept: application/json`. On success, upsert the `ip_intel` row and return
     it. On any error (network, non-200, rate-limit 429), **best-effort**: log a
     warning, return the stale cached row if any, else `None`. Never raise into the
     request path.
- `async def enrich_many(db, ips: list[str]) -> dict[str, IpIntel]` — enrich a
  bounded batch (the current page, ≤20). Sequential awaits are fine at this size;
  the cache absorbs repeat page loads. This is the **lazy + cached, page-scoped**
  strategy that keeps us inside AbuseIPDB's ~1000/day free tier.

### `GET /api/servers/{server_id}/security/attackers`

Lives in `security_events.py` (alongside `/security/events`, `/security/stages`)
or a new `security_attackers.py` router — implementer's call, following the
existing router-per-concern pattern.

**Query params:** `sort` ∈ {`last_seen` (default), `events`, `severity`},
`limit` (default 20, 1–100), `offset` (default 0).

**Logic:**
1. Select security alerts for the server:
   `select(Alert).where(Alert.server_id == server_id, Alert.type.in_(SECURITY_TYPES))`.
2. Left-join / separately fetch `SecurityAction` rows for those alerts (for the
   `block_ip` target fallback and the per-IP `mitigations` count / `blocked` flag).
3. In Python, resolve an IP per alert (IP Attribution order), drop unattributed
   alerts, and group by IP into profiles:
   - `ip`
   - `event_count`
   - `first_seen` (min `sent_at`), `last_seen` (max `sent_at`)
   - `stages` — distinct kill-chain stages walked, ordered by `STAGE_ORDER`
     (reuse `STAGE` map from `security_events.py`)
   - `critical_count`, `warning_count`
   - `mitigations` — count of `SecurityAction`s whose resolved target is this IP
   - `blocked` — true if any such action is `block_ip`, `status == "executed"`,
     and not reverted/expired (i.e. an active block)
   - `last_type`, `last_message` — from the newest alert for this IP
4. Sort the grouped list by `sort` (last_seen desc / events desc / severity:
   critical_count desc then event_count desc), compute `total = len(groups)`,
   slice `[offset : offset+limit]`.
5. Enrich the **sliced page** via `ip_intel.enrich_many` and attach an
   `intel` object per item (`abuse_score`, `country_code`, `isp`, `usage_type`,
   `total_reports`, `last_reported_at`) or `null` when unavailable.
6. Return `{ items: [...], total }`.

### `GET /api/servers/{server_id}/security/attackers/{ip}/events`

For the inline-expand detail: the event history for one IP. Returns that IP's
security alerts newest-first (same `_row` shape the incident timeline already
uses), so the expanded row can render a compact event list. Re-resolves the IP per
alert and filters to the requested `ip`. Paginated (`limit` default 20, `offset`).

### `GET /api/servers/{server_id}/security/trend`

**Query param:** `days` (default 30, 1–90).

Global attack volume over time for the trend chart:
`SELECT date_trunc('day', sent_at) AS day, severity, count(*) ... WHERE server_id = :id
AND type IN SECURITY_TYPES AND sent_at >= now() - :days GROUP BY day, severity`.
Returns `[{ date, critical, warning }, ...]` with zero-filled missing days so the
chart has a continuous axis.

## Frontend

### `SecurityTab.vue` — add the sub-tab

`SubTab` type gains `'attackers'`; add a third button "Attackers" and
`<AttackerIntelligence v-if="subTab === 'attackers'" :server-id="serverId" />`.
No other change.

### New store: `frontend/src/stores/attackers.ts`

Pinia store mirroring the `security.ts` shape:

- `interface AttackerIntel { abuse_score, country_code, isp, usage_type, total_reports, last_reported_at }`
- `interface Attacker { ip, event_count, first_seen, last_seen, stages: string[], critical_count, warning_count, mitigations, blocked, last_type, last_message, intel: AttackerIntel | null }`
- `interface TrendBucket { date: string; critical: number; warning: number }`
- State: `attackers`, `total`, `page`, `sort` (`'last_seen'|'events'|'severity'`),
  `trend: TrendBucket[]`, `loading`, `error`.
- Actions: `fetchAttackers(serverId, p?)`, `setSort(serverId, sort)` (resets to page 0),
  `fetchTrend(serverId, days?)`, `fetchAttackerEvents(serverId, ip, p?)` (for expand).
- `PAGE_SIZE = 20`.

### New component: `components/servers/tabs/security/AttackerIntelligence.vue`

Layout (modern dark dashboard, consistent with the existing Threat Intelligence
tab — applies the UI/UX Pro Max guidance; **reuses existing components first**):

1. **Trend chart** (top) — global attacks/day, stacked by severity. **Reuse the
   existing chart component** that Fail2ban uses (`Fail2banChart.vue` /
   underlying shared chart); if it can't be reused as-is, extend it via props
   rather than fork it (per Component Reuse rule). Empty state when no data.
2. **Top Attackers** panel — header with sort control (`last_seen` / `events` /
   `severity`). Body: a sortable list of attacker rows. Each row shows:
   - **IP** (monospace).
   - **AbuseIPDB badge** — color-graded by `abuse_score` (e.g. green <25,
     amber 25–74, red ≥75), with `total_reports` as a sub-label. Hidden/"—" when
     `intel` is null (AbuseIPDB disabled or lookup failed).
   - **Country flag + ISP** (from `intel`).
   - **Event count**.
   - **Stages-walked mini kill-chain** — reuse `KillChainBar` styling/tokens to
     render the `stages[]` this IP reached (the same 6-stage vocabulary), so the
     row visually shows how deep the attacker got. Extend `KillChainBar` with a
     compact/read-only variant via props if needed rather than duplicating it.
   - **first_seen / last_seen** (reuse `relativeTime` from `@/utils/time`).
   - **Blocked badge** — reuse `StatusBadge` (`resolved` tone when blocked).
   - Click a row → **expand inline** to show `intel` detail + that IP's event
     history (fetched via `/attackers/{ip}/events`), rendered with the same
     event-row presentation the incident timeline uses.
   - Pagination via the existing reusable `Pager` component.
3. **States:** skeleton while loading, error banner on failure, empty state
   ("No attackers detected") when `total === 0`. If AbuseIPDB is disabled, show a
   subtle inline hint linking to Settings ("Enable AbuseIPDB in Settings for
   reputation scoring") — profiles still render without reputation.

**Polling:** mirror the Threat Intelligence cadence — refetch attackers + trend on
a 60s interval; clear on unmount.

## Honest Tradeoffs (call out in UI / docs)

- **Third-party exposure:** enrichment sends attacker IPs to AbuseIPDB. Only public
  IPs are sent (private/loopback are skipped). Enrichment is opt-in (disabled until
  a key is configured).
- **Attribution gaps (Approach A):** IP-less file/webshell events with no linked
  block action are excluded from attacker grouping. Acceptable for v1; upgrade path
  is persisting `source_ip` at detection (Approach B) later.
- **Rate limits:** page-scoped lazy enrichment (≤20 lookups per page, 7-day cache)
  keeps usage well under the free tier.

## Testing

- **Backend unit:** `extract_inline_ip` (hit/miss), `is_public_ip` (private vs
  public), grouping logic (inline-IP attribution, block_ip fallback, unattributed
  exclusion, stages aggregation, blocked flag, sort orders), trend zero-fill,
  `enrich` cache-hit / stale-refresh / disabled / private-IP / API-error paths
  (mock the HTTP call — no live AbuseIPDB in tests).
- **Endpoint smoke (per CLAUDE.md Rule 1):** against the test server, hit
  `/security/attackers`, `/security/attackers/{ip}/events`, `/security/trend`;
  verify shapes and that a known probe_scan IP appears with its stages.
- **Frontend smoke:** open the Attackers sub-tab, verify the trend chart renders,
  the attacker list sorts, a row expands to event history, and the AbuseIPDB
  disabled-hint shows when no key is configured.

## Rollout

Per CLAUDE.md: smoke test → update `PROGRESS.md` + `DASHBOARD.html` → commit + push
`origin main` → bump patch tag (next after `v1.2.65`). Migration runs via the
`migrate` service before backend.
