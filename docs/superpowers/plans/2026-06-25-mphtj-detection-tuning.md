# MPHTJ Detection Tuning — False Positive Fixes + Field-Aware Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two false-positive detection rules that fire on every Joomla page load, wire the SPPB auto-block dead code path, and add `match_field` to `LogAlertRule` so rules can match the request URI field instead of the full log line.

**Architecture:** Three sequential tasks — (1) add `match_field` column + migration to delete bad rules, (2) fix `_derive_type` and `_general_count` in the evaluator, (3) update `DEFAULT_LOG_RULES` to 6-tuples and seed the field-scoped P1-2 rule. No frontend, security responder, or Fluent Bit changes.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2 async ORM, Alembic, PostgreSQL/TimescaleDB, pytest 9.1 + anyio.

## Global Constraints

- Backend is in `backend/` — all Python paths are relative to that directory.
- Run tests inside the running container: `docker exec opspilot-backend bash -c "cd /app && python -m pytest tests/ -x -q"`
- Migrations live in `backend/migrations/versions/`; latest is `0035_sppb_detection_rules`. New migration is `0036_match_field_and_rule_cleanup` with `down_revision = "0035_sppb_detection_rules"`.
- Apply migrations inside the container: `docker exec opspilot-backend bash -c "cd /app && alembic upgrade head"`
- `LogAlertRule` is in `backend/app/models/other.py` at line 199.
- `_derive_type` and `_general_count` are in `backend/app/services/log_evaluator.py`.
- `DEFAULT_LOG_RULES` and `create_default_rules` are in `backend/app/routers/alert_rules.py`.
- Do not add comments explaining the change or referencing this task — only comments explaining non-obvious WHY.
- No `match_field` UI — it is set only via `DEFAULT_LOG_RULES` seeding and migrations.

---

### Task 1: Data model + migration

**Files:**
- Modify: `backend/app/models/other.py:199-213`
- Create: `backend/migrations/versions/0036_match_field_and_rule_cleanup.py`

**Interfaces:**
- Produces: `LogAlertRule.match_field: Mapped[str | None]` — consumed by Task 2 (`_general_count`, `_derive_type`) and Task 3 (`create_default_rules`).

- [ ] **Step 1: Add `match_field` to `LogAlertRule`**

  In `backend/app/models/other.py`, replace the `LogAlertRule` class body (lines 199–213) with:

  ```python
  class LogAlertRule(Base):
      __tablename__ = "log_alert_rule"

      id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
      server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("server.id", ondelete="CASCADE"), nullable=False, index=True)
      source: Mapped[str] = mapped_column(String(80), nullable=False)
      pattern: Mapped[str] = mapped_column(Text, nullable=False)
      severity: Mapped[str] = mapped_column(String(20), nullable=False)
      threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
      window_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
      cooldown_min: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
      enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
      last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
      match_field: Mapped[str | None] = mapped_column(String(50), nullable=True, default=None)

      server: Mapped["Server"] = relationship(back_populates="log_alert_rules")
  ```

- [ ] **Step 2: Create migration `0036_match_field_and_rule_cleanup.py`**

  Create `backend/migrations/versions/0036_match_field_and_rule_cleanup.py`:

  ```python
  """Add match_field to log_alert_rule; delete two false-positive media PHP rules.

  Revision ID: 0036_match_field_and_rule_cleanup
  Revises: 0035_sppb_detection_rules
  Create Date: 2026-06-25
  """
  from alembic import op
  import sqlalchemy as sa

  revision = "0036_match_field_and_rule_cleanup"
  down_revision = "0035_sppb_detection_rules"
  branch_labels = None
  depends_on = None

  _BAD_PATTERNS = ("%/media/%.PHP%", "%/media/%.pHp%")


  def upgrade() -> None:
      op.add_column("log_alert_rule", sa.Column("match_field", sa.String(50), nullable=True))
      conn = op.get_bind()
      for pattern in _BAD_PATTERNS:
          conn.execute(
              sa.text("DELETE FROM log_alert_rule WHERE pattern = :p"),
              {"p": pattern},
          )


  def downgrade() -> None:
      conn = op.get_bind()
      conn.execute(sa.text("DELETE FROM log_alert_rule WHERE match_field IS NOT NULL"))
      op.drop_column("log_alert_rule", "match_field")
  ```

