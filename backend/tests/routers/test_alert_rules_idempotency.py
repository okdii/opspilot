import pytest
from unittest.mock import AsyncMock, MagicMock
from app.routers.alert_rules import DEFAULT_LOG_RULES, create_default_rules


def test_sppb_rule_present():
    patterns = [p for _, p, *_ in DEFAULT_LOG_RULES]
    assert any("com_sppagebuilder" in p and "uploadCustomIcon" in p for p in patterns)


def test_php_uppercase_rule_present():
    patterns = [p for _, p, *_ in DEFAULT_LOG_RULES]
    assert any("/media/%.PHP%" in p for p in patterns)


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
