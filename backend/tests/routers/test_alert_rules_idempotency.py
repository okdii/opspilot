import pytest
from unittest.mock import AsyncMock, MagicMock
from app.routers.alert_rules import DEFAULT_LOG_RULES, create_default_rules


def test_sppb_rule_present():
    patterns = [p for _, p, *_ in DEFAULT_LOG_RULES]
    assert any("com_sppagebuilder" in p and "uploadCustomIcon" in p for p in patterns)


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


def test_sppb_rule_is_critical():
    for _, pattern, severity, *_ in DEFAULT_LOG_RULES:
        if "com_sppagebuilder" in pattern:
            assert severity == "critical"
            return
    pytest.fail("SPPB rule not found")


@pytest.mark.anyio
async def test_create_default_rules_skips_existing_pattern():
    """When all log patterns already exist, log_added must be 0."""
    call_count = 0

    async def fake_scalar(stmt, *a, **kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None   # no existing metric rules → add metric rules
        return "exists"   # every log pattern check returns "exists"

    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=fake_scalar)
    db.add = MagicMock()

    server = MagicMock()
    server.id = "00000000-0000-0000-0000-000000000001"

    _metric_added, log_added = await create_default_rules(db, server)
    assert log_added == 0


@pytest.mark.anyio
async def test_create_default_rules_adds_missing_pattern():
    """When no log rules exist, log_added equals len(DEFAULT_LOG_RULES)."""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)  # nothing exists
    db.add = MagicMock()

    server = MagicMock()
    server.id = "00000000-0000-0000-0000-000000000001"

    _metric_added, log_added = await create_default_rules(db, server)
    assert log_added == len(DEFAULT_LOG_RULES)
