# MPHTJ Detection Tuning — False Positive Fixes + Field-Aware Matching

**Document date:** 2026-06-24  
**Reference server:** MPHTJ Portal Live (`a22b48b6-ae8b-4d07-98e7-137f653813ca`)  
**Source study:** `MPHTJ Detection Tuning Study — MPHTJ (mphtj.gov.my)` (2026-06-24)

---

## Goal

Fix two false-positive alert rules that fire on normal Joomla traffic, wire the SPPB auto-block that was added in the monitoring hardening but is currently a dead code path, and add field-aware matching so future rules can target the request URI without bleeding into the Referer header field.

---

## Root causes addressed

### False positive 1 — `%/media/%.PHP%` and `%/media/%.pHp%`

nginx combined log format places request URI and Referer on the same line:

```
IP ... "GET /media/vendor/bootstrap/js/popover.min.js HTTP/2.0" 200 11314 "https://mphtj.gov.my/index.php/en/..." "UA"
```

ILIKE on the full `message` column: `/media/` matches the request URI; `.php` (case-insensitive) matches `index.php` in the Referer. Every Joomla page load of a static asset fires these rules. Both patterns were added by migration `0035` without a status-code suffix, so they match regardless of response code.

**Fix:** delete these two rules everywhere; replace with a field-scoped rule that matches `raw->>'url'` only.

### False positive 2 — `%POST%.php% 200 %` threshold 1

jsvisit_counter sends `POST /index.php?plugin=jsvisit_counter...` returning HTTP 200 with a 20-byte body. Single-hit threshold means every page visit fires the "upload shell" alert. The Referer bleed is not the issue here — it is pure threshold over-sensitivity on a legitimate Joomla AJAX endpoint.

**Fix:** raise threshold from 1 to 10. The rule still catches genuine upload bursts.

### Dead `sppb_exploit` auto-block code path

`security_responder.py` has `sppb_exploit` in `ACTION_PLAN` (→ `block_ip`) and `_BLOCK_CATEGORY` (→ `"exploit"`), but `_derive_type` in `log_evaluator.py` never returns `"sppb_exploit"`. The existing `%com_sppagebuilder%uploadCustomIcon%` rule falls through all pattern checks and maps to `"log_match"`. Auto-blocking was never triggered.

**Fix:** add a `sppb_exploit` arm to `_derive_type` before the generic `.php` checks.

---

## Architecture

Three independent changes, applied in a single task sequence:

1. **Data model + migration** — add `match_field VARCHAR(50) NULL` to `log_alert_rule`; delete the two false-positive rules globally.
2. **Evaluator** — fix `_derive_type` SPPB dead path; add field-scoped branch in `_general_count`.
3. **Rule data** — extend `DEFAULT_LOG_RULES` to 6-tuples; raise the POST threshold; add the field-scoped P1-2 rule; update `create_default_rules` to write `match_field`.

No changes to the security responder, frontend, or Fluent Bit config are required.

---

## Section 1 — Data model

### `LogAlertRule` model (`backend/app/models/other.py`)

Add one nullable column:

```python
match_field: Mapped[str | None] = mapped_column(String(50), nullable=True, default=None)
```

Semantics:
- `None` (NULL) → existing behaviour: `message ILIKE :pattern` on the full log line.
- `"url"` → match `raw->>'url' ILIKE :pattern` (nginx request URI, parsed by `_enrich_log`).
- `"method"`, `"status_code"`, `"bytes"` → same pattern, different JSONB key.

Valid field names are the keys written by `_enrich_log` for `nginx_access` source: `url`, `method`, `status_code`, `bytes`. No other sources currently populate `raw` with structured sub-fields.

### Migration `0036_match_field_and_rule_cleanup`

```
down_revision = "0035_sppb_detection_rules"
```

**Up:**
1. `ALTER TABLE log_alert_rule ADD COLUMN match_field VARCHAR(50) NULL`
2. `DELETE FROM log_alert_rule WHERE pattern = '%/media/%.PHP%'`
3. `DELETE FROM log_alert_rule WHERE pattern = '%/media/%.pHp%'`

**Down:**
1. `DELETE FROM log_alert_rule WHERE match_field IS NOT NULL` (clean up any field-scoped rules)
2. `ALTER TABLE log_alert_rule DROP COLUMN match_field`

---

## Section 2 — Evaluator changes

### `_derive_type` fix (`backend/app/services/log_evaluator.py`)

`_derive_type` receives the full `LogAlertRule` object, so it can inspect `rule.match_field` as well as `pat`.

Insert **two** new arms, before the existing `"post" in pat and ".php" in pat` arm:

```python
# Field-scoped PHP rule (match_field="url") — always webshell_execution regardless of
# whether "200" appears in the pattern; the URL match IS the high-confidence signal.
if rule.match_field and ".php" in pat:
    return "webshell_execution"

# SP Page Builder CVE-2026-48908 exploit attempt
if "sppagebuilder" in pat or "uploadcustomicon" in pat:
    return "sppb_exploit"
```

The `webshell_execution` arm must come first because any field-scoped `.php` rule would otherwise fall through to the full-message `"post" in pat and ".php" in pat` check (which would miss it, since `"post"` is not in the media path pattern).

This routes `%com_sppagebuilder%uploadCustomIcon%` (and any future SPPB variant) to `sppb_exploit`, which already has:
- `ACTION_PLAN["sppb_exploit"] = [("block_ip", 1)]` — auto block_ip
- `_BLOCK_CATEGORY["sppb_exploit"] = "exploit"` — permanent block, no auto-unblock
- `CONFIDENCE["sppb_exploit"] = "high"`

