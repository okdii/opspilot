"""Tests for Task 6: sppb_exploit wiring, _BLOCK_CATEGORY map, and auto-unblock exclusion."""
from app.services.security_responder import (
    CONFIDENCE, ACTION_PLAN, _IP_LOG_PATTERNS, _BLOCK_CATEGORY,
)


def test_sppb_in_confidence():
    assert CONFIDENCE.get("sppb_exploit") == "high"


def test_sppb_in_action_plan():
    assert ACTION_PLAN.get("sppb_exploit") == [("block_ip", 1)]


def test_sppb_in_ip_log_patterns():
    assert "%com_sppagebuilder%" in _IP_LOG_PATTERNS.get("sppb_exploit", "")


def test_exploit_types_map_to_exploit():
    for t in ("jce_exploit_attempt", "sppb_exploit", "webshell_upload",
              "webshell_execution", "webshell_command_exec"):
        assert _BLOCK_CATEGORY.get(t) == "exploit", f"{t} should be 'exploit'"


def test_scanner_maps_to_scanner():
    assert _BLOCK_CATEGORY.get("probe_scan") == "scanner"


def test_ssh_brute_force_maps_to_ssh():
    assert _BLOCK_CATEGORY.get("ssh_brute_force") == "ssh"
