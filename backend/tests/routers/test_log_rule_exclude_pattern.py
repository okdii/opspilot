"""Tests for Task 2: exclude_pattern in API schemas and default rules."""
from app.routers.alert_rules import (
    DEFAULT_LOG_RULES,
    LogRuleIn,
    LogRulePatch,
    LogRuleOut,
)


def test_log_rule_in_accepts_exclude_pattern():
    rule = LogRuleIn(
        server_id="00000000-0000-0000-0000-000000000001",
        source="%access%",
        pattern="%POST%.php% 200 %",
        severity="critical",
        threshold=10,
        window_sec=300,
        exclude_pattern="%jsvisit_counter%",
    )
    assert rule.exclude_pattern == "%jsvisit_counter%"


def test_log_rule_in_exclude_pattern_defaults_none():
    rule = LogRuleIn(
        server_id="00000000-0000-0000-0000-000000000001",
        source="%access%",
        pattern="%any%",
        severity="warning",
        threshold=1,
        window_sec=300,
    )
    assert rule.exclude_pattern is None


def test_log_rule_patch_exclude_pattern_defaults_none():
    patch = LogRulePatch()
    assert patch.exclude_pattern is None


def test_log_rule_out_has_exclude_pattern_field():
    fields = LogRuleOut.model_fields
    assert "exclude_pattern" in fields


def test_default_log_rules_are_7_tuples():
    for rule in DEFAULT_LOG_RULES:
        assert len(rule) == 7, f"Rule is not a 7-tuple: {rule}"


def test_post_php_rule_excludes_jsvisit():
    match = next((r for r in DEFAULT_LOG_RULES if r[1] == "%POST%.php% 200 %"), None)
    assert match is not None, "%POST%.php% 200 % rule not found"
    assert match[6] == "%jsvisit_counter%"


def test_sppb_rule_excludes_administrator():
    match = next((r for r in DEFAULT_LOG_RULES if "uploadCustomIcon" in r[1]), None)
    assert match is not None, "SPPB uploadCustomIcon rule not found"
    assert match[6] == "%/administrator/%"


def test_other_rules_have_none_exclude():
    for rule in DEFAULT_LOG_RULES:
        if rule[1] not in ("%POST%.php% 200 %",) and "uploadCustomIcon" not in rule[1]:
            assert rule[6] is None, f"Unexpected exclude_pattern on rule: {rule}"
