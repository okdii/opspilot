# Track B — Rule Tuning

**Document date:** 2026-06-28
**Source audit:** MPHTJ OpsPilot Security Audit Report (2026-06-25)
**Findings addressed:** #2 (jsvisit_counter FPs), #9 (orphan legacy rules), #10/11 (admin SPPB URL collision)
**Finding deferred:** #8 (SSH type mislabel — `new_ssh_login` label is technically correct; auto-block risk too high without safelist)

---

## Goal

Reduce false-positive alert noise and eliminate a detection gap where the SPPB exploit rule fires on legitimate admin uploads, by adding an `exclude_pattern` exclusion field to `LogAlertRule` and cleaning up orphan legacy rules left from a prior migration.

---

## Root causes (from audit)

1. **Finding 2 — jsvisit_counter (910 FPs):** `%POST%.php% 200 %` rule (threshold 10, 300s window) fires `webshell_upload` on legitimate Joomla Analytics Plugin (`com_ajax/jsvisit_counter`) POST requests that exceed 10 in 5 minutes during normal page load bursts. No exclusion mechanism exists.

2. **Finding 9 — orphan rules:** Migration 0036 removed `%/media/%.PHP%` and `%/media/%.pHp%` from `DEFAULT_LOG_RULES` but the DELETE statement only covered the specific server being targeted. Any server with a partial migration may retain these rows.

3. **Finding 10/11 — admin SPPB URL collision:** `%com_sppagebuilder%uploadCustomIcon%` matches both the exploit URL (`/index.php?...`) and the Joomla admin panel URL (`/administrator/index.php?...`). An admin uploading a custom icon triggers `sppb_exploit` + auto-block on their own IP.

---

## What already exists

- `LogAlertRule.match_field: String(50)` — routes evaluator to `raw->>:field ILIKE :pattern` (migration 0036)
- `_general_count()` in `log_evaluator.py:93` — two branches: field-scoped and full-message
- `LogRuleIn`, `LogRulePatch`, `LogRuleOut` in `alert_rules.py:160-192` — no `exclude_pattern` yet
- `DEFAULT_LOG_RULES` is a 6-tuple list (migration 0036 extended to 6-tuple)
- Migration chain: `0035_sppb_detection_rules` → `0036_match_field_cleanup` → **(new) 0037**

---

## Architecture

```
LogAlertRule
    ├── source, pattern, match_field   (existing)
    └── exclude_pattern                (NEW — nullable VARCHAR 255)

_general_count(db, rule)
    ├── if match_field:
    │       AND (:excl IS NULL OR message NOT ILIKE :excl)
    └── else:
            AND (:excl IS NULL OR message NOT ILIKE :excl)

Migration 0037
    ├── ADD COLUMN exclude_pattern VARCHAR(255) NULL
    ├── DELETE orphan legacy rules (%/media/%.PHP%, %/media/%.pHp%)
    └── BACKFILL exclude_pattern on existing server rules
            %POST%.php% 200 %                  → '%jsvisit_counter%'
            %com_sppagebuilder%uploadCustomIcon% → '%/administrator/%'
```

---

## Section 1 — `LogAlertRule` model

**File:** `backend/app/models/other.py`

Add after `match_field`:

```python
exclude_pattern: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
```

---

## Section 2 — `_general_count` exclusion clause

**File:** `backend/app/services/log_evaluator.py:93`

Both SQL branches get an exclusion clause. When `exclude_pattern` is `None`, the `(:excl IS NULL OR ...)` condition is always true (no filtering).

**Field-scoped branch** (match_field set):

```sql
SELECT COUNT(*) AS cnt
FROM server_logs
WHERE server_id = :sid
  AND source LIKE :source
  AND raw->>:field ILIKE :pattern
  AND (:excl IS NULL OR message NOT ILIKE :excl)
  AND time > now() - make_interval(secs => :win)
```

**Plain-message branch:**

```sql
SELECT COUNT(*) AS cnt
FROM server_logs
WHERE server_id = :sid
  AND source LIKE :source
  AND message ILIKE :pattern
  AND (:excl IS NULL OR message NOT ILIKE :excl)
  AND time > now() - make_interval(secs => :win)
```

Add `"excl": rule.exclude_pattern` to both parameter dicts.

---

## Section 3 — API schemas

**File:** `backend/app/routers/alert_rules.py`

Add `exclude_pattern: str | None = None` to all three schemas:

```python
class LogRuleIn(BaseModel):
    ...
    exclude_pattern: str | None = None

class LogRulePatch(BaseModel):
    ...
    exclude_pattern: str | None = None

class LogRuleOut(BaseModel):
    ...
    exclude_pattern: str | None = None
```

`LogRuleOut` uses `model_config = {"from_attributes": True}` (or equivalent) — verify the existing Out schema maps attributes correctly and add `exclude_pattern` consistently.

In the PATCH handler for log rules, add:
```python
if body.exclude_pattern is not None:
    rule.exclude_pattern = body.exclude_pattern or None  # empty string → NULL
```

---

## Section 4 — Default rules (7-tuple)

**File:** `backend/app/routers/alert_rules.py`

`DEFAULT_LOG_RULES` becomes a 7-tuple: `(source, pattern, severity, threshold, window_sec, match_field, exclude_pattern)`.

