# Daily Report — HTTP Security Awareness & False Positive Detection

**Date:** 2026-06-28
**Status:** Approved

## Problem

The AI daily report already receives security alert messages with embedded `[HTTP NNN]` codes (added in v1.2.103), but the AI prompt has no instructions to interpret those codes. It cannot distinguish a blocked probe (HTTP 404) from a successful attack (HTTP 200), and it has no data to reason about false positives.

## Goal

Give the AI enough structured data and prompt guidance to:
1. Classify HTTP security events as **threat succeeded** vs **threat blocked/failed**
2. Flag likely false positives (scanners that got nothing back, probes that all 4xx'd)
3. Calibrate finding severity based on actual HTTP outcomes rather than pattern matches alone

## Scope

Two files changed. No migrations. No frontend work.

---

## Design

### 1. Data Collection (`daily_report_collector.py`)

Add a new `_access_log_security()` async function. Wire it into `collect_for_date()` as a new top-level key `access_log_security`.

Queries run against `server_logs WHERE source LIKE '%access%'` using regex on the `message` field (CLF format), consistent with the existing `_http_status_summary` approach in the log evaluator.

**Sub-section 1 — Status distribution:**
```sql
SELECT
    CASE
        WHEN code::int BETWEEN 200 AND 299 THEN '2xx'
        WHEN code::int BETWEEN 300 AND 399 THEN '3xx'
        WHEN code::int BETWEEN 400 AND 499 THEN '4xx'
        WHEN code::int BETWEEN 500 AND 599 THEN '5xx'
        ELSE 'other'
    END AS status_class,
    COUNT(*) AS n
FROM server_logs
WHERE source LIKE '%access%' AND time in range
  AND (regexp_match(message, '(\d{3}) '))[1] IS NOT NULL
GROUP BY status_class
```
Returns: `{ "2xx": 1420, "3xx": 88, "4xx": 312, "5xx": 4 }`

**Sub-section 2 — Top IPs (top 10 by total requests):**
```sql
SELECT
    (regexp_match(message, '^(\S+)'))[1] AS ip,
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE code::int BETWEEN 200 AND 299) AS cnt_2xx,
    COUNT(*) FILTER (WHERE code::int BETWEEN 400 AND 499) AS cnt_4xx,
    COUNT(*) FILTER (WHERE code::int BETWEEN 500 AND 599) AS cnt_5xx
FROM server_logs
WHERE source LIKE '%access%' AND time in range
GROUP BY ip ORDER BY total DESC LIMIT 10
```

**Sub-section 3 — Top security-pattern paths (top 10):**
Filters for paths matching `.php`, `/wp-admin`, `/xmlrpc`, `/.env`, `/shell`, `/admin`, `/config` using ILIKE on message.
```sql
SELECT
    (regexp_match(message, '"(?:GET|POST|PUT|DELETE|HEAD|OPTIONS|PATCH) (\S+)'))[1] AS path,
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE code::int BETWEEN 200 AND 299) AS cnt_2xx,
    COUNT(*) FILTER (WHERE code::int BETWEEN 400 AND 499) AS cnt_4xx
FROM server_logs
WHERE source LIKE '%access%' AND time in range
  AND (message ILIKE '%.php%' OR message ILIKE '%/wp-admin%' OR message ILIKE '%/xmlrpc%'
       OR message ILIKE '%/.env%' OR message ILIKE '%/shell%' OR message ILIKE '%/admin%'
       OR message ILIKE '%/config%')
GROUP BY path ORDER BY total DESC LIMIT 10
```

**Collected shape:**
```json
{
  "access_log_security": {
    "status_distribution": { "2xx": 1420, "3xx": 88, "4xx": 312, "5xx": 4 },
    "top_ips": [
      { "ip": "45.33.32.156", "total": 240, "cnt_2xx": 0, "cnt_4xx": 240, "cnt_5xx": 0 },
      { "ip": "103.21.x.x",   "total": 12,  "cnt_2xx": 8,  "cnt_4xx": 4,  "cnt_5xx": 0 }
    ],
    "top_security_paths": [
      { "path": "/wp-admin/install.php", "total": 55, "cnt_2xx": 0, "cnt_4xx": 55 },
      { "path": "/shell.php",            "total": 3,  "cnt_2xx": 3, "cnt_4xx": 0 }
    ]
  }
}
```

---

### 2. AI Prompt Update (`daily_report_generator.py`)

Append a new block to `SYSTEM_PROMPT` after the existing severity rules.

**HTTP threat outcome rules:**
- `2xx` response on a security-pattern path (`.php`, `/wp-admin`, `/xmlrpc`, `/.env`, `/shell`) → threat **succeeded** → severity must be `danger`
- `4xx`/`5xx` only on security-pattern paths → attack **blocked** → cap at `warn`, note it was blocked
- Alert message containing `[HTTP 200]` or `[HTTP 201]` → confirmed real incident
- Alert message containing only `[HTTP 403]`, `[HTTP 404]`, `[HTTP 429]` → blocked/probe → cap at `warn` or `info`

**False positive detection rules:**
- IP with high `total` but `cnt_2xx == 0` → scanner that found nothing → flag as likely false positive, use `info` severity
- IP with `cnt_2xx > 0` on security paths → confirmed attacker → `danger`
- Many IPs each making few requests with all 4xx → automated probe sweep, not a targeted attack → single `warn` finding, not per-IP findings

**Output schema extension:**

Add optional `fp_likelihood` field to each finding:
```json
{
  "id": "php_probe_sweep",
  "group": "log_anomalies_security",
  "severity": "warn",
  "fp_likelihood": "high",
  "title": "PHP probe sweep — all requests returned 404",
  "description": "45.33.x.x made 240 requests to PHP paths, all returned 404. No successful access.",
  "fix": "Add rate-limit rule for this IP range in your WAF."
}
```

`fp_likelihood` values: `"low"` (clear threat), `"medium"` (ambiguous), `"high"` (likely false positive). Stored in `findings` JSONB automatically — no migration needed. Frontend ignores unknown fields gracefully.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/services/daily_report_collector.py` | Add `_access_log_security()` function; wire into `collect_for_date()` |
| `backend/app/services/daily_report_generator.py` | Extend `SYSTEM_PROMPT` with HTTP outcome rules, false positive guidance, `fp_likelihood` field |

## Not In Scope

- Frontend display of `fp_likelihood` (future task)
- Per-vhost HTTP breakdown
- Real-time alert amendments based on HTTP outcome