- [ ] **Step 3: Apply the migration and verify**

  ```bash
  docker exec opspilot-backend bash -c "cd /app && alembic upgrade head"
  ```

  Expected: `Running upgrade 0035_sppb_detection_rules -> 0036_match_field_and_rule_cleanup, ...`

  Then verify:

  ```bash
  docker exec opspilot-postgres psql -U opspilot -d opspilot -c "\d log_alert_rule" | grep match_field
  ```

  Expected: a line containing `match_field | character varying(50) | ...`

  ```bash
  docker exec opspilot-postgres psql -U opspilot -d opspilot -c "SELECT COUNT(*) FROM log_alert_rule WHERE pattern IN ('%/media/%.PHP%', '%/media/%.pHp%')"
  ```

  Expected: `0`

- [ ] **Step 4: Run tests to confirm no regressions**

  ```bash
  docker exec opspilot-backend bash -c "cd /app && python -m pytest tests/ -x -q"
  ```

  Expected: 32 passed (existing suite unchanged — `match_field` is nullable so no existing rule is affected).

- [ ] **Step 5: Commit**

  ```bash
  git add backend/app/models/other.py backend/migrations/versions/0036_match_field_and_rule_cleanup.py
  git commit -m "feat(detection): add match_field to LogAlertRule; delete false-positive media PHP rules"
  ```

---

### Task 2: Evaluator — `_derive_type` fix + field-scoped `_general_count`

**Files:**
- Modify: `backend/app/services/log_evaluator.py:42-106`
- Create: `backend/tests/services/test_log_evaluator_derive.py`

**Interfaces:**
- Consumes: `LogAlertRule.match_field` from Task 1.
- Produces: `_derive_type` returning `"sppb_exploit"` for SPPB patterns and `"webshell_execution"` for field-scoped `.php` rules; `_general_count` querying `raw->>field ILIKE pattern` when `rule.match_field` is set.

- [ ] **Step 1: Write failing tests for `_derive_type`**

  Create `backend/tests/services/test_log_evaluator_derive.py`:

  ```python
  from unittest.mock import MagicMock
  from app.services.log_evaluator import _derive_type


  def _rule(pattern: str, source: str = "%access%", match_field=None):
      r = MagicMock()
      r.source = source
      r.pattern = pattern
      r.match_field = match_field
      return r


  def test_derive_type_sppb_sppagebuilder():
      assert _derive_type(_rule("%com_sppagebuilder%uploadCustomIcon%")) == "sppb_exploit"


  def test_derive_type_sppb_uploadcustomicon_only():
      assert _derive_type(_rule("%uploadCustomIcon%")) == "sppb_exploit"


  def test_derive_type_field_scoped_php_is_webshell_execution():
      assert _derive_type(_rule("%/media/%.php%", match_field="url")) == "webshell_execution"


  def test_derive_type_field_scoped_any_php_is_webshell_execution():
      """match_field set + .php in pattern always returns webshell_execution."""
      assert _derive_type(_rule("%.php%", match_field="url")) == "webshell_execution"


  def test_derive_type_full_message_post_php_still_webshell_upload():
      """Existing %POST%.php% 200 % rule (no match_field) must stay webshell_upload."""
      assert _derive_type(_rule("%POST%.php% 200 %")) == "webshell_upload"


  def test_derive_type_full_message_media_php_200_still_webshell_execution():
      """Existing %/media/%.php% 200 % rule (no match_field) must stay webshell_execution."""
      assert _derive_type(_rule("%/media/%.php% 200 %")) == "webshell_execution"


  def test_derive_type_jce_unchanged():
      assert _derive_type(_rule("%com_jce%profiles.import%")) == "jce_exploit_attempt"


  def test_derive_type_probe_scan_unchanged():
      assert _derive_type(_rule("% 404 %")) == "probe_scan"
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  docker exec opspilot-backend bash -c "cd /app && python -m pytest tests/services/test_log_evaluator_derive.py -x -q"
  ```

  Expected: `FAILED` on `test_derive_type_sppb_sppagebuilder` and `test_derive_type_field_scoped_php_is_webshell_execution` (current code returns `"log_match"` for both).

- [ ] **Step 3: Fix `_derive_type` in `log_evaluator.py`**

  In `backend/app/services/log_evaluator.py`, replace the block starting at the `# POST to a .php` comment:

  ```python
      # POST to a .php = upload attempt; check before the generic execution rule
      # so the seeded `%POST%.php% 200 %` rule classifies as upload, while a GET
      # to a .php in an upload dir (no "post") falls through to execution.
      if "post" in pat and ".php" in pat:
          return "webshell_upload"
      if ".php" in pat and "200" in pat:
          return "webshell_execution"
  ```

  Replace with:

  ```python
      # Field-scoped rules (match_field set) match raw JSONB fields, not the full
      # message — the URL match itself is the high-confidence signal.
      if rule.match_field and ".php" in pat:
          return "webshell_execution"
      # SP Page Builder CVE-2026-48908 — must precede generic .php checks.
      if "sppagebuilder" in pat or "uploadcustomicon" in pat:
          return "sppb_exploit"
      # POST to a .php = upload attempt; check before the generic execution rule
      # so the seeded `%POST%.php% 200 %` rule classifies as upload, while a GET
      # to a .php in an upload dir (no "post") falls through to execution.
      if "post" in pat and ".php" in pat:
          return "webshell_upload"
      if ".php" in pat and "200" in pat:
          return "webshell_execution"
  ```