No changes to `security_responder.py` are needed.

### `_general_count` field routing

Replace the current single-path query with a conditional:

```python
async def _general_count(db, rule: LogAlertRule) -> int:
    if rule.match_field:
        row = await db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM server_logs
                WHERE server_id = :sid
                  AND source LIKE :source
                  AND raw->>:field ILIKE :pattern
                  AND time > now() - make_interval(secs => :win)
            """),
            {
                "sid": str(rule.server_id),
                "source": rule.source,
                "field": rule.match_field,
                "pattern": rule.pattern,
                "win": rule.window_sec,
            },
        )
    else:
        row = await db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM server_logs
                WHERE server_id = :sid
                  AND source LIKE :source
                  AND message ILIKE :pattern
                  AND time > now() - make_interval(secs => :win)
            """),
            {
                "sid": str(rule.server_id),
                "source": rule.source,
                "pattern": rule.pattern,
                "win": rule.window_sec,
            },
        )
    return int(row.scalar_one() or 0)
```

The `raw->>:field` expression returns `NULL` for rows whose `raw` JSONB does not have the key (non-nginx sources, older rows). `ILIKE` on NULL is NULL (falsy), so those rows are silently excluded — correct behaviour.

---

## Section 3 — Rule data changes

### `DEFAULT_LOG_RULES` format (`backend/app/routers/alert_rules.py`)

Extend from 5-tuple to 6-tuple by adding an optional `match_field` at position 5:

```python
DEFAULT_LOG_RULES: list[tuple[str, str, str, int, int, str | None]] = [
    ...
    ("%access%", "%/media/%.php%", "critical", 1, 300, "url"),  # P1-2, field-scoped
    ...
]
```

All existing entries append `None` as the sixth element.

### Rule removals

Remove from `DEFAULT_LOG_RULES`:
- `("%access%", "%/media/%.PHP%", "critical", 1, 300)` — deleted by migration; remove from code too so new servers don't get it
- `("%access%", "%/media/%.pHp%", "critical", 1, 300)` — same

### Rule threshold change

Change `%POST%.php% 200 %` threshold from `1` to `10`:

```python
("%access%", "%POST%.php% 200 %", "critical", 10, 300, None),
```

### New field-scoped rule

```python
("%access%", "%/media/%.php%", "critical", 1, 300, "url"),
```

Replaces the two deleted case-variant rules. When evaluated against `raw->>'url'`, this matches only if the **request URI** contains `/media/...php` — a static JS/CSS asset load with a Joomla `index.php` Referer will not match because the Referer is in a different field. `_derive_type` routes field-scoped `.php` rules (where `rule.match_field` is set) to `"webshell_execution"`, which has `quarantine_file + block_ip` in `ACTION_PLAN`.

### `create_default_rules` update

Unpack 6-tuples and write `match_field`:

```python
for source, pattern, severity, threshold, window_sec, match_field in DEFAULT_LOG_RULES:
    # existing idempotency check stays the same
    db.add(LogAlertRule(
        server_id=server_id,
        source=source,
        pattern=pattern,
        severity=severity,
        threshold=threshold,
        window_sec=window_sec,
        match_field=match_field,
    ))
```

---

## Files changed

| File | Change |
|------|--------|
| `backend/app/models/other.py` | Add `match_field` to `LogAlertRule` |
| `backend/migrations/versions/0036_match_field_and_rule_cleanup.py` | New migration |
| `backend/app/services/log_evaluator.py` | Fix `_derive_type`; field-scoped `_general_count` |
| `backend/app/routers/alert_rules.py` | 6-tuple format; remove 2 rules; raise threshold; add P1-2 rule; update `create_default_rules` |

---

## What is NOT in this spec

- Per-IP grouping for SPPB 403 blocked events (P1-1 from the study) — handled by existing `probe_scan` path if a future rule uses ` 404 ` pattern; dedicated SPPB per-IP path is a separate enhancement.
- `exclude_pattern` / whitelist negation — the simpler fixes (remove broad rules, add specific ones) achieve the same outcome without a richer rule DSL.
- Exploit User-Agent rules (P0-2) — `%sppb-rce-poc%` and `%sppb-scanner%` were already added by the monitoring hardening migration `0035`; no change needed.
- Frontend UI for `match_field` — admins editing rules in the UI will not see this field; it is set only via `DEFAULT_LOG_RULES` seeding. A rule editor enhancement is a separate spec.

---

## Testing

- After migration, verify `log_alert_rule` has no rows with `pattern = '%/media/%.PHP%'` or `pattern = '%/media/%.pHp%'`.
- Insert a synthetic `server_logs` row with `source = 'nginx_access'`, `message` containing `/media/vendor/bootstrap/js/foo.js` and Referer `index.php`, `raw = {"url": "/media/vendor/bootstrap/js/foo.js", "method": "GET", "status_code": "200", "bytes": "11314"}`. The field-scoped rule `%/media/%.php%` on `match_field = "url"` must return count 0.
- Insert a row where `raw->>'url'` = `/media/com_sppagebuilder/assets/iconfont/abc.PHP`. The same rule must return count 1.
- Confirm `_derive_type` for a rule with pattern `%com_sppagebuilder%uploadCustomIcon%` returns `"sppb_exploit"`.