```python
DEFAULT_LOG_RULES: list[tuple[str, str, str, int, int, str | None, str | None]] = [
    ("php_app",          "%Fatal error%",                        "critical",  1,  300, None, None),
    ("nginx_access",     '%" 5__ %',                             "warning",  10,  300, None, None),
    ("auth",             "%Failed password%",                    "critical",  5,  300, None, None),
    ("mariadb_error",    "%ERROR%",                              "critical",  1,  300, None, None),
    ("mariadb_slow",     "%Query_time%",                         "warning",   5,  300, None, None),
    # ── Security detection (Part 1) ──────────────────────────────────────
    ("%access%",         "%com_jce%profiles.import%",            "critical",  1,  300, None, None),
    ("%access%",         "%POST%.php% 200 %",                    "critical", 10,  300, None, "%jsvisit_counter%"),
    ("%access%",         "%/images/%.php% 200 %",                "critical",  1,  300, None, None),
    ("%access%",         "%/media/%.php% 200 %",                 "critical",  1,  300, None, None),
    ("%access%",         "%/uploads/%.php% 200 %",               "critical",  1,  300, None, None),
    ("%access%",         "%/files/%.php% 200 %",                 "critical",  1,  300, None, None),
    ("%access%",         "%/tmp/%.php% 200 %",                   "critical",  1,  300, None, None),
    ("%access%",         "%/cache/%.php% 200 %",                 "critical",  1,  300, None, None),
    ("%access%",         "% 404 %",                              "warning",  20,  300, None, None),
    ("auditd",           "%webroot_write%",                      "critical",  1,  300, None, None),
    ("auditd",           "%webshell_exec%",                      "critical",  1,  300, None, None),
    ("auditd",           "%ssh_key_change%",                     "critical",  1,  300, None, None),
    ("auditd",           "%log_tamper%",                         "critical",  1,  300, None, None),
    ("mariadb_general",  "%CREATE USER%",                        "critical",  1,  300, None, None),
    ("mariadb_general",  "%GRANT ALL%",                          "critical",  1,  300, None, None),
    ("auth",             "%Accepted publickey%",                 "warning",   1,  300, None, None),
    # ── SP Page Builder CVE-2026-48908 ───────────────────────────────────
    ("%access%",         "%com_sppagebuilder%uploadCustomIcon%", "critical",  1,  300, None, "%/administrator/%"),
    ("%access%",         "%POST%index.php% 200 %",               "warning",  10,   60, None, None),
    # ── Field-scoped rules ────────────────────────────────────────────────
    ("%access%",         "%/media/%.php%",                       "critical",  1,  300, "url", None),
]
```

Update `create_default_rules` loop to unpack 7-tuple:
```python
for source, pattern, severity, threshold, window_sec, match_field, exclude_pattern in DEFAULT_LOG_RULES:
```
And pass `exclude_pattern=exclude_pattern` when constructing `LogAlertRule`.

---

## Section 5 — Migration 0037

**File:** `backend/migrations/versions/0037_exclude_pattern.py`

```python
revision = "0037_exclude_pattern"       # 19 chars — fits varchar(32)
down_revision = "0036_match_field_cleanup"
```

**Upgrade:**

```python
def upgrade():
    # 1. Add column
    op.add_column("log_alert_rule",
        sa.Column("exclude_pattern", sa.String(255), nullable=True))

    # 2. Delete orphan legacy rules from all servers
    op.execute(
        "DELETE FROM log_alert_rule "
        "WHERE pattern IN ('%/media/%.PHP%', '%/media/%.pHp%')"
    )

    # 3. Backfill exclude_pattern on existing server rules
    op.execute(
        "UPDATE log_alert_rule "
        "SET exclude_pattern = '%jsvisit_counter%' "
        "WHERE pattern = '%POST%.php% 200 %'"
    )
    op.execute(
        "UPDATE log_alert_rule "
        "SET exclude_pattern = '%/administrator/%' "
        "WHERE pattern LIKE '%com_sppagebuilder%uploadCustomIcon%'"
    )
```

**Downgrade:**

```python
def downgrade():
    op.drop_column("log_alert_rule", "exclude_pattern")
```

---

## Files changed

| File | Change |
|------|--------|
| `backend/app/models/other.py` | Add `exclude_pattern` column to `LogAlertRule` |
| `backend/app/services/log_evaluator.py` | Add exclusion clause to both `_general_count` branches |
| `backend/app/routers/alert_rules.py` | Add `exclude_pattern` to `LogRuleIn`, `LogRulePatch`, `LogRuleOut`; update 7-tuple `DEFAULT_LOG_RULES`; PATCH handler; `create_default_rules` loop |
| `backend/migrations/versions/0037_exclude_pattern.py` | New migration: add column, delete orphans, backfill |

No frontend changes needed — `exclude_pattern` surfaces via the existing log rule edit UI once `LogRuleOut` includes it.

---

## What is NOT in this spec

- Finding 8 (SSH type mislabel) — deferred; auto-blocking `new_ssh_login` risks blocking legitimate admin SSH without a safelist
- UI for exclude_pattern visibility — the existing alert rules table renders all `LogRuleOut` fields; no new component needed
- Per-server exclude_pattern override — global default is sufficient; admins can PATCH individual rules if needed

---

## Testing

1. `_general_count` with `exclude_pattern` set: two log lines matching pattern, one also containing exclude string → count = 1
2. `_general_count` with `exclude_pattern = None` → no filtering, behaves as before
3. `LogRuleIn` / `LogRulePatch` pydantic validation: `exclude_pattern` accepted and defaults to `None`
4. Migration 0037 upgrade: `%/media/%.PHP%` and `%/media/%.pHp%` rows absent; `exclude_pattern` populated on the two backfilled rules
5. End-to-end on MPHTJ: jsvisit_counter POST burst does not fire alert; admin SPPB upload does not fire alert