- [ ] **Step 4: Update `_general_count` to support field routing**

  In `backend/app/services/log_evaluator.py`, replace the entire `_general_count` function (lines 86–106):

  ```python
  async def _general_count(db, rule: LogAlertRule) -> int:
      """Count matching rows in the rule's recent window.

      When ``rule.match_field`` is set, matches the named key in the ``raw``
      JSONB column (e.g. ``raw->>'url'``) instead of the full message.
      ``raw->>key`` returns NULL for rows that predate enrichment or use a
      non-nginx source — ILIKE on NULL is NULL (falsy), so they are excluded.
      """
      if rule.match_field:
          row = await db.execute(
              text(
                  """
                  SELECT COUNT(*) AS cnt
                  FROM server_logs
                  WHERE server_id = :sid
                    AND source LIKE :source
                    AND raw->>:field ILIKE :pattern
                    AND time > now() - make_interval(secs => :win)
                  """
              ),
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
              text(
                  """
                  SELECT COUNT(*) AS cnt
                  FROM server_logs
                  WHERE server_id = :sid
                    AND source LIKE :source
                    AND message ILIKE :pattern
                    AND time > now() - make_interval(secs => :win)
                  """
              ),
              {
                  "sid": str(rule.server_id),
                  "source": rule.source,
                  "pattern": rule.pattern,
                  "win": rule.window_sec,
              },
          )
      return int(row.scalar_one() or 0)
  ```

- [ ] **Step 5: Run tests to verify they all pass**

  ```bash
  docker exec opspilot-backend bash -c "cd /app && python -m pytest tests/ -x -q"
  ```

  Expected: all 8 new tests pass + existing 32 = 40 passed total.

- [ ] **Step 6: Commit**

  ```bash
  git add backend/app/services/log_evaluator.py backend/tests/services/test_log_evaluator_derive.py
  git commit -m "fix(detection): wire sppb_exploit in _derive_type; add field-scoped _general_count branch"
  ```

---

### Task 3: Rule data changes + test updates

**Files:**
- Modify: `backend/app/routers/alert_rules.py:32-112`
- Modify: `backend/tests/routers/test_alert_rules_idempotency.py`

**Interfaces:**
- Consumes: `LogAlertRule.match_field` from Task 1; `_derive_type` routing from Task 2.
- Produces: Updated `DEFAULT_LOG_RULES` (6-tuples, bad rules removed, threshold raised, P1-2 added); `create_default_rules` writes `match_field` to DB.

