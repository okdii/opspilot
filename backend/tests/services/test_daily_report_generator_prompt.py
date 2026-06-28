"""Tests for SYSTEM_PROMPT HTTP security guidance."""
from app.services.daily_report_generator import SYSTEM_PROMPT


def test_prompt_includes_http_outcome_guidance():
    assert "access_log_security" in SYSTEM_PROMPT


def test_prompt_defines_2xx_as_threat_succeeded():
    assert "2xx" in SYSTEM_PROMPT
    assert "succeeded" in SYSTEM_PROMPT.lower()


def test_prompt_defines_4xx_as_blocked():
    assert "4xx" in SYSTEM_PROMPT
    assert "blocked" in SYSTEM_PROMPT.lower()


def test_prompt_defines_fp_likelihood_field():
    assert "fp_likelihood" in SYSTEM_PROMPT


def test_prompt_defines_all_three_fp_likelihood_values():
    # All three values must appear so the AI knows the full enum
    assert '"low"' in SYSTEM_PROMPT
    assert '"medium"' in SYSTEM_PROMPT
    assert '"high"' in SYSTEM_PROMPT


def test_prompt_includes_false_positive_scanner_rule():
    # Scanner pattern: high request count, zero 2xx → false positive
    assert "cnt_2xx" in SYSTEM_PROMPT


def test_prompt_security_group_requires_fp_likelihood():
    assert "log_anomalies_security" in SYSTEM_PROMPT
    # The prompt must tell the AI to include fp_likelihood for security findings
    assert "fp_likelihood" in SYSTEM_PROMPT