- [ ] **Step 1: Update `DEFAULT_LOG_RULES` and `create_default_rules`**

  In `backend/app/routers/alert_rules.py`, replace the `DEFAULT_LOG_RULES` definition (lines 32–60) with:

  ```python
  DEFAULT_LOG_RULES: list[tuple[str, str, str, int, int, str | None]] = [
      ("php_app", "%Fatal error%", "critical", 1, 300, None),
      ("nginx_access", '%" 5__ %', "warning", 10, 300, None),
      ("auth", "%Failed password%", "critical", 5, 300, None),
      ("mariadb_error", "%ERROR%", "critical", 1, 300, None),
      ("mariadb_slow", "%Query_time%", "warning", 5, 300, None),
      # ── Security detection (Part 1) ───────────────────────────────────
      ("%access%", "%com_jce%profiles.import%", "critical", 1, 300, None),
      ("%access%", "%POST%.php% 200 %", "critical", 10, 300, None),
      ("%access%", "%/images/%.php% 200 %", "critical", 1, 300, None),
      ("%access%", "%/media/%.php% 200 %", "critical", 1, 300, None),
      ("%access%", "%/uploads/%.php% 200 %", "critical", 1, 300, None),
      ("%access%", "%/files/%.php% 200 %", "critical", 1, 300, None),
      ("%access%", "%/tmp/%.php% 200 %", "critical", 1, 300, None),
      ("%access%", "%/cache/%.php% 200 %", "critical", 1, 300, None),
      ("%access%", "% 404 %", "warning", 20, 300, None),
      ("auditd", "%webroot_write%", "critical", 1, 300, None),
      ("auditd", "%webshell_exec%", "critical", 1, 300, None),
      ("auditd", "%ssh_key_change%", "critical", 1, 300, None),
      ("auditd", "%log_tamper%", "critical", 1, 300, None),
      ("mariadb_general", "%CREATE USER%", "critical", 1, 300, None),
      ("mariadb_general", "%GRANT ALL%", "critical", 1, 300, None),
      ("auth", "%Accepted publickey%", "warning", 1, 300, None),
      # ── SP Page Builder CVE-2026-48908 ────────────────────────────────
      ("%access%", "%com_sppagebuilder%uploadCustomIcon%", "critical", 1, 300, None),
      ("%access%", "%POST%index.php% 200 %", "warning", 10, 60, None),
      # ── Field-scoped rules (match request URI only, not Referer) ──────
      # %/media/%.PHP% and %/media/%.pHp% removed: they match Referer index.php
      # on every Joomla asset load. This rule replaces them by scoping to raw->>'url'.
      ("%access%", "%/media/%.php%", "critical", 1, 300, "url"),
  ]
  ```

  Then replace the `create_default_rules` log loop (lines 90–112) with:

  ```python
      log_added = 0
      for source, pattern, severity, threshold, window_sec, match_field in DEFAULT_LOG_RULES:
          exists = await db.scalar(
              select(LogAlertRule.id)
              .where(
                  LogAlertRule.server_id == server_id,
                  LogAlertRule.source == source,
                  LogAlertRule.pattern == pattern,
              )
              .limit(1)
          )
          if exists:
              continue
          db.add(
              LogAlertRule(
                  server_id=server_id,
                  source=source,
                  pattern=pattern,
                  severity=severity,
                  threshold=threshold,
                  window_sec=window_sec,
                  cooldown_min=60,
                  enabled=True,
                  match_field=match_field,
              )
          )
          log_added += 1
  ```

- [ ] **Step 2: Update the test that checks for `%/media/%.PHP%`**

  In `backend/tests/routers/test_alert_rules_idempotency.py`, replace `test_php_uppercase_rule_present` with tests for the new rules:

  ```python
  def test_field_scoped_media_php_rule_present():
      """Field-scoped rule replaces the deleted case-variant rules."""
      field_rules = [(p, mf) for _, p, _, _, _, mf in DEFAULT_LOG_RULES if mf == "url"]
      assert any("%/media/%.php%" in p for p, _ in field_rules)


  def test_bad_uppercase_php_rules_absent():
      """False-positive rules that match Referer must not be seeded."""
      patterns = [p for _, p, *_ in DEFAULT_LOG_RULES]
      assert "%/media/%.PHP%" not in patterns
      assert "%/media/%.pHp%" not in patterns


  def test_post_php_threshold_raised():
      """Broad POST+php rule must have threshold >= 10 to avoid jsvisit_counter noise."""
      for _, pattern, _, threshold, *_ in DEFAULT_LOG_RULES:
          if pattern == "%POST%.php% 200 %":
              assert threshold >= 10
              return
      pytest.fail("%POST%.php% 200 % rule not found")
  ```

  Remove the old `test_php_uppercase_rule_present` function entirely.

- [ ] **Step 3: Run tests to verify everything passes**

  ```bash
  docker exec opspilot-backend bash -c "cd /app && python -m pytest tests/ -x -q"
  ```

  Expected: 42 passed (32 original + 8 from Task 2 + 3 new − 1 removed = 42).

- [ ] **Step 4: Smoke test — verify the field-scoped rule is seeded with `match_field`**

  Inspect the database on a server that already has rules to confirm existing rules are unaffected (all `match_field = NULL` except the new one). Run `reconfigure-monitoring` on a test server (or check via psql):

  ```bash
  docker exec opspilot-postgres psql -U opspilot -d opspilot -c \
    "SELECT pattern, match_field FROM log_alert_rule WHERE pattern LIKE '%/media/%' LIMIT 10"
  ```

  Expected: rows for `%/media/%.php% 200 %` with `match_field = NULL` (existing rule), and if the P1-2 rule was seeded by `reconfigure-monitoring`, a row for `%/media/%.php%` with `match_field = url`.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/app/routers/alert_rules.py backend/tests/routers/test_alert_rules_idempotency.py
  git commit -m "fix(detection): remove false-positive media PHP rules; add field-scoped P1-2 rule; raise POST threshold to 10"
  ```
